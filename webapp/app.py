"""Flask-website voor meerdere panden: dashboard, kamers, betalingen-check,
contracten en documenten, per pand. Login is beperkt tot de gebruikers in
users.json, elk met eigen pand-toegang (zie webapp/auth.py).

Starten (development): python -m webapp.app
Starten (productie): zie README (gunicorn + webapp.app:create_app()).
"""
from __future__ import annotations

import dataclasses
import re
from datetime import date
from decimal import Decimal
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, Response, abort, flash, g, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.drive_client import DriveClient
from kamerverhuur_scanner.models import Tenant
from kamerverhuur_scanner.properties import PropertiesError, find_pand, load_properties, verwijder_pand, zet_pand
from kamerverhuur_scanner.runner import run_check
from kamerverhuur_scanner.sheet_client import SheetClient
from kamerverhuur_scanner.utils import parse_bedrag

from . import ads, contracts
from .aanmeldingen import AanmeldingFout, valideer_en_bouw
from .aanzegging import bereken_aanzeg_status
from .auth import User, load_users, save_users, user_uit_gegevens, verify_login, zet_gebruiker
from .reliability import bereken_betrouwbaarheid

load_dotenv()


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)

    if config is None:
        try:
            config = Config.load()
        except ConfigError as exc:
            raise SystemExit(f"Configuratiefout: {exc}") from exc

    try:
        load_properties(config.properties_file)  # fail fast bij een ongeldig properties.json
    except PropertiesError as exc:
        raise SystemExit(f"Pandenfout: {exc}") from exc

    def _properties() -> list:
        # Steeds opnieuw inlezen (net als users.json) zodat wijzigingen via
        # "Panden beheren" meteen gelden, zonder de app te herstarten.
        try:
            return load_properties(config.properties_file)
        except PropertiesError:
            return []

    app.secret_key = config.flask_secret_key

    @app.template_filter("eur")
    def eur(value) -> str:
        bedrag = f"{Decimal(str(value)):,.2f}"  # bv. "4,209.56"
        bedrag = bedrag.replace(",", "X").replace(".", ",").replace("X", ".")  # -> "4.209,56"
        return f"€{bedrag}"

    @app.template_filter("status_klasse")
    def status_klasse(status_tekst: str) -> str:
        return "status-" + status_tekst.lower().replace(" ", "-")

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(username: str) -> User | None:
        users = load_users(config.users_file)
        gebruiker = users.get(username)
        return user_uit_gegevens(username, gebruiker) if gebruiker else None

    @app.before_request
    def _laad_pand_en_check_toegang():
        if not request.view_args or "pand_slug" not in request.view_args:
            return None
        pand_slug = request.view_args["pand_slug"]
        pand = find_pand(_properties(), pand_slug)
        if pand is None:
            abort(404, f"Pand '{pand_slug}' bestaat niet.")
        g.pand = pand
        if not current_user.is_authenticated:
            return None  # login_required op de route zorgt voor de redirect naar /login
        if not current_user.heeft_toegang(pand_slug):
            return render_template("geen_toegang.html", pand=pand), 403
        return None

    @app.context_processor
    def _template_context():
        eigen_panden = []
        if current_user.is_authenticated:
            eigen_panden = [p for p in _properties() if current_user.heeft_toegang(p.slug)]
        return {"eigen_panden": eigen_panden, "huidig_pand": getattr(g, "pand", None)}

    def _kamer_of_404(sheet: SheetClient, kamer_naam: str) -> Tenant:
        for kamer in sheet.get_kamers():
            if kamer.kamer == kamer_naam:
                return kamer
        abort(404, f"Kamer '{kamer_naam}' niet gevonden.")

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.mag_gebruikers_beheren():
                flash("Je hebt geen toegang tot gebruikersbeheer.")
                return redirect(url_for("start"))
            return view(*args, **kwargs)
        return wrapped

    # --- Login/logout ---

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            users = load_users(config.users_file)
            if verify_login(users, username, password):
                login_user(user_uit_gegevens(username, users[username]))
                return redirect(url_for("start"))
            flash("Onjuiste gebruikersnaam of wachtwoord.")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    # --- Pandkiezer (landingspagina na het inloggen) ---

    @app.route("/")
    @login_required
    def start():
        eigen_panden = [p for p in _properties() if current_user.heeft_toegang(p.slug)]
        if len(eigen_panden) == 1:
            return redirect(url_for("dashboard", pand_slug=eigen_panden[0].slug))
        return render_template("pand_kiezer.html", panden=eigen_panden)

    # --- Gebruikersbeheer (alleen voor beheerders met toegang tot alle panden) ---

    def _panden_uit_form(form) -> tuple[bool, list[str]]:
        alle_panden = form.get("alle_panden") == "on"
        panden = form.getlist("panden") if not alle_panden else []
        return alle_panden, panden

    @app.route("/beheer/gebruikers")
    @login_required
    @admin_required
    def gebruikers_overzicht():
        users = load_users(config.users_file)
        return render_template("gebruikers.html", users=users)

    @app.route("/beheer/gebruikers/nieuw", methods=["GET", "POST"])
    @login_required
    @admin_required
    def gebruiker_nieuw():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            wachtwoord = request.form.get("wachtwoord", "")
            users = load_users(config.users_file)
            if not username:
                flash("Gebruikersnaam is verplicht.")
            elif username in users:
                flash(f"Gebruiker '{username}' bestaat al.")
            elif len(wachtwoord) < 8:
                flash("Gebruik een wachtwoord van minimaal 8 tekens.")
            else:
                alle_panden, panden = _panden_uit_form(request.form)
                zet_gebruiker(users, username, wachtwoord, alle_panden, panden)
                save_users(config.users_file, users)
                flash(f"Gebruiker '{username}' aangemaakt.")
                return redirect(url_for("gebruikers_overzicht"))
        return render_template("gebruiker_form.html", gebruiker=None, username=None, panden=_properties())

    @app.route("/beheer/gebruikers/<username>/bewerken", methods=["GET", "POST"])
    @login_required
    @admin_required
    def gebruiker_bewerken(username: str):
        users = load_users(config.users_file)
        gebruiker = users.get(username)
        if gebruiker is None:
            abort(404, f"Gebruiker '{username}' bestaat niet.")
        if request.method == "POST":
            wachtwoord = request.form.get("wachtwoord", "")
            alle_panden, panden = _panden_uit_form(request.form)
            if wachtwoord and len(wachtwoord) < 8:
                flash("Gebruik een wachtwoord van minimaal 8 tekens.")
            elif username == current_user.id and not alle_panden:
                flash("Je kunt jezelf niet de toegang tot alle panden ontnemen.")
            else:
                zet_gebruiker(users, username, wachtwoord or None, alle_panden, panden)
                save_users(config.users_file, users)
                flash(f"Gebruiker '{username}' bijgewerkt.")
                return redirect(url_for("gebruikers_overzicht"))
        return render_template("gebruiker_form.html", gebruiker=gebruiker, username=username, panden=_properties())

    @app.route("/beheer/gebruikers/<username>/verwijderen", methods=["POST"])
    @login_required
    @admin_required
    def gebruiker_verwijderen(username: str):
        if username == current_user.id:
            flash("Je kunt jezelf niet verwijderen.")
            return redirect(url_for("gebruikers_overzicht"))
        users = load_users(config.users_file)
        if users.pop(username, None) is not None:
            save_users(config.users_file, users)
            flash(f"Gebruiker '{username}' verwijderd.")
        return redirect(url_for("gebruikers_overzicht"))

    # --- Panden beheren (alleen voor beheerders met toegang tot alle panden) ---

    def _pand_gegevens_uit_form(form) -> dict:
        return {
            "naam": form.get("naam", "").strip(),
            "google_sheet_id": form.get("google_sheet_id", "").strip(),
            "google_sheet_worksheet": form.get("google_sheet_worksheet", "").strip() or "Huurders",
            "history_worksheet": form.get("history_worksheet", "").strip() or "Historie",
            "aanmeldingen_worksheet": form.get("aanmeldingen_worksheet", "").strip() or "Aanmeldingen",
            "google_drive_folder_id": form.get("google_drive_folder_id", "").strip() or None,
            "bunq_rekening_iban": form.get("bunq_rekening_iban", "").strip().replace(" ", "").upper(),
        }

    @app.route("/beheer/panden")
    @login_required
    @admin_required
    def panden_overzicht():
        return render_template("panden.html", panden=_properties())

    @app.route("/beheer/panden/nieuw", methods=["GET", "POST"])
    @login_required
    @admin_required
    def pand_nieuw():
        if request.method == "POST":
            slug = request.form.get("slug", "").strip().lower()
            gegevens = _pand_gegevens_uit_form(request.form)
            bestaande_slugs = {p.slug for p in _properties()}
            if not re.fullmatch(r"[a-z0-9-]+", slug or ""):
                flash("Slug mag alleen kleine letters, cijfers en streepjes bevatten.")
            elif slug in bestaande_slugs:
                flash(f"Pand met slug '{slug}' bestaat al.")
            elif not gegevens["naam"] or not gegevens["google_sheet_id"] or not gegevens["bunq_rekening_iban"]:
                flash("Naam, Google Sheet ID en bunq-IBAN zijn verplicht.")
            else:
                zet_pand(config.properties_file, slug, gegevens)
                flash(f"Pand '{gegevens['naam']}' aangemaakt.")
                return redirect(url_for("panden_overzicht"))
        return render_template("pand_form.html", pand=None, slug=None)

    @app.route("/beheer/panden/<slug>/bewerken", methods=["GET", "POST"])
    @login_required
    @admin_required
    def pand_bewerken(slug: str):
        pand = find_pand(_properties(), slug)
        if pand is None:
            abort(404, f"Pand '{slug}' bestaat niet.")
        if request.method == "POST":
            gegevens = _pand_gegevens_uit_form(request.form)
            if not gegevens["naam"] or not gegevens["google_sheet_id"] or not gegevens["bunq_rekening_iban"]:
                flash("Naam, Google Sheet ID en bunq-IBAN zijn verplicht.")
            else:
                zet_pand(config.properties_file, slug, gegevens)
                flash(f"Pand '{gegevens['naam']}' bijgewerkt.")
                return redirect(url_for("panden_overzicht"))
        return render_template("pand_form.html", pand=pand, slug=slug)

    @app.route("/beheer/panden/<slug>/verwijderen", methods=["POST"])
    @login_required
    @admin_required
    def pand_verwijderen(slug: str):
        if len(_properties()) <= 1:
            flash("Je kunt het laatste overgebleven pand niet verwijderen (de site heeft minstens één pand nodig om te starten).")
            return redirect(url_for("panden_overzicht"))
        verwijder_pand(config.properties_file, slug)
        flash(f"Pand '{slug}' verwijderd (gebruikerstoegang tot dit pand blijft ongebruikt in users.json staan, maar heeft geen effect meer).")
        return redirect(url_for("panden_overzicht"))

    # --- Dashboard ---

    @app.route("/pand/<pand_slug>/")
    @login_required
    def dashboard(pand_slug: str):
        cache = state.load(pand_slug)
        totalen = None
        if cache:
            totalen = {
                "verwacht": sum(Decimal(r["verwacht_bedrag"]) for r in cache["resultaten"]),
                "ontvangen": sum(Decimal(r["ontvangen_bedrag"]) for r in cache["resultaten"]),
            }
        sheet = SheetClient(config, g.pand)
        aanzeg_waarschuwingen = [
            (kamer, bereken_aanzeg_status(kamer.contract_einddatum))
            for kamer in sheet.get_kamers()
        ]
        aanzeg_waarschuwingen = [
            (kamer, status)
            for kamer, status in aanzeg_waarschuwingen
            if status and (status.moet_nu_aanzeggen or status.venster_verstreken)
        ]
        return render_template(
            "dashboard.html", cache=cache, totalen=totalen, aanzeg_waarschuwingen=aanzeg_waarschuwingen
        )

    # --- Huurders ---

    @app.route("/pand/<pand_slug>/huurders")
    @login_required
    def huurders(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        kamers = sheet.get_kamers()
        sheet_url = f"https://docs.google.com/spreadsheets/d/{g.pand.google_sheet_id}/edit"
        return render_template("huurders.html", kamers=kamers, sheet_url=sheet_url)

    def _kamer_form_naar_velden(form) -> dict:
        kale_huurprijs = form.get("kale_huurprijs", "").strip()
        servicekosten = form.get("servicekosten", "").strip()
        return {
            "naam": form.get("naam", "").strip(),
            "kamer": form.get("kamer", "").strip(),
            "verwacht_bedrag": parse_bedrag(form.get("verwacht_bedrag", "0")),
            "iban": form.get("iban", "").strip().replace(" ", "").upper() or None,
            "zoekwoord": form.get("zoekwoord", "").strip() or None,
            "kale_huurprijs": parse_bedrag(kale_huurprijs) if kale_huurprijs else None,
            "servicekosten": parse_bedrag(servicekosten) if servicekosten else None,
            "contract_einddatum": form.get("contract_einddatum", "").strip() or None,
            "opmerking": form.get("opmerking", "").strip() or None,
            "email": form.get("email", "").strip() or None,
            "telefoonnummer": form.get("telefoonnummer", "").strip() or None,
        }

    @app.route("/pand/<pand_slug>/huurders/nieuw", methods=["GET", "POST"])
    @login_required
    def huurder_nieuw(pand_slug: str):
        if request.method == "POST":
            sheet = SheetClient(config, g.pand)
            sheet.add_kamer(**_kamer_form_naar_velden(request.form))
            flash("Nieuwe kamer toegevoegd.")
            return redirect(url_for("huurders", pand_slug=pand_slug))
        return render_template("huurder_bewerken.html", kamer=None)

    @app.route("/pand/<pand_slug>/huurders/<kamer_naam>/bewerken", methods=["GET", "POST"])
    @login_required
    def huurder_bewerken(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _kamer_of_404(sheet, kamer_naam)
        if request.method == "POST":
            sheet.update_kamer(row_index=kamer.row_index, **_kamer_form_naar_velden(request.form))
            flash(f"Kamer {kamer_naam} bijgewerkt.")
            return redirect(url_for("huurders", pand_slug=pand_slug))
        return render_template("huurder_bewerken.html", kamer=kamer)

    # --- Betalingen ---

    @app.route("/pand/<pand_slug>/betalingen", methods=["GET", "POST"])
    @login_required
    def betalingen(pand_slug: str):
        net_gecontroleerd = None
        if request.method == "POST":
            _tenants, results, unmatched = run_check(config, g.pand, dry_run=False)
            net_gecontroleerd = {"results": results, "unmatched": unmatched}
        return render_template("betalingen.html", net_gecontroleerd=net_gecontroleerd, cache=state.load(pand_slug))

    # --- Kamers ---

    @app.route("/pand/<pand_slug>/kamers")
    @login_required
    def kamers_overzicht(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        return render_template("kamers.html", kamers=sheet.get_kamers(), cache=state.load(pand_slug))

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>")
    @login_required
    def kamer_detail(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _kamer_of_404(sheet, kamer_naam)
        geschiedenis = sheet.get_geschiedenis(kamer_naam)
        return render_template(
            "kamer_detail.html",
            kamer=kamer,
            geschiedenis=list(reversed(geschiedenis)),
            betrouwbaarheid=bereken_betrouwbaarheid(geschiedenis),
            cache_status=state.status_voor_kamer(state.load(pand_slug), kamer_naam),
            contracten=contracts.list_contracten_voor_kamer(pand_slug, kamer_naam),
            aanzeg_status=bereken_aanzeg_status(kamer.contract_einddatum),
        )

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>/advertentie")
    @login_required
    def kamer_advertentie(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _kamer_of_404(sheet, kamer_naam)
        return render_template("advertentie.html", kamer=kamer, advertentie=ads.genereer_advertentie(g.pand, kamer))

    # --- Aanbod beheren (foto's/video's + beschikbaarheid voor de publieke aanbodpagina) ---

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>/aanbod", methods=["GET", "POST"])
    @login_required
    def kamer_aanbod(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _kamer_of_404(sheet, kamer_naam)
        if request.method == "POST":
            beschikbaar = request.form.get("beschikbaar") == "on"
            omschrijving = request.form.get("omschrijving", "").strip() or None
            sheet.update_aanbod(kamer.row_index, beschikbaar, omschrijving, kamer.advertentie_map_id)
            flash("Aanbod bijgewerkt.")
            return redirect(url_for("kamer_aanbod", pand_slug=pand_slug, kamer_naam=kamer_naam))
        media = []
        if kamer.advertentie_map_id:
            media = DriveClient(config, g.pand).list_bestanden(kamer.advertentie_map_id)
        standaard_omschrijving = kamer.advertentie_omschrijving or ads.genereer_advertentie(g.pand, kamer)["beschrijving"]
        return render_template("kamer_aanbod.html", kamer=kamer, media=media, standaard_omschrijving=standaard_omschrijving)

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>/aanbod/upload", methods=["POST"])
    @login_required
    def kamer_aanbod_upload(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _kamer_of_404(sheet, kamer_naam)
        if not g.pand.google_drive_folder_id:
            flash("Foto's/video's uploaden kan pas als er een Drive-map voor dit pand is ingesteld (zie properties.json).")
            return redirect(url_for("kamer_aanbod", pand_slug=pand_slug, kamer_naam=kamer_naam))
        drive = DriveClient(config, g.pand)
        map_id = kamer.advertentie_map_id
        if not map_id:
            aanbod_map = drive.vind_of_maak_map("Aanbod")
            map_id = drive.vind_of_maak_map(kamer_naam, aanbod_map)
            sheet.update_aanbod(kamer.row_index, kamer.beschikbaar, kamer.advertentie_omschrijving, map_id)
        aantal = 0
        for bestand in request.files.getlist("bestand"):
            if bestand and bestand.filename:
                drive.upload_bestand(bestand.filename, bestand.mimetype, bestand.read(), folder_id=map_id)
                aantal += 1
        flash(f"{aantal} bestand(en) geupload." if aantal else "Geen bestand geselecteerd.")
        return redirect(url_for("kamer_aanbod", pand_slug=pand_slug, kamer_naam=kamer_naam))

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>/aanbod/<file_id>/verwijderen", methods=["POST"])
    @login_required
    def kamer_aanbod_media_verwijderen(pand_slug: str, kamer_naam: str, file_id: str):
        sheet = SheetClient(config, g.pand)
        kamer = _kamer_of_404(sheet, kamer_naam)
        if kamer.advertentie_map_id:
            drive = DriveClient(config, g.pand)
            bestanden = drive.list_bestanden(kamer.advertentie_map_id)
            if any(b.id == file_id for b in bestanden):
                drive.verwijder_bestand(file_id)
                flash("Bestand verwijderd.")
        return redirect(url_for("kamer_aanbod", pand_slug=pand_slug, kamer_naam=kamer_naam))

    # --- Aanmeldingen (reacties op de publieke aanbodpagina) ---

    @app.route("/pand/<pand_slug>/aanmeldingen")
    @login_required
    def aanmeldingen_overzicht(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        return render_template("aanmeldingen.html", rijen=sheet.get_aanmeldingen())

    @app.route("/pand/<pand_slug>/aanmeldingen/wissen", methods=["POST"])
    @login_required
    def aanmeldingen_wissen(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        sheet.wis_aanmeldingen()
        flash("Lijst met aanmeldingen gewist.")
        return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))

    # --- Contracten ---

    @app.route("/pand/<pand_slug>/contracten")
    @login_required
    def contracten_overzicht(pand_slug: str):
        return render_template("contracten.html", contracten=contracts.list_contracten(pand_slug))

    @app.route("/pand/<pand_slug>/contracten/nieuw", methods=["GET", "POST"])
    @login_required
    def contract_nieuw(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        if request.method == "POST":
            bestandsnaam = contracts.genereer_contract(pand_slug, request.form)
            return redirect(url_for("contract_bekijken", pand_slug=pand_slug, bestandsnaam=bestandsnaam))
        return render_template("contract_nieuw.html", kamers=sheet.get_kamers(), vandaag=date.today())

    @app.route("/pand/<pand_slug>/contracten/<bestandsnaam>")
    @login_required
    def contract_bekijken(pand_slug: str, bestandsnaam: str):
        try:
            html = contracts.lees_contract(pand_slug, bestandsnaam)
        except FileNotFoundError:
            abort(404)
        return Response(html, mimetype="text/html")

    # --- Documenten ---

    def _documenten_url(pand_slug: str, folder_id: str | None):
        if folder_id:
            return url_for("documenten_map", pand_slug=pand_slug, folder_id=folder_id)
        return url_for("documenten", pand_slug=pand_slug)

    @app.route("/pand/<pand_slug>/documenten")
    @login_required
    def documenten(pand_slug: str):
        return _documenten_view(pand_slug, None)

    @app.route("/pand/<pand_slug>/documenten/map/<folder_id>")
    @login_required
    def documenten_map(pand_slug: str, folder_id: str):
        return _documenten_view(pand_slug, folder_id)

    def _documenten_view(pand_slug: str, folder_id: str | None):
        if not g.pand.google_drive_folder_id:
            return render_template("documenten.html", bestanden=None, kruimels=[], folder_id=None)
        drive = DriveClient(config, g.pand)
        return render_template(
            "documenten.html",
            bestanden=drive.list_bestanden(folder_id),
            kruimels=drive.get_pad(folder_id),
            folder_id=folder_id,
        )

    @app.route("/pand/<pand_slug>/documenten/upload", methods=["POST"])
    @login_required
    def documenten_upload(pand_slug: str):
        folder_id = request.form.get("folder_id") or None
        if not g.pand.google_drive_folder_id:
            flash("Documenten zijn nog niet ingesteld (google_drive_folder_id ontbreekt in properties.json).")
            return redirect(_documenten_url(pand_slug, folder_id))
        drive = DriveClient(config, g.pand)
        aantal = 0
        for bestand in request.files.getlist("bestand"):
            if bestand and bestand.filename:
                drive.upload_bestand(bestand.filename, bestand.mimetype, bestand.read(), folder_id=folder_id)
                aantal += 1
        flash(f"{aantal} bestand(en) geupload." if aantal else "Geen bestand geselecteerd.")
        return redirect(_documenten_url(pand_slug, folder_id))

    @app.route("/pand/<pand_slug>/documenten/nieuwe-map", methods=["POST"])
    @login_required
    def documenten_nieuwe_map(pand_slug: str):
        folder_id = request.form.get("folder_id") or None
        if not g.pand.google_drive_folder_id:
            flash("Documenten zijn nog niet ingesteld (google_drive_folder_id ontbreekt in properties.json).")
            return redirect(_documenten_url(pand_slug, folder_id))
        naam = request.form.get("naam", "").strip()
        if naam:
            DriveClient(config, g.pand).maak_map(naam, folder_id=folder_id)
            flash(f"Map '{naam}' aangemaakt.")
        return redirect(_documenten_url(pand_slug, folder_id))

    @app.route("/pand/<pand_slug>/documenten/<file_id>/download")
    @login_required
    def documenten_download(pand_slug: str, file_id: str):
        drive = DriveClient(config, g.pand)
        naam, mimetype, inhoud = drive.download_bestand(file_id)
        return Response(
            inhoud,
            mimetype=mimetype,
            headers={"Content-Disposition": f'attachment; filename="{naam}"'},
        )

    # --- Publieke aanbodpagina (geen login, Engelstalig - vooral voor expats) ---

    def _beschikbare_kamer_of_404(sheet: SheetClient, kamer_naam: str) -> Tenant:
        kamer = _kamer_of_404(sheet, kamer_naam)
        if not kamer.beschikbaar:
            abort(404)
        return kamer

    def _eerste_foto(drive: DriveClient, map_id: str | None):
        if not map_id:
            return None
        return next((b for b in drive.list_bestanden(map_id) if b.mimetype.startswith("image/")), None)

    @app.route("/aanbod")
    def aanbod_overzicht():
        kaarten = []
        for pand in _properties():
            sheet = SheetClient(config, pand)
            drive = DriveClient(config, pand) if pand.google_drive_folder_id else None
            for kamer in sheet.get_kamers():
                if not kamer.beschikbaar:
                    continue
                foto = _eerste_foto(drive, kamer.advertentie_map_id) if drive else None
                kaarten.append({"pand": pand, "kamer": kamer, "foto": foto})
        return render_template("aanbod_overzicht.html", kaarten=kaarten)

    @app.route("/aanbod/<pand_slug>/<kamer_naam>")
    def aanbod_detail(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _beschikbare_kamer_of_404(sheet, kamer_naam)
        media = []
        if kamer.advertentie_map_id:
            media = DriveClient(config, g.pand).list_bestanden(kamer.advertentie_map_id)
        omschrijving = kamer.advertentie_omschrijving or ads.genereer_advertentie(g.pand, kamer)["beschrijving"]
        return render_template("aanbod_detail.html", kamer=kamer, media=media, omschrijving=omschrijving)

    @app.route("/aanbod/<pand_slug>/<kamer_naam>/media/<file_id>")
    def aanbod_media(pand_slug: str, kamer_naam: str, file_id: str):
        sheet = SheetClient(config, g.pand)
        kamer = _beschikbare_kamer_of_404(sheet, kamer_naam)
        if not kamer.advertentie_map_id:
            abort(404)
        drive = DriveClient(config, g.pand)
        bestanden = drive.list_bestanden(kamer.advertentie_map_id)
        if not any(b.id == file_id for b in bestanden):
            abort(404)
        _naam, mimetype, inhoud = drive.download_bestand(file_id)
        return Response(inhoud, mimetype=mimetype, headers={"Cache-Control": "public, max-age=3600"})

    @app.route("/aanbod/<pand_slug>/<kamer_naam>/apply", methods=["GET", "POST"])
    def aanbod_apply(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _beschikbare_kamer_of_404(sheet, kamer_naam)
        if request.method == "POST":
            if not g.pand.google_drive_folder_id:
                return render_template(
                    "aanbod_apply.html", kamer=kamer,
                    fout="Sorry, applications are temporarily unavailable for this property. Please contact us directly.",
                ), 503
            bestand = request.files.get("study_proof")
            try:
                aanmelding = valideer_en_bouw(request.form, heeft_bestand=bool(bestand and bestand.filename))
            except AanmeldingFout as exc:
                return render_template("aanbod_apply.html", kamer=kamer, fout=str(exc)), 400
            drive = DriveClient(config, g.pand)
            aanmeldingen_map = drive.vind_of_maak_map("Aanmeldingen")
            kamer_map = drive.vind_of_maak_map(kamer_naam, aanmeldingen_map)
            bestandsnaam = f"{date.today():%Y-%m-%d} - {aanmelding.naam} - bewijs inschrijving - {bestand.filename}"
            file_id = drive.upload_bestand(bestandsnaam, bestand.mimetype, bestand.read(), folder_id=kamer_map)
            aanmelding = dataclasses.replace(
                aanmelding, bewijs_inschrijving_link=f"https://drive.google.com/file/d/{file_id}/view"
            )
            sheet.add_aanmelding(kamer_naam, aanmelding)
            return redirect(url_for("aanbod_apply_bedankt", pand_slug=pand_slug, kamer_naam=kamer_naam))
        return render_template("aanbod_apply.html", kamer=kamer, fout=None)

    @app.route("/aanbod/<pand_slug>/<kamer_naam>/apply/thanks")
    def aanbod_apply_bedankt(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _beschikbare_kamer_of_404(sheet, kamer_naam)
        return render_template("aanbod_bedankt.html", kamer=kamer)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
