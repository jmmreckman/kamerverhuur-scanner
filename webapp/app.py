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
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, flash, g, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.middleware.proxy_fix import ProxyFix

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.drive_client import DriveClient
from kamerverhuur_scanner.lokale_media import LokaleMediaClient
from kamerverhuur_scanner.mailer import MailError, verstuur_email
from kamerverhuur_scanner.models import Tenant
from kamerverhuur_scanner.properties import PropertiesError, find_pand, load_properties, verwijder_pand, zet_pand
from kamerverhuur_scanner.runner import backfill_geschiedenis, run_check
from kamerverhuur_scanner.sheet_client import SheetClient
from kamerverhuur_scanner.utils import format_bedrag_nl, parse_bedrag

from . import ads, contracts, ondertekenen
from .aanmeldingen import AanmeldingFout, valideer_en_bouw
from .aanzegging import bereken_aanzeg_status
from .auth import User, load_users, save_users, user_uit_gegevens, verify_login, zet_gebruiker
from .reliability import bereken_betrouwbaarheid, voeg_actuele_maand_toe
from .reminders import bouw_herinnering, bouw_ingebrekestelling

load_dotenv()


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)
    # Achter Caddy (reverse proxy) staat request.remote_addr anders op het
    # interne Docker-IP van Caddy i.p.v. het echte bezoekers-IP - cruciaal
    # voor de audit-trail bij het elektronisch ondertekenen van contracten
    # (zie webapp/ondertekenen.py). x_for=1 vertrouwt precies één hop.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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
        return f"€{format_bedrag_nl(Decimal(str(value)))}"

    @app.template_filter("status_klasse")
    def status_klasse(status_tekst: str) -> str:
        return "status-" + status_tekst.lower().replace(" ", "-")

    _MAAND_NAMEN = [
        "januari", "februari", "maart", "april", "mei", "juni",
        "juli", "augustus", "september", "oktober", "november", "december",
    ]

    @app.template_filter("maandnaam")
    def maandnaam(waarde: str) -> str:
        try:
            jaar, maand = waarde.split("-")
            return f"{_MAAND_NAMEN[int(maand) - 1]} {jaar}"
        except (ValueError, IndexError):
            return waarde

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

    # Endpoints met alléén pand_slug als dynamisch urldeel worden 1-op-1
    # hergebruikt bij het wisselen van pand (zie _pand_wissel_url()). Voor
    # detailpagina's (kamer/contract/document/etc., die een extra urldeel
    # hebben dat niet vanzelfsprekend ook bestaat bij het andere pand) valt
    # dit terug op de overzichtspagina van diezelfde sectie, aan de hand van
    # het eerste urldeel na "/pand/<pand_slug>/".
    _PAND_SECTIE_OVERZICHT = {
        "": "dashboard", "dashboard": "dashboard", "huuropzegging": "huuropzegging",
        "kamers": "kamers_overzicht", "huurders": "huurders", "betalingen": "betalingen",
        "contracten": "contracten_overzicht", "documenten": "documenten",
        "aanmeldingen": "aanmeldingen_overzicht",
    }

    def _pand_sectie_overzicht_endpoint() -> str:
        pand = getattr(g, "pand", None)
        if pand is None:
            return "dashboard"
        prefix = f"/pand/{pand.slug}/"
        if not request.path.startswith(prefix):
            return "dashboard"
        sectie = request.path[len(prefix):].split("/", 1)[0]
        return _PAND_SECTIE_OVERZICHT.get(sectie, "dashboard")

    def _pand_wissel_url(doelpand_slug: str) -> str:
        """URL voor het wisselen van pand via de dropdown in de navigatie -
        blijft zoveel mogelijk op dezelfde (soort) pagina staan i.p.v. altijd
        terug te vallen op het dashboard van het andere pand."""
        if request.endpoint == "pand_bewerken":
            return url_for("pand_bewerken", slug=doelpand_slug)
        if request.endpoint and request.view_args and set(request.view_args) == {"pand_slug"}:
            return url_for(request.endpoint, pand_slug=doelpand_slug)
        return url_for(_pand_sectie_overzicht_endpoint(), pand_slug=doelpand_slug)

    @app.context_processor
    def _template_context():
        eigen_panden = []
        alle_panden = []
        if current_user.is_authenticated:
            alle_panden = _properties()
            eigen_panden = [p for p in alle_panden if current_user.heeft_toegang(p.slug)]
        return {
            "eigen_panden": eigen_panden, "alle_panden": alle_panden, "huidig_pand": getattr(g, "pand", None),
            "pand_wissel_url": _pand_wissel_url,
        }

    def _kamer_of_404(sheet: SheetClient, kamer_naam: str) -> Tenant:
        for kamer in sheet.get_kamers():
            if kamer.kamer == kamer_naam:
                return kamer
        abort(404, f"Kamer '{kamer_naam}' niet gevonden.")

    def _aanbod_media(pand=None) -> LokaleMediaClient:
        return LokaleMediaClient(config, pand or g.pand, "aanbod")

    def _aanmeldingen_media(pand=None) -> LokaleMediaClient:
        return LokaleMediaClient(config, pand or g.pand, "aanmeldingen")

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
        verhuurders = []
        for regel in form.get("verhuurders", "").splitlines():
            regel = regel.strip()
            if not regel:
                continue
            if "|" in regel:
                naam, adres = regel.split("|", 1)
            elif "," in regel:
                # bv. "Jurian Reckman, Batavierenplantsoen 33 2025CJ Haarlem" -
                # naam en adres los van elkaar op de eerste komma splitsen.
                naam, adres = regel.split(",", 1)
            else:
                naam, adres = regel, ""
            verhuurders.append({"naam": naam.strip(), "adres": adres.strip()})
        return {
            "naam": form.get("naam", "").strip(),
            "google_sheet_id": form.get("google_sheet_id", "").strip(),
            "google_sheet_worksheet": form.get("google_sheet_worksheet", "").strip() or "Huurders",
            "history_worksheet": form.get("history_worksheet", "").strip() or "Historie",
            "aanmeldingen_worksheet": form.get("aanmeldingen_worksheet", "").strip() or "Aanmeldingen",
            "vertrokken_worksheet": form.get("vertrokken_worksheet", "").strip() or "Vertrokken",
            "google_drive_folder_id": form.get("google_drive_folder_id", "").strip() or None,
            "bunq_rekening_iban": form.get("bunq_rekening_iban", "").strip().replace(" ", "").upper(),
            "extra_bcc": [e.strip() for e in form.get("extra_bcc", "").split(",") if e.strip()],
            "postcode": form.get("postcode", "").strip(),
            "plaats": form.get("plaats", "").strip(),
            "verhuurders": verhuurders,
            "rekeninghouder_naam": form.get("rekeninghouder_naam", "").strip(),
            "gedeelde_ruimtes": form.get("gedeelde_ruimtes", "").strip(),
            "bijzondere_bepalingen": form.get("bijzondere_bepalingen", "").strip(),
            "gemeente_meldpunt": form.get("gemeente_meldpunt", "").strip(),
            "heeft_bold_slot": form.get("heeft_bold_slot") == "on",
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

    # --- Contractsjabloon (basistekst/artikelen, geldt voor alle panden) ---

    @app.route("/beheer/contractsjabloon", methods=["GET", "POST"])
    @login_required
    @admin_required
    def contractsjabloon_bewerken():
        if request.method == "POST":
            inhoud = request.form.get("sjabloon", "")
            try:
                contracts.schrijf_artikelen(config.state_dir, inhoud)
            except contracts.SjabloonFout as exc:
                flash(str(exc))
                return render_template(
                    "contractsjabloon.html", sjabloon=inhoud,
                    variabelen=contracts.SJABLOON_VARIABELEN,
                    aangepast=contracts.heeft_aangepast_sjabloon(config.state_dir),
                )
            flash("Contractsjabloon opgeslagen - geldt voor alle nieuw te genereren contracten.")
            return redirect(url_for("contractsjabloon_bewerken"))
        return render_template(
            "contractsjabloon.html", sjabloon=contracts.lees_artikelen(config.state_dir),
            variabelen=contracts.SJABLOON_VARIABELEN,
            aangepast=contracts.heeft_aangepast_sjabloon(config.state_dir),
        )

    @app.route("/beheer/contractsjabloon/terugzetten", methods=["POST"])
    @login_required
    @admin_required
    def contractsjabloon_terugzetten():
        contracts.verwijder_sjabloon_override(config.state_dir)
        flash("Contractsjabloon teruggezet naar de standaardtekst.")
        return redirect(url_for("contractsjabloon_bewerken"))

    # --- Dashboard ---

    _AANZEG_TEGEL_DAGEN = 60  # ~2 maanden, voor de "loopt binnenkort af"-tegel

    @app.route("/pand/<pand_slug>/")
    @login_required
    def dashboard(pand_slug: str):
        cache = state.load(pand_slug, config.state_dir)
        totalen = None
        if cache:
            totalen = {
                "verwacht": sum(Decimal(r["verwacht_bedrag"]) for r in cache["resultaten"]),
                "ontvangen": sum(Decimal(r["ontvangen_bedrag"]) for r in cache["resultaten"]),
            }
        sheet = SheetClient(config, g.pand)
        kamer_statussen = [
            (kamer, bereken_aanzeg_status(kamer.contract_einddatum))
            for kamer in sheet.get_kamers()
            if kamer.naam
        ]
        kamer_statussen = [(kamer, status) for kamer, status in kamer_statussen if status]

        # De tegel "kamer komt leeg" is puur informatief (er loopt een contract
        # af, ongeacht of de wettelijke aanzegging al gedaan is) en blijft dus
        # staan totdat de kamer daadwerkelijk weer een (nieuw) contract heeft -
        # wegklikken van de aanzeg-waarschuwing hieronder mag deze niet
        # verbergen, want aangezegd hebben betekent niet dat er al een nieuwe
        # huurder gevonden is.
        aflopende_contracten = sorted(
            (
                (kamer, status)
                for kamer, status in kamer_statussen
                if 0 <= status.dagen_tot_einddatum <= _AANZEG_TEGEL_DAGEN
            ),
            key=lambda ks: ks[1].dagen_tot_einddatum,
        )

        niet_afgehandeld = [
            (kamer, status)
            for kamer, status in kamer_statussen
            if not state.aanzegging_is_afgehandeld(pand_slug, kamer.kamer, status.einddatum.isoformat(), config.state_dir)
        ]
        aanzeg_waarschuwingen = [
            (kamer, status) for kamer, status in niet_afgehandeld if status.moet_nu_aanzeggen or status.venster_verstreken
        ]
        return render_template(
            "dashboard.html", cache=cache, totalen=totalen,
            aanzeg_waarschuwingen=aanzeg_waarschuwingen, aflopende_contracten=aflopende_contracten,
        )

    @app.route("/pand/<pand_slug>/dashboard/aanzegging-afhandelen", methods=["POST"])
    @login_required
    def aanzegging_afhandelen(pand_slug: str):
        kamer = request.form.get("kamer", "").strip()
        einddatum = request.form.get("einddatum", "").strip()
        if kamer and einddatum:
            state.markeer_aanzegging_afgehandeld(pand_slug, kamer, einddatum, config.state_dir)
            flash(f"Aanzegging voor kamer {kamer} gemarkeerd als afgehandeld.")
        return redirect(url_for("dashboard", pand_slug=pand_slug))

    def _kamer_snapshot_velden(kamer: Tenant) -> dict:
        """Alle bewerkbare velden van een kamer als kwargs voor
        sheet.update_kamer(), zodat een gerichte wijziging (bv. alleen de
        einddatum) niet per ongeluk de rest van de rij leegmaakt."""
        return {
            "naam": kamer.naam, "kamer": kamer.kamer, "verwacht_bedrag": kamer.verwacht_bedrag,
            "iban": kamer.iban, "zoekwoord": kamer.zoekwoord, "kale_huurprijs": kamer.kale_huurprijs,
            "servicekosten": kamer.servicekosten, "contract_einddatum": kamer.contract_einddatum,
            "opmerking": kamer.opmerking, "email": kamer.email, "telefoonnummer": kamer.telefoonnummer,
            "geboortedatum": kamer.geboortedatum, "geboorteplaats": kamer.geboorteplaats,
            "studentnummer": kamer.studentnummer, "studierichting": kamer.studierichting,
            "borgsteller_naam": kamer.borgsteller_naam, "borgsteller_relatie": kamer.borgsteller_relatie,
            "contract_startdatum": kamer.contract_startdatum, "borg_bedrag": kamer.borg_bedrag,
        }

    @app.route("/pand/<pand_slug>/huuropzegging", methods=["GET", "POST"])
    @login_required
    def huuropzegging_doorgeven(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        tenants = sheet.get_tenants()
        if request.method == "POST":
            kamer_naam = request.form.get("kamer", "").strip()
            einddatum = request.form.get("einddatum", "").strip()
            kamer = next((k for k in tenants if k.kamer == kamer_naam), None)
            if not kamer or not einddatum:
                flash("Kies een huurder en een einddatum.")
            else:
                einddatum_nl = contracts._datum_lang(einddatum)
                velden = _kamer_snapshot_velden(kamer)
                velden["contract_einddatum"] = einddatum_nl
                sheet.update_kamer(row_index=kamer.row_index, **velden)
                flash(f"Huuropzegging verwerkt: kamer {kamer.kamer} ({kamer.naam}) loopt af op {einddatum_nl}.")
                return redirect(url_for("dashboard", pand_slug=pand_slug))
        return render_template("huuropzegging.html", tenants=tenants)

    # --- Huurders ---

    @app.route("/pand/<pand_slug>/huurders")
    @login_required
    def huurders(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        kamers = sheet.get_kamers()
        sheet_url = f"https://docs.google.com/spreadsheets/d/{g.pand.google_sheet_id}/edit"
        return render_template(
            "huurders.html", kamers=kamers, sheet_url=sheet_url,
            vertrokken_huurders=sheet.get_recent_vertrokken_huurders(),
        )

    def _kamer_form_naar_velden(form) -> dict:
        kale_huurprijs = form.get("kale_huurprijs", "").strip()
        servicekosten = form.get("servicekosten", "").strip()
        borg_bedrag = form.get("borg_bedrag", "").strip()
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
            "geboortedatum": form.get("geboortedatum", "").strip() or None,
            "geboorteplaats": form.get("geboorteplaats", "").strip() or None,
            "studentnummer": form.get("studentnummer", "").strip() or None,
            "studierichting": form.get("studierichting", "").strip() or None,
            "borgsteller_naam": form.get("borgsteller_naam", "").strip() or None,
            "borgsteller_relatie": form.get("borgsteller_relatie", "").strip() or None,
            "contract_startdatum": form.get("contract_startdatum", "").strip() or None,
            "borg_bedrag": parse_bedrag(borg_bedrag) if borg_bedrag else None,
        }

    @app.route("/pand/<pand_slug>/huurders/<kamer_naam>/bewerken", methods=["GET", "POST"])
    @login_required
    def huurder_bewerken(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _kamer_of_404(sheet, kamer_naam)
        if request.method == "POST":
            velden = _kamer_form_naar_velden(request.form)
            if kamer.naam and kamer.naam != velden["naam"]:
                # een andere (of geen) huurder komt voor deze kamer in de plaats -
                # bewaar de vertrekkende huurder nog even (zie Huurders-pagina).
                sheet.archiveer_vertrokken_huurder(kamer)
            sheet.update_kamer(row_index=kamer.row_index, **velden)
            flash(f"Kamer {kamer_naam} bijgewerkt.")
            return redirect(url_for("huurders", pand_slug=pand_slug))
        return render_template("huurder_bewerken.html", kamer=kamer)

    @app.route("/pand/<pand_slug>/huurders/mailen", methods=["GET", "POST"])
    @login_required
    def huishouden_mailen(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        tenants = sheet.get_tenants()
        tenants_met_mail = [t for t in tenants if t.email]
        tenants_zonder_mail = [t for t in tenants if not t.email]

        if request.method == "POST":
            onderwerp = request.form.get("onderwerp", "").strip()
            tekst = request.form.get("tekst", "").strip()
            if not onderwerp or not tekst:
                flash("Onderwerp en tekst zijn verplicht.")
                return render_template(
                    "huishouden_mailen.html", tenants_met_mail=tenants_met_mail,
                    tenants_zonder_mail=tenants_zonder_mail, onderwerp=onderwerp, tekst=tekst,
                )
            bcc = list(dict.fromkeys(config.email_bcc + g.pand.extra_bcc))
            verzonden, mislukt = 0, []
            for tenant in tenants_met_mail:
                try:
                    verstuur_email(config, tenant.email, onderwerp, tekst, bcc=bcc)
                    verzonden += 1
                except MailError:
                    mislukt.append(tenant.naam)
            if verzonden:
                flash(f"Mail verstuurd naar {verzonden} huurder(s).")
            if mislukt:
                flash(f"Versturen is mislukt voor: {', '.join(mislukt)}.")
            if tenants_zonder_mail:
                flash(
                    "Geen e-mailadres bekend voor: "
                    f"{', '.join(t.naam for t in tenants_zonder_mail)} - deze hebben niets ontvangen."
                )
            return redirect(url_for("huurders", pand_slug=pand_slug))

        return render_template(
            "huishouden_mailen.html", tenants_met_mail=tenants_met_mail,
            tenants_zonder_mail=tenants_zonder_mail, onderwerp="", tekst="",
        )

    # --- Betalingen ---

    @app.route("/pand/<pand_slug>/betalingen", methods=["GET", "POST"])
    @login_required
    def betalingen(pand_slug: str):
        net_gecontroleerd = None
        if request.method == "POST":
            _tenants, results, unmatched = run_check(config, g.pand, dry_run=False)
            net_gecontroleerd = {"results": results, "unmatched": unmatched}
        sheet = SheetClient(config, g.pand)
        tenants_by_kamer = {k.kamer: k for k in sheet.get_kamers()}
        huidige_maand = date.today().strftime("%Y-%m")
        verzonden = {
            (kamer, soort): state.email_verzonden_op(pand_slug, kamer, soort, huidige_maand, config.state_dir)
            for kamer in tenants_by_kamer
            for soort in _EMAIL_SOORTEN
        }
        return render_template(
            "betalingen.html",
            net_gecontroleerd=net_gecontroleerd,
            cache=state.load(pand_slug, config.state_dir),
            tenants_by_kamer=tenants_by_kamer,
            verzonden=verzonden,
        )

    @app.route("/pand/<pand_slug>/betalingen/geschiedenis-aanvullen", methods=["POST"])
    @login_required
    def geschiedenis_aanvullen(pand_slug: str):
        aantal = backfill_geschiedenis(config, g.pand)
        flash(
            f"Betaalgeschiedenis aangevuld voor in totaal {aantal} maand(en) - per kamer vanaf de "
            "bekende contract-startdatum (kolom 'Contract startdatum'), of anders de standaard "
            "12 maanden terug."
        )
        return redirect(url_for("betalingen", pand_slug=pand_slug))

    _EMAIL_SOORTEN = {
        "herinnering": (bouw_herinnering, "Betaalherinnering"),
        "ingebrekestelling": (bouw_ingebrekestelling, "Ingebrekestelling"),
    }

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>/email/<soort>", methods=["GET", "POST"])
    @login_required
    def kamer_email(pand_slug: str, kamer_naam: str, soort: str):
        if soort not in _EMAIL_SOORTEN:
            abort(404)
        bouwer, titel = _EMAIL_SOORTEN[soort]
        sheet = SheetClient(config, g.pand)
        kamer = _kamer_of_404(sheet, kamer_naam)
        if not kamer.email:
            flash(f"Kamer {kamer_naam} heeft geen e-mailadres - vul dit eerst in bij Huurders.")
            return redirect(url_for("betalingen", pand_slug=pand_slug))

        status = state.status_voor_kamer(state.load(pand_slug, config.state_dir), kamer_naam)
        ontvangen_bedrag = parse_bedrag(status["ontvangen_bedrag"]) if status else Decimal("0")

        if request.method == "POST":
            onderwerp = request.form.get("onderwerp", "").strip()
            tekst = request.form.get("tekst", "").strip()
            bcc = list(dict.fromkeys(config.email_bcc + g.pand.extra_bcc))
            try:
                verstuur_email(config, kamer.email, onderwerp, tekst, bcc=bcc)
            except MailError as exc:
                flash(str(exc))
                return render_template(
                    "kamer_email.html", kamer=kamer, soort=soort, titel=titel,
                    onderwerp=onderwerp, tekst=tekst,
                )
            huidige_maand = date.today().strftime("%Y-%m")
            state.markeer_email_verzonden(pand_slug, kamer_naam, soort, huidige_maand, config.state_dir)
            flash(f"{titel} verstuurd naar {kamer.naam} ({kamer.email}).")
            return redirect(url_for("betalingen", pand_slug=pand_slug))

        opgesteld = bouwer(g.pand, kamer, ontvangen_bedrag)
        return render_template(
            "kamer_email.html", kamer=kamer, soort=soort, titel=titel,
            onderwerp=opgesteld["onderwerp"], tekst=opgesteld["tekst"],
        )

    # --- Kamers ---

    @app.route("/pand/<pand_slug>/kamers")
    @login_required
    def kamers_overzicht(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        return render_template("kamers.html", kamers=sheet.get_kamers(), cache=state.load(pand_slug, config.state_dir))

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>")
    @login_required
    def kamer_detail(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _kamer_of_404(sheet, kamer_naam)
        cache_status = state.status_voor_kamer(state.load(pand_slug, config.state_dir), kamer_naam)
        geschiedenis = sheet.get_geschiedenis(kamer_naam)
        if kamer.naam:
            geschiedenis = voeg_actuele_maand_toe(geschiedenis, cache_status, kamer_naam, kamer.naam)
        return render_template(
            "kamer_detail.html",
            kamer=kamer,
            geschiedenis=list(reversed(geschiedenis)),
            betrouwbaarheid=bereken_betrouwbaarheid(geschiedenis),
            cache_status=cache_status,
            contracten=contracts.list_contracten_voor_kamer(pand_slug, kamer_naam, config.state_dir),
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
        media = _aanbod_media().list_bestanden(kamer_naam)
        standaard_omschrijving = kamer.advertentie_omschrijving or ads.genereer_advertentie(g.pand, kamer)["beschrijving"]
        return render_template("kamer_aanbod.html", kamer=kamer, media=media, standaard_omschrijving=standaard_omschrijving)

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>/aanbod/upload", methods=["POST"])
    @login_required
    def kamer_aanbod_upload(pand_slug: str, kamer_naam: str):
        _kamer_of_404(SheetClient(config, g.pand), kamer_naam)
        media_client = _aanbod_media()
        try:
            aantal = 0
            for bestand in request.files.getlist("bestand"):
                if bestand and bestand.filename:
                    media_client.upload_bestand(kamer_naam, bestand.filename, bestand.mimetype, bestand.read())
                    aantal += 1
            flash(f"{aantal} bestand(en) geupload." if aantal else "Geen bestand geselecteerd.")
        except Exception:
            app.logger.exception("Uploaden van aanbod-foto/video voor kamer %s is mislukt.", kamer_naam)
            flash("Uploaden is helaas mislukt (probeer het opnieuw).")
        return redirect(url_for("kamer_aanbod", pand_slug=pand_slug, kamer_naam=kamer_naam))

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>/aanbod/<file_id>/verwijderen", methods=["POST"])
    @login_required
    def kamer_aanbod_media_verwijderen(pand_slug: str, kamer_naam: str, file_id: str):
        _kamer_of_404(SheetClient(config, g.pand), kamer_naam)
        _aanbod_media().verwijder_bestand(kamer_naam, file_id)
        flash("Bestand verwijderd.")
        return redirect(url_for("kamer_aanbod", pand_slug=pand_slug, kamer_naam=kamer_naam))

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>/aanbod/<file_id>/weergeven")
    @login_required
    def kamer_aanbod_media(pand_slug: str, kamer_naam: str, file_id: str):
        """Toont een aanbod-foto/video inline (geen Content-Disposition: attachment,
        anders tonen <img>/<video>-tags op de 'Aanbod beheren'-pagina niets)."""
        _kamer_of_404(SheetClient(config, g.pand), kamer_naam)
        gevonden = _aanbod_media().lees_bestand(kamer_naam, file_id)
        if not gevonden:
            abort(404)
        _naam, mimetype, inhoud = gevonden
        return Response(inhoud, mimetype=mimetype, headers={"Cache-Control": "private, max-age=3600"})

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

    def _schrijf_contract_terug_naar_sheet(sheet: SheetClient, kamers, kamer_naam: str, velden) -> None:
        """Schrijft contractgegevens terug naar de Huurders-sheet voor deze
        kamer (archiveert eerst de vertrekkende huurder als de naam wijzigt) -
        `velden` ondersteunt .get() net als request.form (huurder_naam, email,
        kale_huurprijs, servicekosten, borg, geboortedatum, geboorteplaats,
        studentnummer, studierichting, borgsteller_naam, borgsteller_relatie,
        ingangsdatum, einddatum). Gebruikt door zowel het genereren van een
        nieuw contract als het verzoek tot tekenen (met gegevens uit de
        contractmetadata i.p.v. een live formulier), zodat een proefcontract
        dat pas bij het tekenverzoek definitief wordt alsnog kan worden
        teruggeschreven. Doet niets als de kamer niet (meer) bestaat."""
        bestaande = next((k for k in kamers if k.kamer == kamer_naam), None)
        if bestaande is None:
            return
        nieuwe_naam = velden.get("huurder_naam", "").strip()
        if bestaande.naam and bestaande.naam != nieuwe_naam:
            # een andere huurder komt voor deze kamer in de plaats - bewaar de
            # vertrekkende huurder nog even (zie Huurders-pagina).
            sheet.archiveer_vertrokken_huurder(bestaande)
        kale = velden.get("kale_huurprijs", "").strip()
        service = velden.get("servicekosten", "").strip()
        borg = velden.get("borg", "").strip()
        sheet.update_kamer(
            row_index=bestaande.row_index,
            naam=nieuwe_naam or bestaande.naam,
            kamer=kamer_naam,
            verwacht_bedrag=bestaande.verwacht_bedrag,
            iban=bestaande.iban,
            zoekwoord=bestaande.zoekwoord,
            kale_huurprijs=parse_bedrag(kale) if kale else bestaande.kale_huurprijs,
            servicekosten=parse_bedrag(service) if service else bestaande.servicekosten,
            contract_einddatum=velden.get("einddatum", "").strip() or bestaande.contract_einddatum,
            opmerking=bestaande.opmerking,
            email=velden.get("email", "").strip() or bestaande.email,
            telefoonnummer=bestaande.telefoonnummer,
            geboortedatum=velden.get("geboortedatum", "").strip() or bestaande.geboortedatum,
            geboorteplaats=velden.get("geboorteplaats", "").strip() or bestaande.geboorteplaats,
            studentnummer=velden.get("studentnummer", "").strip() or bestaande.studentnummer,
            studierichting=velden.get("studierichting", "").strip() or bestaande.studierichting,
            borgsteller_naam=velden.get("borgsteller_naam", "").strip() or bestaande.borgsteller_naam,
            borgsteller_relatie=velden.get("borgsteller_relatie", "").strip() or bestaande.borgsteller_relatie,
            contract_startdatum=velden.get("ingangsdatum", "").strip() or bestaande.contract_startdatum,
            borg_bedrag=parse_bedrag(borg) if borg else bestaande.borg_bedrag,
        )

    @app.route("/pand/<pand_slug>/contracten")
    @login_required
    def contracten_overzicht(pand_slug: str):
        contracten = []
        for bestandsnaam in contracts.list_contracten(pand_slug, config.state_dir):
            ronde = ondertekenen.lees_ondertekenronde(pand_slug, bestandsnaam, config.state_dir)
            contracten.append({
                "bestandsnaam": bestandsnaam,
                "getekend": contracts.is_getekend_contract(bestandsnaam),
                # alleen tonen als het ondertekenverzoek ook echt verstuurd is
                # (niet bij een geopend maar niet bevestigd voorbeeldscherm)
                "ronde": ronde if ronde and ronde.get("verzonden_op") else None,
            })
        return render_template("contracten.html", contracten=contracten)

    @app.route("/pand/<pand_slug>/contracten/nieuw", methods=["GET", "POST"])
    @login_required
    def contract_nieuw(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        kamers = sheet.get_kamers()
        if request.method == "POST":
            bestandsnaam = contracts.genereer_contract(pand_slug, g.pand, request.form, config.state_dir)
            # Gegevens ook terugschrijven naar de Huurders-sheet, zodat ze bij een
            # volgend contract (of op de Huurders-pagina) meteen weer klaarstaan -
            # optioneel, sommige contracten zijn een proefversie waarvoor dat nog
            # niet gewenst is (zie het vinkje op het formulier).
            kamer_naam = request.form.get("kamer", "").strip()
            if request.form.get("schrijf_terug_naar_sheet") == "on":
                _schrijf_contract_terug_naar_sheet(sheet, kamers, kamer_naam, request.form)
            return redirect(url_for("contract_mailen", pand_slug=pand_slug, bestandsnaam=bestandsnaam))
        aantal_bewoners = len([k for k in kamers if k.naam]) or len(kamers) or 1
        return render_template(
            "contract_nieuw.html", kamers=kamers, vandaag=date.today(), aantal_bewoners=aantal_bewoners
        )

    @app.route("/pand/<pand_slug>/contracten/<bestandsnaam>")
    @login_required
    def contract_bekijken(pand_slug: str, bestandsnaam: str):
        try:
            html = contracts.lees_contract(pand_slug, bestandsnaam, config.state_dir)
        except FileNotFoundError:
            abort(404)
        return Response(html, mimetype="text/html")

    @app.route("/pand/<pand_slug>/contracten/<bestandsnaam>/pdf")
    @login_required
    def contract_pdf(pand_slug: str, bestandsnaam: str):
        try:
            pdf = contracts.genereer_pdf(pand_slug, bestandsnaam, config.state_dir)
        except FileNotFoundError:
            abort(404)
        except contracts.PdfGenerationError:
            flash("PDF-generatie is mislukt voor dit contract.")
            return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))
        pdf_bestandsnaam = Path(bestandsnaam).with_suffix(".pdf").name
        return Response(
            pdf, mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{pdf_bestandsnaam}"'},
        )

    @app.route("/pand/<pand_slug>/contracten/<bestandsnaam>/mailen", methods=["GET", "POST"])
    @login_required
    def contract_mailen(pand_slug: str, bestandsnaam: str):
        try:
            contracts.lees_contract(pand_slug, bestandsnaam, config.state_dir)
        except FileNotFoundError:
            abort(404)
        metadata = contracts.lees_metadata(pand_slug, bestandsnaam, config.state_dir)
        bcc_adressen = list(dict.fromkeys(config.email_bcc + g.pand.extra_bcc))

        if request.method == "POST":
            aan = request.form.get("aan", "").strip()
            onderwerp = request.form.get("onderwerp", "").strip()
            tekst = request.form.get("tekst", "").strip()
            if not aan:
                flash("Vul een e-mailadres van de huurder in.")
                return render_template(
                    "contract_mailen.html", bestandsnaam=bestandsnaam,
                    aan=aan, onderwerp=onderwerp, tekst=tekst, bcc_adressen=bcc_adressen,
                )
            try:
                pdf = contracts.genereer_pdf(pand_slug, bestandsnaam, config.state_dir)
            except contracts.PdfGenerationError:
                flash("PDF-generatie is mislukt - het contract is niet gemaild.")
                return render_template(
                    "contract_mailen.html", bestandsnaam=bestandsnaam,
                    aan=aan, onderwerp=onderwerp, tekst=tekst, bcc_adressen=bcc_adressen,
                )
            pdf_bestandsnaam = Path(bestandsnaam).with_suffix(".pdf").name
            try:
                verstuur_email(
                    config, aan, onderwerp, tekst, bcc=bcc_adressen,
                    bijlagen=[(pdf_bestandsnaam, "application/pdf", pdf)],
                )
            except MailError as exc:
                flash(str(exc))
                return render_template(
                    "contract_mailen.html", bestandsnaam=bestandsnaam,
                    aan=aan, onderwerp=onderwerp, tekst=tekst, bcc_adressen=bcc_adressen,
                )
            flash(f"Concept-huurcontract gemaild naar {aan}.")
            return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))

        opgesteld = contracts.bouw_concept_email(g.pand, metadata)
        return render_template(
            "contract_mailen.html", bestandsnaam=bestandsnaam,
            aan=metadata.get("email", ""), onderwerp=opgesteld["onderwerp"], tekst=opgesteld["tekst"],
            bcc_adressen=bcc_adressen,
        )

    @app.route("/pand/<pand_slug>/contracten/<bestandsnaam>/verwijderen", methods=["POST"])
    @login_required
    def contract_verwijderen(pand_slug: str, bestandsnaam: str):
        contracts.verwijder_contract(pand_slug, bestandsnaam, config.state_dir)
        flash(f"Contract '{bestandsnaam}' verwijderd.")
        return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))

    # --- Elektronisch ondertekenen ---

    def _teken_url(token: str) -> str:
        return url_for("tekenen", token=token, _external=True)

    def _bouw_huurder_tekenmail(metadata: dict, teken_url: str) -> dict[str, str]:
        huurprijs = parse_bedrag(metadata.get("huurprijs"))
        borg = parse_bedrag(metadata.get("borg"))
        try:
            ingangsdatum = date.fromisoformat(metadata.get("ingangsdatum_iso") or "")
        except ValueError:
            ingangsdatum = date.today()
        betaalverzoek = ondertekenen.bereken_betaalverzoek(huurprijs, borg, ingangsdatum)
        return ondertekenen.bouw_betaal_en_tekenmail(g.pand, metadata, teken_url, betaalverzoek)

    def _verstuur_tekenverzoek_mails(ronde: dict, metadata: dict, huurder_override: dict | None = None) -> list[str]:
        """Mailt (opnieuw) elke nog niet getekende ondertekenaar in `ronde` -
        de huurder krijgt het betaalverzoek + tekenlink (desgewenst met een
        aangepaste onderwerp/tekst uit het voorbeeldscherm), de rest alleen
        de tekenlink. Geeft de e-mailadressen terug waarvoor het versturen
        mislukte (best-effort, net als bij 'mail het hele huishouden')."""
        mislukt = []
        for o in ronde["ondertekenaars"]:
            if not o["email"] or o["ondertekend_op"]:
                continue
            teken_url = _teken_url(o["token"])
            if o["rol"] == "huurder":
                mail = huurder_override or _bouw_huurder_tekenmail(metadata, teken_url)
            else:
                mail = ondertekenen.bouw_tekenmail_overig(o["rol"], o["naam"], g.pand, metadata, teken_url)
            try:
                verstuur_email(config, o["email"], mail["onderwerp"], mail["tekst"])
            except MailError:
                app.logger.exception("Ondertekenverzoek-mail naar %s is mislukt.", o["email"])
                mislukt.append(o["email"])
        return mislukt

    def _rond_ondertekening_af(pand_slug: str, bestandsnaam: str, pand) -> None:
        """Wordt aangeroepen zodra de laatste partij getekend heeft: maakt de
        definitieve, ondertekende contractversie en mailt die (als PDF) naar
        iedereen die getekend heeft."""
        ronde = ondertekenen.lees_ondertekenronde(pand_slug, bestandsnaam, config.state_dir)
        handtekeningen_html = ondertekenen.bouw_handtekeningen_html(ronde)
        getekend_bestandsnaam = contracts.genereer_getekend_contract(
            pand_slug, bestandsnaam, handtekeningen_html, config.state_dir
        )
        ondertekenen.markeer_afgerond(pand_slug, bestandsnaam, config.state_dir, getekend_bestandsnaam)
        metadata = contracts.lees_metadata(pand_slug, bestandsnaam, config.state_dir)
        try:
            pdf = contracts.genereer_pdf(pand_slug, getekend_bestandsnaam, config.state_dir)
        except contracts.PdfGenerationError:
            app.logger.exception("PDF-generatie van het ondertekende contract %s is mislukt.", getekend_bestandsnaam)
            return
        mail = ondertekenen.bouw_getekend_contract_mail(pand, metadata)
        pdf_bestandsnaam = Path(getekend_bestandsnaam).with_suffix(".pdf").name
        for adres in dict.fromkeys(o["email"] for o in ronde["ondertekenaars"] if o["email"]):
            try:
                verstuur_email(
                    config, adres, mail["onderwerp"], mail["tekst"],
                    bijlagen=[(pdf_bestandsnaam, "application/pdf", pdf)],
                )
            except MailError:
                app.logger.exception("Mail met ondertekend contract naar %s is mislukt.", adres)

    @app.route("/pand/<pand_slug>/contracten/<bestandsnaam>/tekenverzoek", methods=["GET", "POST"])
    @login_required
    def contract_tekenverzoek(pand_slug: str, bestandsnaam: str):
        if contracts.is_getekend_contract(bestandsnaam):
            flash("Dit is al een ondertekend contract.")
            return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))
        try:
            contracts.lees_contract(pand_slug, bestandsnaam, config.state_dir)
        except FileNotFoundError:
            abort(404)
        bestaande_ronde = ondertekenen.lees_ondertekenronde(pand_slug, bestandsnaam, config.state_dir)
        if bestaande_ronde is not None and bestaande_ronde.get("verzonden_op"):
            flash("Er loopt al een ondertekenverzoek voor dit contract.")
            return redirect(url_for("contract_ondertekenstatus", pand_slug=pand_slug, bestandsnaam=bestandsnaam))
        metadata = contracts.lees_metadata(pand_slug, bestandsnaam, config.state_dir)
        if not metadata.get("email"):
            flash("Geen e-mailadres van de huurder bekend voor dit contract - kan geen ondertekenverzoek versturen.")
            return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))

        # De ronde (en dus de echte, unieke tekenlinks) wordt al hier
        # aangemaakt zodat het voorbeeldscherm de kloppende link kan tonen -
        # er wordt pas gemaild na bevestiging hieronder (zie verzonden_op).
        verhuurder_emails = list(dict.fromkeys(config.email_bcc + g.pand.extra_bcc))
        ronde = ondertekenen.start_ondertekenronde(
            g.pand, pand_slug, bestandsnaam, metadata, verhuurder_emails, config.state_dir
        )
        huurder = next(o for o in ronde["ondertekenaars"] if o["rol"] == "huurder")

        if request.method == "POST":
            if request.form.get("schrijf_terug_naar_sheet") == "on":
                sheet = SheetClient(config, g.pand)
                _schrijf_contract_terug_naar_sheet(sheet, sheet.get_kamers(), metadata.get("kamer", ""), metadata)
            onderwerp = request.form.get("onderwerp", "").strip()
            tekst = request.form.get("tekst", "").strip()
            huurder_override = {"onderwerp": onderwerp, "tekst": tekst} if onderwerp and tekst else None
            mislukt = _verstuur_tekenverzoek_mails(ronde, metadata, huurder_override)
            ondertekenen.markeer_verzonden(pand_slug, bestandsnaam, config.state_dir)
            if mislukt:
                flash(f"Ondertekenverzoek verstuurd, maar mislukt voor: {', '.join(mislukt)}.")
            else:
                flash("Ondertekenverzoek verstuurd naar alle partijen.")
            return redirect(url_for("contract_ondertekenstatus", pand_slug=pand_slug, bestandsnaam=bestandsnaam))

        mail = _bouw_huurder_tekenmail(metadata, _teken_url(huurder["token"]))
        overige_ontvangers = [o for o in ronde["ondertekenaars"] if o["rol"] != "huurder"]
        return render_template(
            "contract_tekenverzoek.html", bestandsnaam=bestandsnaam,
            onderwerp=mail["onderwerp"], tekst=mail["tekst"], overige_ontvangers=overige_ontvangers,
        )

    @app.route("/pand/<pand_slug>/contracten/<bestandsnaam>/ondertekenstatus")
    @login_required
    def contract_ondertekenstatus(pand_slug: str, bestandsnaam: str):
        ronde = ondertekenen.lees_ondertekenronde(pand_slug, bestandsnaam, config.state_dir)
        if ronde is None:
            abort(404)
        return render_template("contract_ondertekenstatus.html", bestandsnaam=bestandsnaam, ronde=ronde)

    @app.route(
        "/pand/<pand_slug>/contracten/<bestandsnaam>/ondertekenstatus/<ondertekenaar_id>/opnieuw-mailen",
        methods=["POST"],
    )
    @login_required
    def contract_tekenverzoek_opnieuw(pand_slug: str, bestandsnaam: str, ondertekenaar_id: str):
        ronde = ondertekenen.lees_ondertekenronde(pand_slug, bestandsnaam, config.state_dir)
        if ronde is None:
            abort(404)
        doelwit = next((o for o in ronde["ondertekenaars"] if o["id"] == ondertekenaar_id), None)
        if doelwit is None:
            abort(404)
        if doelwit["ondertekend_op"]:
            flash(f"{doelwit['naam']} had al getekend.")
        else:
            metadata = contracts.lees_metadata(pand_slug, bestandsnaam, config.state_dir)
            mislukt = _verstuur_tekenverzoek_mails({"ondertekenaars": [doelwit]}, metadata)
            flash(f"Mail naar {doelwit['naam']} is mislukt." if mislukt else f"Opnieuw gemaild naar {doelwit['naam']}.")
        return redirect(url_for("contract_ondertekenstatus", pand_slug=pand_slug, bestandsnaam=bestandsnaam))

    @app.route("/tekenen/<token>", methods=["GET", "POST"])
    def tekenen(token: str):
        gevonden = ondertekenen.zoek_via_token(token, config.state_dir)
        if gevonden is None:
            abort(404)
        pand_slug, bestandsnaam, ondertekenaar = gevonden
        pand = find_pand(_properties(), pand_slug)
        if pand is None:
            abort(404)

        if ondertekenaar["ondertekend_op"]:
            return render_template("tekenen_getekend.html", ondertekenaar=ondertekenaar)

        if request.method == "POST":
            getekende_naam = request.form.get("getekende_naam", "").strip()
            akkoord = request.form.get("akkoord") == "on"
            handtekening = ondertekenen.handtekening_base64_uit_data_url(
                request.form.get("handtekening_data_url", "")
            )
            if not getekende_naam or not akkoord or not handtekening:
                flash("Please fill in your full name, draw your signature, and tick the checkbox to sign.")
                return render_template("tekenen.html", pand=pand, bestandsnaam=bestandsnaam, ondertekenaar=ondertekenaar)
            ronde = ondertekenen.markeer_ondertekend(
                pand_slug, bestandsnaam, ondertekenaar["id"], config.state_dir,
                request.remote_addr or "", request.user_agent.string or "", getekende_naam, handtekening,
            )
            if ondertekenen.alles_getekend(ronde):
                _rond_ondertekening_af(pand_slug, bestandsnaam, pand)
            bijgewerkt = next(o for o in ronde["ondertekenaars"] if o["id"] == ondertekenaar["id"])
            return render_template("tekenen_getekend.html", ondertekenaar=bijgewerkt)

        return render_template("tekenen.html", pand=pand, bestandsnaam=bestandsnaam, ondertekenaar=ondertekenaar)

    @app.route("/tekenen/<token>/contract")
    def tekenen_contract(token: str):
        """De volledige contracttekst, om in een iframe te tonen op de
        ondertekenpagina - publiek (geen login), maar alleen bereikbaar met
        een geldige, niet te raden token."""
        gevonden = ondertekenen.zoek_via_token(token, config.state_dir)
        if gevonden is None:
            abort(404)
        pand_slug, bestandsnaam, _ondertekenaar = gevonden
        try:
            html_inhoud = contracts.lees_contract(pand_slug, bestandsnaam, config.state_dir)
        except FileNotFoundError:
            abort(404)
        return Response(html_inhoud, mimetype="text/html")

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
        try:
            aantal = 0
            for bestand in request.files.getlist("bestand"):
                if bestand and bestand.filename:
                    drive.upload_bestand(bestand.filename, bestand.mimetype, bestand.read(), folder_id=folder_id)
                    aantal += 1
            flash(f"{aantal} bestand(en) geupload." if aantal else "Geen bestand geselecteerd.")
        except Exception:
            app.logger.exception("Uploaden van een document is mislukt (pand %s).", pand_slug)
            flash("Uploaden is helaas mislukt (probeer het opnieuw, of met een kleiner bestand).")
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

    def _eerste_foto(media_client: LokaleMediaClient, kamer_naam: str):
        return next((b for b in media_client.list_bestanden(kamer_naam) if b.mimetype.startswith("image/")), None)

    @app.route("/aanbod")
    def aanbod_overzicht():
        kaarten = []
        for pand in _properties():
            sheet = SheetClient(config, pand)
            media_client = _aanbod_media(pand)
            for kamer in sheet.get_kamers():
                if not kamer.beschikbaar:
                    continue
                foto = _eerste_foto(media_client, kamer.kamer)
                kaarten.append({"pand": pand, "kamer": kamer, "foto": foto})
        return render_template("aanbod_overzicht.html", kaarten=kaarten)

    @app.route("/aanbod/<pand_slug>/<kamer_naam>")
    def aanbod_detail(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _beschikbare_kamer_of_404(sheet, kamer_naam)
        media = _aanbod_media().list_bestanden(kamer_naam)
        omschrijving = kamer.advertentie_omschrijving or ads.genereer_advertentie(g.pand, kamer)["beschrijving"]
        return render_template("aanbod_detail.html", kamer=kamer, media=media, omschrijving=omschrijving)

    @app.route("/aanbod/<pand_slug>/<kamer_naam>/media/<file_id>")
    def aanbod_media(pand_slug: str, kamer_naam: str, file_id: str):
        sheet = SheetClient(config, g.pand)
        _beschikbare_kamer_of_404(sheet, kamer_naam)
        gevonden = _aanbod_media().lees_bestand(kamer_naam, file_id)
        if not gevonden:
            abort(404)
        _naam, mimetype, inhoud = gevonden
        return Response(inhoud, mimetype=mimetype, headers={"Cache-Control": "public, max-age=3600"})

    @app.route("/aanbod/<pand_slug>/<kamer_naam>/apply", methods=["GET", "POST"])
    def aanbod_apply(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _beschikbare_kamer_of_404(sheet, kamer_naam)
        if request.method == "POST":
            bestand = request.files.get("study_proof")
            try:
                aanmelding = valideer_en_bouw(request.form, heeft_bestand=bool(bestand and bestand.filename))
            except AanmeldingFout as exc:
                return render_template("aanbod_apply.html", kamer=kamer, fout=str(exc)), 400
            media_client = _aanmeldingen_media()
            try:
                bestandsnaam = f"{date.today():%Y-%m-%d} - {aanmelding.naam} - bewijs inschrijving - {bestand.filename}"
                file_id = media_client.upload_bestand(kamer_naam, bestandsnaam, bestand.mimetype, bestand.read())
            except Exception:
                app.logger.exception("Uploaden van bewijs inschrijving is mislukt (pand %s, kamer %s).", pand_slug, kamer_naam)
                return render_template(
                    "aanbod_apply.html", kamer=kamer,
                    fout="Sorry, uploading your file failed. Please try again with a smaller file, or contact us directly.",
                ), 500
            aanmelding = dataclasses.replace(
                aanmelding,
                bewijs_inschrijving_link=url_for(
                    "aanmelding_bewijs_bekijken", pand_slug=pand_slug, kamer_naam=kamer_naam, file_id=file_id
                ),
            )
            sheet.add_aanmelding(kamer_naam, aanmelding)
            return redirect(url_for("aanbod_apply_bedankt", pand_slug=pand_slug, kamer_naam=kamer_naam))
        return render_template("aanbod_apply.html", kamer=kamer, fout=None)

    @app.route("/pand/<pand_slug>/aanmeldingen/bewijs/<kamer_naam>/<file_id>")
    @login_required
    def aanmelding_bewijs_bekijken(pand_slug: str, kamer_naam: str, file_id: str):
        """Bewijs van inschrijving bij een aanmelding - alleen voor
        ingelogde beheerders van dit pand, geen publieke link (bevat
        persoonsgegevens)."""
        gevonden = _aanmeldingen_media().lees_bestand(kamer_naam, file_id)
        if not gevonden:
            abort(404)
        naam, mimetype, inhoud = gevonden
        return Response(inhoud, mimetype=mimetype, headers={"Content-Disposition": f'inline; filename="{naam}"'})

    @app.route("/aanbod/<pand_slug>/<kamer_naam>/apply/thanks")
    def aanbod_apply_bedankt(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _beschikbare_kamer_of_404(sheet, kamer_naam)
        return render_template("aanbod_bedankt.html", kamer=kamer)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
