"""Flask-website voor meerdere panden: dashboard, kamers, betalingen-check,
contracten en documenten, per pand. Login is beperkt tot de gebruikers in
users.json, elk met eigen pand-toegang (zie webapp/auth.py).

Starten (development): python -m webapp.app
Starten (productie): zie README (gunicorn + webapp.app:create_app()).
"""
from __future__ import annotations

import dataclasses
import logging
import mimetypes
import re
import threading
from datetime import date, time
from decimal import Decimal
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, flash, g, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.datastructures import ImmutableMultiDict
from werkzeug.middleware.proxy_fix import ProxyFix

from kamerverhuur_scanner import document_ai, drive_browse, drive_sync, mail_voorkeuren, state, winst
from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.lokale_media import LokaleMediaClient
from kamerverhuur_scanner.mailer import MailError, verstuur_email
from kamerverhuur_scanner.models import Status, Tenant
from kamerverhuur_scanner.properties import PropertiesError, find_pand, load_properties, verwijder_pand, zet_pand
from kamerverhuur_scanner.runner import (
    backfill_geschiedenis,
    bereken_winstoverzicht,
    run_check,
    verwachte_huurinkomsten_specificatie,
)
from kamerverhuur_scanner.sheet_client import SheetClient
from kamerverhuur_scanner.utils import format_bedrag_nl, parse_bedrag

from . import ads, afwijzing, bezichtiging, contracts, documentverzoek, ondertekenen
from .aanmeldingen import AanmeldingFout, bouw_nieuwe_aanmelding_mail, valideer_en_bouw
from .aanzegging import bereken_aanzeg_status
from .auth import User, load_users, save_users, user_uit_gegevens, verify_login, zet_gebruiker, zet_mail_voorkeuren
from .reliability import bereken_betrouwbaarheid, voeg_actuele_maand_toe
from .reminders import bouw_herinnering, bouw_ingebrekestelling

load_dotenv()

# Zonder dit staat het root-logniveau standaard op WARNING, waardoor alle
# logger.info()-regels in kamerverhuur_scanner (bv. run_check() tijdens "Nu
# controleren") nooit in de gunicorn/docker-logs verschijnen - main.py en de
# scripts/-CLI's zetten dit zelf al bij het opstarten, maar de webapp draait
# via gunicorn "webapp.app:create_app()" en komt hier nooit langs.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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

    def _lees_aanbod_media_veilig(kamer_naam: str) -> list:
        """Haalt de geüploade foto's/video's op voor "Aanbod beheren" - vangt
        een fout af (bv. een beschadigd .meta-bestand, of een schijf-/
        bestandssysteemhapering) zodat één probleembestand niet de hele
        "Aanbod beheren"-pagina laat crashen (kale 500-fout), alleen een
        lege/onvolledige lijst laat zien met een duidelijke melding."""
        try:
            return _aanbod_media().list_bestanden(kamer_naam)
        except Exception:
            app.logger.exception("Ophalen van aanbod-media voor kamer %s is mislukt.", kamer_naam)
            flash("De lijst met foto's/video's kon niet volledig geladen worden - de rest van de pagina werkt gewoon.")
            return []

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

    # --- Mailvoorkeuren (zelfbediening: welke soorten BCC/meldingen wil ik) ---

    @app.route("/account/mail-voorkeuren", methods=["GET", "POST"])
    @login_required
    def mail_voorkeuren_overzicht():
        users = load_users(config.users_file)
        gebruiker = users.get(current_user.id, {})
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            if email and "@" not in email:
                flash("Vul een geldig e-mailadres in (of laat het leeg).")
            else:
                voorkeuren = {
                    type_key: request.form.get(f"voorkeur_{type_key}") == "on"
                    for type_key in mail_voorkeuren.NOTIFICATIE_TYPES
                }
                zet_mail_voorkeuren(users, current_user.id, email, voorkeuren)
                save_users(config.users_file, users)
                flash("Mailvoorkeuren opgeslagen.")
                return redirect(url_for("mail_voorkeuren_overzicht"))
        return render_template(
            "mail_voorkeuren.html", types=mail_voorkeuren.NOTIFICATIE_TYPES, email=gebruiker.get("email") or "",
            voorkeuren={k: mail_voorkeuren.wil_ontvangen(gebruiker, k) for k in mail_voorkeuren.NOTIFICATIE_TYPES},
        )

    def _ontvangers(pand_slug: str, type_key: str, basis: list[str]) -> list[str]:
        """Past de mailvoorkeuren van gebruikers met een account toe op
        `basis` (de bestaande EMAIL_BCC/EMAIL_BCC_BEHEERDER/extra_bcc-lijst)
        - zie kamerverhuur_scanner/mail_voorkeuren.py. `pand_slug` bewust
        expliciet (i.p.v. impliciet g.pand) - deze functie wordt ook gebruikt
        vanuit /tekenen/<token>, een publieke route zonder pand_slug in de
        URL, waar g.pand niet gezet wordt (zie _laad_pand_en_check_toegang())."""
        return mail_voorkeuren.ontvangers(load_users(config.users_file), pand_slug, type_key, basis)

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
            "onderhoud_reserve_per_maand": form.get("onderhoud_reserve_per_maand", "").strip() or None,
            "sleutels": [r.strip() for r in form.get("sleutels", "").splitlines() if r.strip()],
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

    def _laatste_winst(pand_slug: str) -> Decimal | None:
        """Winst van het laatst opgeslagen datapunt (zie state.laad_winst_geschiedenis())
        - GEEN live bunq-aanroep, dat zou elk dashboardbezoek trager maken.
        Wordt bijgewerkt zodra iemand de winstberekeningspagina van dat pand
        bezoekt (en sowieso wekelijks via scripts/winst_snapshot.py)."""
        geschiedenis = state.laad_winst_geschiedenis(pand_slug, config.state_dir)
        return Decimal(geschiedenis[-1]["winst"]) if geschiedenis else None

    def _aantal_beheerders(pand_slug: str) -> int:
        users = load_users(config.users_file)
        aantal = sum(1 for gebruiker in users.values() if mail_voorkeuren.heeft_toegang(gebruiker, pand_slug))
        return aantal or 1

    def _winst_specificatie_alle_panden(panden: list) -> list[dict]:
        """Per pand: laatst bekende winst, aantal beheerders, en het eigen deel
        daarvan (zie winst.verdeelde_winst()) - laat precies zien hoe de
        "totale winst alle panden"-tegel tot stand komt. `laatste`/`verdeeld`
        zijn None voor een pand zonder enig winst-datapunt (nog nooit de
        winstpagina bezocht, en de wekelijkse snapshot nog niet geweest) -
        telt dan niet mee in het totaal, maar staat wel in het rijtje."""
        specificatie = []
        for pand in panden:
            laatste = _laatste_winst(pand.slug)
            aantal_beheerders = _aantal_beheerders(pand.slug)
            verdeeld = winst.verdeelde_winst(laatste, aantal_beheerders) if laatste is not None else None
            specificatie.append({
                "pand": pand, "laatste": laatste, "aantal_beheerders": aantal_beheerders, "verdeeld": verdeeld,
            })
        return specificatie

    def _totale_winst(specificatie: list[dict]) -> Decimal:
        return sum((regel["verdeeld"] for regel in specificatie if regel["verdeeld"] is not None), Decimal("0"))

    _BETAALD_STATUSSEN = {Status.BETAALD.value, Status.TE_VEEL.value}

    def _aggregeer_betalingen(resultaten: list[dict]) -> dict:
        """Telt betaal-resultaten (dicts met verwacht_bedrag/ontvangen_bedrag/status,
        zowel uit de state-cache als uit een live run_check) op tot totalen over alle
        panden: hoeveel kamers al betaald zijn (status Betaald of Te veel ontvangen),
        het totaal aantal kamers, en het totaal ontvangen/verwacht bedrag."""
        return {
            "betaald": sum(1 for r in resultaten if r["status"] in _BETAALD_STATUSSEN),
            "totaal": len(resultaten),
            "ontvangen": sum((Decimal(r["ontvangen_bedrag"]) for r in resultaten), Decimal("0")),
            "verwacht": sum((Decimal(r["verwacht_bedrag"]) for r in resultaten), Decimal("0")),
        }

    def _betalingen_huidige_maand(panden: list) -> dict:
        """Betalingen deze maand over alle opgegeven panden, uit de state-cache (de
        laatste 'Nu controleren'/dagelijkse controle) - dus snel, geen live
        bunq-/sheet-aanroepen. Panden zonder cache tellen simpelweg niet mee."""
        resultaten: list[dict] = []
        for pand in panden:
            cache = state.load(pand.slug, config.state_dir)
            if cache:
                resultaten.extend(cache["resultaten"])
        return _aggregeer_betalingen(resultaten)

    def _eerste_van_volgende_maand(vandaag: date) -> date:
        return date(vandaag.year + 1, 1, 1) if vandaag.month == 12 else date(vandaag.year, vandaag.month + 1, 1)

    def _betalingen_komende_maand(panden: list, vandaag: date) -> tuple[dict, list[str]]:
        """Betalingen die (per de 17e-grens, zie runner._effectieve_maand) al voor
        volgende maand binnen zijn - zodat je in de lopende maand alvast ziet wie
        vooruitbetaald heeft. Dit staat niet in de cache (die gaat over deze maand),
        dus dit haalt per pand live een dry-run-controle op voor de eerste van
        volgende maand. Een pand dat faalt (bv. bunq/sheet-storing) mag de pagina niet
        breken; die komt in de teruggegeven foutenlijst."""
        volgende = _eerste_van_volgende_maand(vandaag)
        resultaten: list[dict] = []
        fouten: list[str] = []
        for pand in panden:
            try:
                _tenants, results, _unmatched = run_check(config, pand, dry_run=True, vandaag=volgende)
            except Exception as exc:  # noqa: BLE001 - één pand mag de hele pagina niet breken
                fouten.append(f"{pand.naam}: kon komende maand niet ophalen ({exc})")
                continue
            resultaten.extend(
                {
                    "verwacht_bedrag": str(r.tenant.verwacht_bedrag),
                    "ontvangen_bedrag": str(r.ontvangen_bedrag),
                    "status": r.status.value,
                }
                for r in results
            )
        return _aggregeer_betalingen(resultaten), fouten

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
            winst_laatste=_laatste_winst(pand_slug),
        )

    @app.route("/pand/<pand_slug>/sleutels")
    @login_required
    def sleuteloverzicht(pand_slug: str):
        return render_template("sleuteloverzicht.html", sleutels=g.pand.sleutels)

    @app.route("/pand/<pand_slug>/winst")
    @login_required
    def winstberekening(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        specificatie = verwachte_huurinkomsten_specificatie(sheet.get_kamers())
        overzicht = bereken_winstoverzicht(config, g.pand, specificatie)
        state.voeg_winst_snapshot_toe(pand_slug, overzicht.winst, config.state_dir)
        return render_template(
            "winst.html", overzicht=overzicht,
            geschiedenis=state.laad_winst_geschiedenis(pand_slug, config.state_dir),
        )

    @app.route("/pand/<pand_slug>/winst/negeer", methods=["POST"])
    @login_required
    def winst_last_negeren(pand_slug: str):
        sleutel = request.form.get("sleutel", "").strip()
        omschrijving = request.form.get("omschrijving", "").strip() or sleutel
        if sleutel:
            state.negeer_last(pand_slug, sleutel, omschrijving, config.state_dir)
            flash(f"'{omschrijving}' telt niet meer mee als vaste last.")
        return redirect(url_for("winstberekening", pand_slug=pand_slug))

    @app.route("/pand/<pand_slug>/winst/negeerlijst")
    @login_required
    def winst_negeerlijst(pand_slug: str):
        genegeerd = state.laad_genegeerde_lasten(pand_slug, config.state_dir)
        return render_template("winst_negeerlijst.html", genegeerd=genegeerd)

    @app.route("/pand/<pand_slug>/winst/negeerlijst/herstel", methods=["POST"])
    @login_required
    def winst_negeerlijst_herstellen(pand_slug: str):
        sleutel = request.form.get("sleutel", "").strip()
        if sleutel:
            state.verwijder_genegeerde_last(pand_slug, sleutel, config.state_dir)
            flash("Weer teruggezet - telt weer mee als die aan de herkenningsregels voldoet.")
        return redirect(url_for("winst_negeerlijst", pand_slug=pand_slug))

    @app.route("/winst-overzicht")
    @login_required
    def winst_overzicht():
        eigen_panden = [p for p in _properties() if current_user.heeft_toegang(p.slug)]
        reeksen = {p.slug: state.laad_winst_geschiedenis(p.slug, config.state_dir) for p in eigen_panden}
        aantal_beheerders = {p.slug: _aantal_beheerders(p.slug) for p in eigen_panden}
        geschiedenis = winst.gecombineerde_winst_over_tijd(reeksen, aantal_beheerders)
        specificatie = _winst_specificatie_alle_panden(eigen_panden)
        totaal = _totale_winst(specificatie)

        vandaag = date.today()
        betalingen_nu = _betalingen_huidige_maand(eigen_panden)
        betalingen_komend, komend_fouten = _betalingen_komende_maand(eigen_panden, vandaag)
        volgende = _eerste_van_volgende_maand(vandaag)
        return render_template(
            "winst_overzicht.html", geschiedenis=geschiedenis, panden=eigen_panden,
            specificatie=specificatie, totaal=totaal,
            huidige_maandnaam=f"{_MAAND_NAMEN[vandaag.month - 1]} {vandaag.year}",
            komende_maandnaam=f"{_MAAND_NAMEN[volgende.month - 1]} {volgende.year}",
            betalingen_nu=betalingen_nu, betalingen_komend=betalingen_komend,
            komend_fouten=komend_fouten,
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
        return render_template(
            "huurders.html", kamers=kamers,
            vertrokken_huurders=sheet.get_recent_vertrokken_huurders(),
        )

    @app.route("/pand/<pand_slug>/huurders/oud")
    @login_required
    def oude_huurders(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        return render_template("oude_huurders.html", oude_huurders=sheet.get_alle_vertrokken_huurders())

    @app.route("/pand/<pand_slug>/huurders/oud/<int:row_index>")
    @login_required
    def oude_huurder_detail(pand_slug: str, row_index: int):
        sheet = SheetClient(config, g.pand)
        oud = sheet.get_vertrokken_huurder(row_index)
        if oud is None:
            abort(404)
        # Historie-regels blijven permanent per kamer staan (ook nadat een
        # andere huurder is ingevoerd) en de huurdernaam van een bestaande
        # regel wordt nooit meer overschreven (zie SheetClient.upsert_history)
        # - dus filteren op naam geeft precies de maanden terug die déze
        # (voormalige) huurder zelf betaalde.
        geschiedenis = [r for r in sheet.get_geschiedenis(oud.kamer) if r.huurder == oud.naam]
        return render_template(
            "oude_huurder_detail.html", oud=oud, geschiedenis=list(reversed(geschiedenis)),
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
                drive_sync.verhuis_naar_oude_huurders(config, g.pand, kamer.naam)
            if velden["naam"] and velden["naam"] != kamer.naam:
                drive_sync.maak_huurder_map(config, g.pand, velden["naam"])
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
        # Ruimere termijn dan het grijze "recent vertrokken"-blokje op de
        # Huurders-pagina (dat gaat om zichtbaarheid, dit om nog daadwerkelijk
        # kunnen mailen) - soms staat een nieuwe huurder al in de sheet
        # terwijl de vorige huurder de laatste weken van hun opzegtermijn nog
        # gewoon in de kamer woont, en moet je dus de vertrokken huurder
        # kunnen bereiken i.p.v. de nieuwe.
        oude_huurders = sheet.get_recent_vertrokken_huurders(dagen=61)
        oude_huurders_met_mail = [h for h in oude_huurders if h.email]
        oude_huurders_zonder_mail = [h for h in oude_huurders if not h.email]

        if request.method == "POST":
            onderwerp = request.form.get("onderwerp", "").strip()
            tekst = request.form.get("tekst", "").strip()
            geselecteerde_kamers = request.form.getlist("kamers")
            try:
                geselecteerde_oude_huurders = [int(r) for r in request.form.getlist("oude_huurders")]
            except ValueError:
                geselecteerde_oude_huurders = []
            ontvangers = [t for t in tenants_met_mail if t.kamer in geselecteerde_kamers]
            ontvangers += [h for h in oude_huurders_met_mail if h.row_index in geselecteerde_oude_huurders]
            if not onderwerp or not tekst or not ontvangers:
                if not onderwerp or not tekst:
                    flash("Onderwerp en tekst zijn verplicht.")
                else:
                    flash("Selecteer minstens 1 huurder om naar te mailen.")
                return render_template(
                    "huishouden_mailen.html", tenants_met_mail=tenants_met_mail,
                    tenants_zonder_mail=tenants_zonder_mail, oude_huurders_met_mail=oude_huurders_met_mail,
                    oude_huurders_zonder_mail=oude_huurders_zonder_mail, onderwerp=onderwerp, tekst=tekst,
                    geselecteerde_kamers=geselecteerde_kamers,
                    geselecteerde_oude_huurders=geselecteerde_oude_huurders,
                )
            bcc = _ontvangers(g.pand.slug, "huishouden", list(dict.fromkeys(config.email_bcc + g.pand.extra_bcc)))
            aan = ", ".join(t.email for t in ontvangers)
            try:
                verstuur_email(config, aan, onderwerp, tekst, bcc=bcc)
                flash(
                    f"Mail verstuurd naar het hele huishouden ({len(ontvangers)} huurder(s), "
                    "als groep in één mail)."
                )
            except MailError:
                flash("Versturen van de mail is mislukt.")
            zonder_mail = tenants_zonder_mail + oude_huurders_zonder_mail
            if zonder_mail:
                flash(
                    "Geen e-mailadres bekend voor: "
                    f"{', '.join(t.naam for t in zonder_mail)} - deze hebben niets ontvangen."
                )
            return redirect(url_for("huurders", pand_slug=pand_slug))

        return render_template(
            "huishouden_mailen.html", tenants_met_mail=tenants_met_mail,
            tenants_zonder_mail=tenants_zonder_mail, oude_huurders_met_mail=oude_huurders_met_mail,
            oude_huurders_zonder_mail=oude_huurders_zonder_mail,
            onderwerp=request.args.get("onderwerp", ""), tekst=request.args.get("tekst", ""),
            geselecteerde_kamers=[t.kamer for t in tenants_met_mail], geselecteerde_oude_huurders=[],
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
            bcc = _ontvangers(g.pand.slug, "herinneringen", list(dict.fromkeys(config.email_bcc + g.pand.extra_bcc)))
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

    # --- Aanbod beheren (foto's/video's + beschikbaarheid voor de publieke aanbodpagina) ---

    @app.route("/pand/<pand_slug>/kamers/<kamer_naam>/aanbod", methods=["GET", "POST"])
    @login_required
    def kamer_aanbod(pand_slug: str, kamer_naam: str):
        sheet = SheetClient(config, g.pand)
        kamer = _kamer_of_404(sheet, kamer_naam)
        if request.method == "POST":
            beschikbaar = request.form.get("beschikbaar") == "on"
            omschrijving = request.form.get("omschrijving", "").strip() or None
            prijs = request.form.get("advertentie_prijs", "").strip()
            oppervlakte = request.form.get("advertentie_oppervlakte", "").strip() or None
            beschikbaar_per = request.form.get("advertentie_beschikbaar_per", "").strip() or None
            beschikbaar_tot = request.form.get("advertentie_beschikbaar_tot", "").strip() or None
            borg = request.form.get("advertentie_borg", "").strip()
            try:
                prijs_bedrag = parse_bedrag(prijs) if prijs else None
                borg_bedrag = parse_bedrag(borg) if borg else None
            except ValueError:
                flash("Kon de prijs of waarborgsom niet lezen - vul een bedrag in zoals 725,00 of 725.")
                media = _lees_aanbod_media_veilig(kamer_naam)
                standaard_omschrijving = kamer.advertentie_omschrijving or ads.genereer_advertentie(g.pand, kamer)["beschrijving"]
                return render_template(
                    "kamer_aanbod.html", kamer=kamer, media=media, standaard_omschrijving=standaard_omschrijving,
                )
            try:
                sheet.update_aanbod(
                    kamer.row_index, beschikbaar, omschrijving, kamer.advertentie_map_id,
                    prijs=prijs_bedrag, oppervlakte=oppervlakte,
                    beschikbaar_per=beschikbaar_per, beschikbaar_tot=beschikbaar_tot,
                    borg=borg_bedrag,
                )
            except Exception:
                app.logger.exception(
                    "Bijwerken van aanbod voor kamer %s (pand %s) is mislukt.", kamer_naam, pand_slug
                )
                flash(
                    "Opslaan is helaas mislukt door een fout bij het schrijven naar de sheet - "
                    "probeer het nog eens, en laat het weten als dit blijft gebeuren."
                )
                media = _lees_aanbod_media_veilig(kamer_naam)
                standaard_omschrijving = kamer.advertentie_omschrijving or ads.genereer_advertentie(g.pand, kamer)["beschrijving"]
                return render_template(
                    "kamer_aanbod.html", kamer=kamer, media=media, standaard_omschrijving=standaard_omschrijving,
                )
            flash("Aanbod bijgewerkt.")
            return redirect(url_for("kamer_aanbod", pand_slug=pand_slug, kamer_naam=kamer_naam))
        media = _lees_aanbod_media_veilig(kamer_naam)
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
        # (kamer, naam, email) van elke al ingeplande bezichtiging - zodat de
        # pagina kan tonen wie al is uitgenodigd, handig bij het kiezen van
        # een vervanger voor een afgezegd tijdslot.
        ingepland = {(b[3], b[4], b[5]) for b in sheet.get_bezichtigingen()}
        return render_template("aanmeldingen.html", rijen=sheet.get_aanmeldingen(), ingepland=ingepland)

    @app.route("/pand/<pand_slug>/aanmeldingen/wissen", methods=["POST"])
    @login_required
    def aanmeldingen_wissen(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        sheet.wis_aanmeldingen()
        flash("Lijst met aanmeldingen gewist.")
        return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))

    @app.route("/pand/<pand_slug>/aanmeldingen/bezichtigingen")
    @login_required
    def bezichtigingen_overzicht(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        rijen = sheet.get_bezichtigingen_met_rijnummer()
        rijen.sort(key=lambda item: (item[1][0], item[1][1]))  # datum, tijd_start
        return render_template("bezichtigingen_overzicht.html", rijen=rijen)

    @app.route("/pand/<pand_slug>/aanmeldingen/bezichtigingen/verwijderen", methods=["POST"])
    @login_required
    def bezichtigingen_verwijderen(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        try:
            rijnummers = [int(r) for r in request.form.getlist("rijnummers")]
        except ValueError:
            flash("Ongeldige aanvraag - probeer opnieuw.")
            return redirect(url_for("bezichtigingen_overzicht", pand_slug=pand_slug))
        if not rijnummers:
            flash("Selecteer minstens 1 bezichtiging om te verwijderen.")
            return redirect(url_for("bezichtigingen_overzicht", pand_slug=pand_slug))
        # van hoog naar laag rijnummer verwijderen - anders schuiven latere
        # rijnummers op en verwijder je per ongeluk de verkeerde regel
        for rijnummer in sorted(rijnummers, reverse=True):
            try:
                sheet.verwijder_bezichtiging(rijnummer)
            except Exception:
                app.logger.exception("Verwijderen van bezichtiging (rij %s) mislukt.", rijnummer)
                flash("Verwijderen van één of meer bezichtigingen is mislukt - probeer het nog eens.")
                return redirect(url_for("bezichtigingen_overzicht", pand_slug=pand_slug))
        flash(f"{len(rijnummers)} bezichtiging(en) verwijderd - dat tijdslot is nu weer vrij.")
        return redirect(url_for("bezichtigingen_overzicht", pand_slug=pand_slug))

    # --- Documenten opvragen bij de gekozen kandidaat (na de bezichtiging) ---

    def _documenten_media(pand=None) -> LokaleMediaClient:
        return LokaleMediaClient(config, pand or g.pand, "documentverzoeken")

    def _upload_url(token: str) -> str:
        return url_for("kandidaat_documenten_upload", token=token, _external=True)

    def _vind_aanmelding_rij(pand, verzoek: dict) -> list[str] | None:
        """Zoekt de aanmelding van deze kandidaat op, via kamer+naam+email -
        dezelfde combinatie waarmee het documentverzoek zelf is aangemaakt
        (zie documentverzoek.maak_sleutel()). None als er geen (meer) te
        vinden is (bv. de aanmeldingenlijst is intussen gewist)."""
        sheet = SheetClient(config, pand)
        return next(
            (r for r in sheet.get_aanmeldingen() if r[1] == verzoek["kamer"] and r[2] == verzoek["naam"] and r[3] == verzoek["email"]),
            None,
        )

    def _studiebewijs_van_aanmelding(pand, verzoek: dict, aanmelding_rij: list[str] | None) -> tuple[str, str, bytes] | None:
        if aanmelding_rij is None or not aanmelding_rij[15]:
            return None
        bestand_id = aanmelding_rij[15].rsplit("/", 1)[-1]
        return _aanmeldingen_media(pand).lees_bestand(verzoek["kamer"], bestand_id)

    def _kopieer_studie_bewijs_naar_drive(pand, verzoek: dict) -> None:
        """Kopieert het eerder aangeleverde bewijs van inschrijving (indien
        aanwezig) ook naar de Drive-map van de kandidaat - zo staan alle
        documenten van deze kandidaat straks bij elkaar, ongeacht wanneer ze
        zijn aangeleverd. Best-effort: een ontbrekende/onvindbare aanmelding
        mag de rest van de upload nooit laten mislukken."""
        try:
            aanmelding_rij = _vind_aanmelding_rij(pand, verzoek)
            gevonden = _studiebewijs_van_aanmelding(pand, verzoek, aanmelding_rij)
            if gevonden is None:
                return
            bestandsnaam, _mimetype, inhoud = gevonden
            drive_sync.upload_bestand(config, pand, verzoek["naam"], bestandsnaam, inhoud)
        except Exception:
            app.logger.exception(
                "Kopiëren van bewijs inschrijving naar Drive is mislukt (pand %s, sleutel %s).",
                pand.slug, verzoek["sleutel"],
            )

    def _genereer_concept_contract_uit_ai_resultaat(pand, pand_slug: str, verzoek: dict, ai_resultaat: dict, aanmelding_rij: list[str] | None) -> str:
        sheet = SheetClient(config, pand)
        kamers = sheet.get_kamers()
        kamer_tenant = next((k for k in kamers if k.kamer == verzoek["kamer"]), None)
        aantal_bewoners = len([k for k in kamers if k.naam]) or len(kamers) or 1

        def _geld(bedrag):
            return f"€{format_bedrag_nl(bedrag)}" if bedrag is not None else ""

        form_data = {
            "kamer": verzoek["kamer"],
            "kamer_omschrijving": "",
            # De naam op het ID-document is leidend voor het contract (dat is
            # de wettelijke naam) - valt terug op de aanmelding/het
            # documentverzoek zelf als de AI geen naam kon uitlezen.
            "huurder_naam": ai_resultaat.get("volledige_naam") or (aanmelding_rij[2] if aanmelding_rij else "") or verzoek["naam"],
            "geboortedatum": ai_resultaat.get("geboortedatum") or "",
            "geboorteplaats": ai_resultaat.get("geboorteplaats") or "",
            "studentnummer": ai_resultaat.get("studentnummer") or (aanmelding_rij[7] if aanmelding_rij else ""),
            "studierichting": ai_resultaat.get("studierichting") or (aanmelding_rij[6] if aanmelding_rij else ""),
            "email": verzoek["email"],
            "borgsteller_naam": aanmelding_rij[16] if aanmelding_rij else "",
            "borgsteller_relatie": aanmelding_rij[17] if aanmelding_rij else "",
            "borgsteller_email": aanmelding_rij[18] if aanmelding_rij else "",
            "kale_huurprijs": _geld(kamer_tenant.kale_huurprijs) if kamer_tenant else "",
            "servicekosten": _geld(kamer_tenant.servicekosten) if kamer_tenant else "",
            "huurprijs": _geld(kamer_tenant.verwacht_bedrag) if kamer_tenant else "",
            "borg": "",
            "aantal_bewoners": str(aantal_bewoners),
            "ingangsdatum": (aanmelding_rij[8] if aanmelding_rij else "") or date.today().isoformat(),
            "einddatum": "",
            "bijzonderheden": "",
        }
        return contracts.genereer_contract(pand_slug, pand, ImmutableMultiDict(form_data), config.state_dir)

    def _verwerk_documenten_met_ai(pand, pand_slug: str, verzoek: dict) -> None:
        """De "magie": leest de zojuist geuploade documenten (+ het eerder
        aangeleverde bewijs van inschrijving) met AI uit, vergelijkt dat met
        de aanmelding, en stelt op basis daarvan automatisch een concept-
        huurcontract op - met een bevestigingsmail naar de beheerder. Volledig
        best-effort en op de achtergrond van de uploadaanvraag: als AI niet
        is ingesteld, een document onleesbaar is, of er iets anders misgaat,
        blijft gewoon alles staan zoals het is - de beheerder kan het concept
        dan nog steeds handmatig opstellen via de bestaande "Contract maken"-
        knop bij Aanmeldingen."""
        try:
            aanmelding_rij = _vind_aanmelding_rij(pand, verzoek)
            documenten: list[tuple[str, str, bytes]] = []
            for doc in verzoek["documenten"]:
                gevonden = _documenten_media(pand).lees_bestand(verzoek["sleutel"], doc["bestand_id"])
                if gevonden:
                    documenten.append(gevonden)
            studiebewijs = _studiebewijs_van_aanmelding(pand, verzoek, aanmelding_rij)
            if studiebewijs:
                documenten.append(studiebewijs)

            ai_resultaat = document_ai.lees_documenten_uit(config, documenten)
            mismatches = document_ai.vergelijk_met_aanmelding(
                ai_resultaat, verzoek["naam"],
                aanmelding_rij[6] if aanmelding_rij else "", aanmelding_rij[7] if aanmelding_rij else "",
            )
            bestandsnaam = _genereer_concept_contract_uit_ai_resultaat(pand, pand_slug, verzoek, ai_resultaat, aanmelding_rij)
            documentverzoek.zet_ai_resultaat(pand_slug, verzoek["sleutel"], ai_resultaat, mismatches, bestandsnaam, config.state_dir)

            contract_url = url_for("contract_mailen", pand_slug=pand_slug, bestandsnaam=bestandsnaam, _external=True)
            mismatch_tekst = ("\n\nLet op, mogelijk afwijkende gegevens:\n- " + "\n- ".join(mismatches)) if mismatches else ""
            verstuur_email(
                config, "jmmreckman@gmail.com",
                f"Concept-huurcontract klaar - kamer {verzoek['kamer']}, {pand.naam}",
                f"Het concept-huurcontract voor {verzoek['naam']} (kamer {verzoek['kamer']}, {pand.naam}) "
                f"staat klaar, automatisch opgesteld op basis van de aangeleverde documenten:\n{contract_url}"
                f"{mismatch_tekst}",
                bcc=[],
            )
        except document_ai.DocumentAIError as exc:
            app.logger.warning(
                "AI-uitlezen van documenten is overgeslagen (pand %s, sleutel %s): %s", pand.slug, verzoek["sleutel"], exc
            )
        except Exception:
            app.logger.exception(
                "Automatisch verwerken van documenten (AI + concept-contract) is mislukt (pand %s, sleutel %s).",
                pand.slug, verzoek["sleutel"],
            )

    @app.route("/pand/<pand_slug>/aanmeldingen/bezichtigingen/documenten-verzoeken", methods=["POST"])
    @login_required
    def documentverzoek_voorbeeld(pand_slug: str):
        try:
            rijnummers = [int(r) for r in request.form.getlist("rijnummers")]
        except ValueError:
            flash("Ongeldige aanvraag - probeer opnieuw.")
            return redirect(url_for("bezichtigingen_overzicht", pand_slug=pand_slug))
        if len(rijnummers) != 1:
            flash("Selecteer precies 1 kandidaat om documenten bij op te vragen.")
            return redirect(url_for("bezichtigingen_overzicht", pand_slug=pand_slug))

        sheet = SheetClient(config, g.pand)
        gekozen = next((r for rijnummer, r in sheet.get_bezichtigingen_met_rijnummer() if rijnummer == rijnummers[0]), None)
        if gekozen is None:
            flash("Deze bezichtiging bestaat niet meer.")
            return redirect(url_for("bezichtigingen_overzicht", pand_slug=pand_slug))
        _datum, _tijd_start, _tijd_eind, kamer, naam, email, telefoon, _manier, _bel_nr, _bevestigd_op = gekozen
        if not email:
            flash(f"Geen e-mailadres bekend voor {naam or 'deze kandidaat'} - kan geen documentverzoek versturen.")
            return redirect(url_for("bezichtigingen_overzicht", pand_slug=pand_slug))

        # Het verzoek (en dus de echte, unieke upload-link) wordt al hier
        # aangemaakt zodat het voorbeeldscherm de kloppende link kan tonen -
        # er wordt pas gemaild na bevestiging (zie documentverzoek_versturen).
        verzoek = documentverzoek.start_documentverzoek(pand_slug, kamer, naam, email, telefoon, config.state_dir)
        mail = documentverzoek.bouw_documentverzoek_mail(g.pand, kamer, naam, _upload_url(verzoek["token"]))
        return render_template(
            "documentverzoek_voorbeeld.html", sleutel=verzoek["sleutel"], kandidaat_naam=naam,
            onderwerp=mail["onderwerp"], tekst=mail["tekst"],
        )

    @app.route("/pand/<pand_slug>/documentverzoek/<sleutel>/versturen", methods=["POST"])
    @login_required
    def documentverzoek_versturen(pand_slug: str, sleutel: str):
        verzoek = documentverzoek.lees_verzoek(pand_slug, sleutel, config.state_dir)
        if verzoek is None:
            abort(404)
        onderwerp = request.form.get("onderwerp", "").strip()
        tekst = request.form.get("tekst", "").strip()
        if not onderwerp or not tekst:
            flash("Onderwerp en tekst zijn verplicht.")
            return redirect(url_for("bezichtigingen_overzicht", pand_slug=pand_slug))
        bcc = _ontvangers(pand_slug, "contracten", config.email_bcc)
        try:
            verstuur_email(config, verzoek["email"], onderwerp, tekst, bcc=bcc)
        except MailError:
            app.logger.exception("Documentverzoek-mail naar %s is mislukt.", verzoek["email"])
            flash("Versturen van het documentverzoek is mislukt - probeer het nog eens.")
            return redirect(url_for("bezichtigingen_overzicht", pand_slug=pand_slug))
        documentverzoek.markeer_verzonden(pand_slug, sleutel, config.state_dir)
        flash(f"Documentverzoek verstuurd naar {verzoek['naam'] or verzoek['email']}.")
        return redirect(url_for("documentverzoek_status", pand_slug=pand_slug, sleutel=sleutel))

    @app.route("/pand/<pand_slug>/documentverzoeken")
    @login_required
    def documentverzoeken_overzicht(pand_slug: str):
        return render_template(
            "documentverzoeken_overzicht.html", verzoeken=documentverzoek.list_verzoeken(pand_slug, config.state_dir)
        )

    @app.route("/pand/<pand_slug>/documentverzoek/<sleutel>")
    @login_required
    def documentverzoek_status(pand_slug: str, sleutel: str):
        verzoek = documentverzoek.lees_verzoek(pand_slug, sleutel, config.state_dir)
        if verzoek is None:
            abort(404)
        return render_template("documentverzoek_status.html", verzoek=verzoek)

    @app.route("/pand/<pand_slug>/documentverzoek/<sleutel>/bestand/<bestand_id>")
    @login_required
    def documentverzoek_bestand(pand_slug: str, sleutel: str, bestand_id: str):
        gevonden = _documenten_media().lees_bestand(sleutel, bestand_id)
        if not gevonden:
            abort(404)
        naam, mimetype, inhoud = gevonden
        return Response(inhoud, mimetype=mimetype, headers={"Content-Disposition": f'inline; filename="{naam}"'})

    @app.route("/documenten/<token>", methods=["GET", "POST"])
    def kandidaat_documenten_upload(token: str):
        """Publieke uploadpagina (geen login) waarop de kandidaat-huurder,
        via de link uit het documentverzoek, een kopie van ID/paspoort en
        bewijs van inkomen/garantsteller kan aanleveren."""
        gevonden = documentverzoek.zoek_via_token(token, config.state_dir)
        if gevonden is None:
            abort(404)
        pand_slug, verzoek = gevonden
        pand = find_pand(_properties(), pand_slug)
        if pand is None:
            abort(404)

        if request.method == "POST":
            categorieen = {
                "id_bestanden": "Copy of ID or passport",
                "inkomen_bestanden": "Proof of income or guarantor",
            }
            geuploade_documenten = []
            try:
                for veldnaam, categorie_label in categorieen.items():
                    for bestand in request.files.getlist(veldnaam):
                        if not bestand or not bestand.filename:
                            continue
                        bestandsnaam = f"{categorie_label} - {bestand.filename}"
                        inhoud = bestand.read()
                        bestand_id = _documenten_media(pand).upload_bestand(
                            verzoek["sleutel"], bestandsnaam, bestand.mimetype, inhoud
                        )
                        geuploade_documenten.append({
                            "categorie": categorie_label, "bestand_id": bestand_id,
                            "naam": bestandsnaam, "mimetype": bestand.mimetype or "application/octet-stream",
                            "inhoud": inhoud,
                        })
            except Exception:
                app.logger.exception("Uploaden van documenten is mislukt (pand %s, sleutel %s).", pand_slug, verzoek["sleutel"])
                return render_template(
                    "documenten_upload.html", pand=pand, verzoek=verzoek,
                    fout="Sorry, uploading your documents failed. Please try again with smaller files, or contact us directly.",
                ), 500
            if not geuploade_documenten:
                return render_template(
                    "documenten_upload.html", pand=pand, verzoek=verzoek,
                    fout="Please select at least one file to upload.",
                ), 400
            verzoek = documentverzoek.voeg_documenten_toe(
                pand_slug, verzoek["sleutel"],
                [{k: v for k, v in d.items() if k != "inhoud"} for d in geuploade_documenten],
                config.state_dir,
            )

            # De rest - Drive-kopieen, AI-uitlezen en het opstellen van het
            # concept-huurcontract - kan makkelijk 10+ seconden duren (Drive-
            # uploads + Claude-aanroepen). Dat op de achtergrond doen zodat de
            # kandidaat meteen de bevestiging ziet, i.p.v. een hangende pagina
            # die uitnodigt om nog een paar keer op "Upload" te klikken (met
            # dubbel aangeleverde documenten tot gevolg).
            basis_url = request.url_root

            def _verwerk_op_achtergrond() -> None:
                with app.test_request_context(base_url=basis_url):
                    for doc in geuploade_documenten:
                        drive_sync.upload_bestand(config, pand, verzoek["naam"], doc["naam"], doc["inhoud"])
                    _kopieer_studie_bewijs_naar_drive(pand, verzoek)
                    _verwerk_documenten_met_ai(pand, pand_slug, verzoek)
                    # Meldingsmail aan de beheerder(s) is best-effort, mag een
                    # geslaagde upload nooit laten mislukken.
                    ontvangers = _ontvangers(pand_slug, "contracten", config.email_bcc)
                    if not ontvangers:
                        return
                    status_url = url_for(
                        "documentverzoek_status", pand_slug=pand_slug, sleutel=verzoek["sleutel"], _external=True
                    )
                    try:
                        verstuur_email(
                            config, ", ".join(ontvangers),
                            f"Documents received - room {verzoek['kamer']}, {pand.naam}",
                            f"{verzoek['naam']} heeft documenten aangeleverd voor kamer {verzoek['kamer']} "
                            f"({pand.naam}):\n{status_url}",
                            bcc=[],
                        )
                    except MailError:
                        app.logger.exception("Melding van geuploade documenten (sleutel %s) is mislukt.", verzoek["sleutel"])

            if app.testing:
                # Synchroon in tests, zodat die niet op een achtergrondthread
                # hoeven te wachten om de effecten (mails, Drive-uploads,
                # concept-contract) te kunnen verifieren.
                _verwerk_op_achtergrond()
            else:
                threading.Thread(target=_verwerk_op_achtergrond, daemon=True).start()
            return render_template("documenten_upload_bedankt.html", pand=pand, verzoek=verzoek)

        return render_template("documenten_upload.html", pand=pand, verzoek=verzoek, fout=None)

    def _licht_huurders_in_redirect(pand_slug: str, datum_iso: str, afspraken_op_datum: list[dict]):
        datum = date.fromisoformat(datum_iso)
        tijd_vanaf = min(a["tijd_start"] for a in afspraken_op_datum)
        tijd_tot = max(a["tijd_eind"] for a in afspraken_op_datum)
        mail = bezichtiging.bouw_huurders_inlichten_mail(datum, tijd_vanaf, tijd_tot)
        return redirect(
            url_for("huishouden_mailen", pand_slug=pand_slug, onderwerp=mail["onderwerp"], tekst=mail["tekst"])
        )

    @app.route("/pand/<pand_slug>/aanmeldingen/huurders-inlichten")
    @login_required
    def licht_huurders_in(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        lijsten = bezichtiging.groepeer_per_datum(sheet.get_bezichtigingen())
        if not lijsten:
            flash("Nog geen bezichtiging ingepland om huurders over in te lichten.")
            return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))
        if len(lijsten) == 1:
            datum_iso, afspraken = next(iter(lijsten.items()))
            return _licht_huurders_in_redirect(pand_slug, datum_iso, afspraken)
        return render_template("licht_huurders_in_kies_lijst.html", lijsten=lijsten)

    @app.route("/pand/<pand_slug>/aanmeldingen/huurders-inlichten/kies", methods=["POST"])
    @login_required
    def licht_huurders_in_kies(pand_slug: str):
        sheet = SheetClient(config, g.pand)
        lijsten = bezichtiging.groepeer_per_datum(sheet.get_bezichtigingen())
        datum_iso = request.form.get("datum", "").strip()
        afspraken = lijsten.get(datum_iso)
        if afspraken is None:
            flash("Deze lijst bestaat niet (meer) - kies opnieuw.")
            return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))
        return _licht_huurders_in_redirect(pand_slug, datum_iso, afspraken)

    # --- Bezichtiging inplannen (voor geselecteerde aanmelders) ---

    def _aanmelders_of_terug(pand_slug: str, ruwe_aanmelders: list[str]):
        """Parseert de aangevinkte aanmelders, of stuurt terug naar het
        aanmeldingenoverzicht met een foutmelding - gedeeld door alle
        bezichtiging-routes die met dezelfde checkbox-selectie beginnen."""
        if not ruwe_aanmelders:
            flash("Selecteer minstens 1 aanmelder om een bezichtiging voor in te plannen.")
            return None, redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))
        try:
            return [bezichtiging.parse_aanmelder(r) for r in ruwe_aanmelders], None
        except bezichtiging.BezichtigingFout as exc:
            flash(str(exc))
            return None, redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))

    @app.route("/pand/<pand_slug>/aanmeldingen/bezichtiging", methods=["POST"])
    @login_required
    def bezichtiging_formulier(pand_slug: str):
        aanmelders, foutrespons = _aanmelders_of_terug(pand_slug, request.form.getlist("aanmelders"))
        if foutrespons is not None:
            return foutrespons
        return render_template(
            "bezichtiging_plannen.html", aanmelders=aanmelders, ruwe_aanmelders=request.form.getlist("aanmelders"),
            datum="", tijd_vanaf="", tijd_tot="", duur_minuten="15", toevoegen_aan_datum=None,
        )

    @app.route("/pand/<pand_slug>/aanmeldingen/bezichtiging/toevoegen", methods=["POST"])
    @login_required
    def bezichtiging_toevoegen_formulier(pand_slug: str):
        ruwe_aanmelders = request.form.getlist("aanmelders")
        aanmelders, foutrespons = _aanmelders_of_terug(pand_slug, ruwe_aanmelders)
        if foutrespons is not None:
            return foutrespons

        sheet = SheetClient(config, g.pand)
        lijsten = bezichtiging.groepeer_per_datum(sheet.get_bezichtigingen())
        if not lijsten:
            flash(
                "Nog geen eerdere bezichtigingslijst gevonden voor dit pand - gebruik "
                "'Plan bezichtiging in' om een nieuwe lijst te starten."
            )
            return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))
        if len(lijsten) == 1:
            datum_iso, afspraken_op_datum = next(iter(lijsten.items()))
            return _bezichtiging_plannen_response(aanmelders, ruwe_aanmelders, datum_iso, afspraken_op_datum)
        return render_template(
            "bezichtiging_kies_lijst.html", lijsten=lijsten, ruwe_aanmelders=ruwe_aanmelders,
        )

    @app.route("/pand/<pand_slug>/aanmeldingen/bezichtiging/toevoegen/kies", methods=["POST"])
    @login_required
    def bezichtiging_toevoegen_kies(pand_slug: str):
        ruwe_aanmelders = request.form.getlist("aanmelders")
        aanmelders, foutrespons = _aanmelders_of_terug(pand_slug, ruwe_aanmelders)
        if foutrespons is not None:
            return foutrespons

        sheet = SheetClient(config, g.pand)
        lijsten = bezichtiging.groepeer_per_datum(sheet.get_bezichtigingen())
        datum_iso = request.form.get("datum", "").strip()
        afspraken_op_datum = lijsten.get(datum_iso)
        if afspraken_op_datum is None:
            flash("Deze lijst bestaat niet (meer) - kies opnieuw.")
            return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))
        return _bezichtiging_plannen_response(aanmelders, ruwe_aanmelders, datum_iso, afspraken_op_datum)

    def _bezichtiging_plannen_response(aanmelders, ruwe_aanmelders, datum_iso: str, afspraken_op_datum: list[dict]):
        """Rendert het inplanformulier, voorgevuld om aan te sluiten op het
        laatste tijdslot van een al bestaande lijst voor deze datum."""
        laatste = afspraken_op_datum[-1]
        return render_template(
            "bezichtiging_plannen.html", aanmelders=aanmelders, ruwe_aanmelders=ruwe_aanmelders,
            datum=datum_iso, tijd_vanaf=laatste["tijd_eind"], tijd_tot="",
            duur_minuten=str(bezichtiging.duur_minuten_van(laatste)), toevoegen_aan_datum=datum_iso,
        )

    @app.route("/pand/<pand_slug>/aanmeldingen/bezichtiging/voorstel", methods=["POST"])
    @login_required
    def bezichtiging_voorstel(pand_slug: str):
        ruwe_aanmelders = request.form.getlist("aanmelders")
        datum_ruw = request.form.get("datum", "").strip()
        tijd_vanaf_ruw = request.form.get("tijd_vanaf", "").strip()
        tijd_tot_ruw = request.form.get("tijd_tot", "").strip()
        duur_ruw = request.form.get("duur_minuten", "").strip()
        toevoegen_aan_datum = request.form.get("toevoegen_aan_datum", "").strip() or None

        def _terug_naar_formulier(foutmelding: str):
            flash(foutmelding)
            try:
                aanmelders = [bezichtiging.parse_aanmelder(r) for r in ruwe_aanmelders]
            except bezichtiging.BezichtigingFout:
                return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))
            return render_template(
                "bezichtiging_plannen.html", aanmelders=aanmelders, ruwe_aanmelders=ruwe_aanmelders,
                datum=datum_ruw, tijd_vanaf=tijd_vanaf_ruw, tijd_tot=tijd_tot_ruw, duur_minuten=duur_ruw,
                toevoegen_aan_datum=toevoegen_aan_datum,
            )

        if not ruwe_aanmelders:
            flash("Selecteer minstens 1 aanmelder om een bezichtiging voor in te plannen.")
            return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))
        try:
            aanmelders = [bezichtiging.parse_aanmelder(r) for r in ruwe_aanmelders]
        except bezichtiging.BezichtigingFout as exc:
            flash(str(exc))
            return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))
        try:
            datum = date.fromisoformat(datum_ruw)
        except ValueError:
            return _terug_naar_formulier("Vul een geldige datum in.")
        try:
            tijd_vanaf = time.fromisoformat(tijd_vanaf_ruw)
            tijd_tot = time.fromisoformat(tijd_tot_ruw)
        except ValueError:
            return _terug_naar_formulier("Vul een geldige begin- en eindtijd in.")
        if tijd_tot <= tijd_vanaf:
            return _terug_naar_formulier("De eindtijd moet na de begintijd liggen.")
        try:
            duur_minuten = int(duur_ruw)
        except ValueError:
            duur_minuten = 0
        if duur_minuten <= 0:
            return _terug_naar_formulier("Vul een tijdsduur per bezichtiging in van minstens 1 minuut.")

        afspraken = bezichtiging.bereken_planning(aanmelders, tijd_vanaf, duur_minuten)
        ruwe_afspraken = [bezichtiging.serialiseer_afspraak(a) for a in afspraken]
        for a in afspraken:
            a["bel_nummer"] = bezichtiging.bel_nummer(a)
        if afspraken[-1]["tijd_eind"] > tijd_tot.strftime("%H:%M"):
            flash(
                f"Let op: dit past niet allemaal tussen {tijd_vanaf.strftime('%H:%M')} en "
                f"{tijd_tot.strftime('%H:%M')} - de laatste bezichtiging eindigt om {afspraken[-1]['tijd_eind']}."
            )
        sheet = SheetClient(config, g.pand)
        bestaande_emails = {b[5] for b in sheet.get_bezichtigingen()}
        dubbele_emails = bezichtiging.vind_dubbele_emails(afspraken, bestaande_emails)
        return render_template(
            "bezichtiging_voorstel.html", afspraken=afspraken, datum=datum, ruwe_afspraken=ruwe_afspraken,
            dubbele_emails=dubbele_emails,
        )

    @app.route("/pand/<pand_slug>/aanmeldingen/bezichtiging/bevestigen", methods=["POST"])
    @login_required
    def bezichtiging_bevestigen(pand_slug: str):
        try:
            datum = date.fromisoformat(request.form.get("datum", ""))
            afspraken = [bezichtiging.parse_afspraak(r) for r in request.form.getlist("afspraken")]
        except (ValueError, bezichtiging.BezichtigingFout):
            flash("Ongeldige aanvraag - probeer opnieuw vanaf de aanmeldingenlijst.")
            return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))
        if not afspraken:
            flash("Geen bezichtigingen om te bevestigen.")
            return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))

        sheet = SheetClient(config, g.pand)
        datum_iso = datum.isoformat()
        for afspraak in afspraken:
            afspraak["bel_nummer"] = bezichtiging.bel_nummer(afspraak)
            try:
                sheet.add_bezichtiging(datum_iso, afspraak)
            except Exception:
                app.logger.exception("Bezichtiging wegschrijven naar de sheet mislukt voor %s.", afspraak["naam"])

        beheerder_bcc = _ontvangers(g.pand.slug, "bezichtigingen", config.email_bcc_beheerder or config.email_bcc)
        mislukt = []
        for afspraak in afspraken:
            mail = bezichtiging.bouw_bevestigingsmail(g.pand, afspraak, datum)
            try:
                verstuur_email(config, afspraak["email"], mail["onderwerp"], mail["tekst"], bcc=beheerder_bcc)
            except MailError:
                app.logger.exception("Bevestigingsmail bezichtiging mislukt voor %s.", afspraak["email"])
                mislukt.append(afspraak["naam"])

        alle_beheerders = _ontvangers(g.pand.slug, "bezichtigingen", list(dict.fromkeys(config.email_bcc + g.pand.extra_bcc)))
        if alle_beheerders:
            # De volledige, actuele lijst voor deze datum (dus incl. eerder al
            # bevestigde bezichtigingen als dit een aanvulling was) - niet
            # alleen de net toegevoegde afspraken.
            volledige_lijst = bezichtiging.groepeer_per_datum(sheet.get_bezichtigingen()).get(datum_iso, afspraken)
            overzicht = bezichtiging.bouw_overzichtsmail_beheerders(g.pand, volledige_lijst, datum)
            try:
                verstuur_email(
                    config, ", ".join(alle_beheerders), overzicht["onderwerp"], overzicht["tekst"], bcc=[],
                )
            except MailError:
                app.logger.exception("Overzichtsmail bezichtigingen naar beheerders mislukt.")

        gelukt = len(afspraken) - len(mislukt)
        flash(f"Bezichtiging ingepland en bevestigingsmail verstuurd naar {gelukt} van {len(afspraken)} aanmelder(s).")
        if mislukt:
            flash("Mislukt voor: " + ", ".join(mislukt) + " - controleer het e-mailadres en probeer het opnieuw.")
        return redirect(url_for("aanmeldingen_overzicht", pand_slug=pand_slug))

    # --- Afwijzing sturen (voor aanmelders die niet uitgenodigd worden) ---

    @app.route("/pand/<pand_slug>/aanmeldingen/afwijzen", methods=["POST"])
    @login_required
    def afwijzing_formulier(pand_slug: str):
        ruwe_aanmelders = request.form.getlist("aanmelders")
        aanmelders, foutrespons = _aanmelders_of_terug(pand_slug, ruwe_aanmelders)
        if foutrespons is not None:
            return foutrespons
        standaard = afwijzing.standaard_afwijzingsmail(g.pand)
        return render_template(
            "afwijzing_versturen.html", aanmelders=aanmelders, ruwe_aanmelders=ruwe_aanmelders,
            onderwerp=standaard["onderwerp"], tekst=standaard["tekst"],
        )

    @app.route("/pand/<pand_slug>/aanmeldingen/afwijzen/versturen", methods=["POST"])
    @login_required
    def afwijzing_versturen(pand_slug: str):
        ruwe_aanmelders = request.form.getlist("aanmelders")
        onderwerp = request.form.get("onderwerp", "").strip()
        tekst = request.form.get("tekst", "").strip()
        aanmelders, foutrespons = _aanmelders_of_terug(pand_slug, ruwe_aanmelders)
        if foutrespons is not None:
            return foutrespons
        if not onderwerp or not tekst:
            flash("Vul een onderwerp en tekst in.")
            return render_template(
                "afwijzing_versturen.html", aanmelders=aanmelders, ruwe_aanmelders=ruwe_aanmelders,
                onderwerp=onderwerp, tekst=tekst,
            )

        beheerder_bcc = _ontvangers(g.pand.slug, "bezichtigingen", config.email_bcc_beheerder or config.email_bcc)
        mislukt = []
        for aanmelder in aanmelders:
            try:
                verstuur_email(config, aanmelder["email"], onderwerp, tekst, bcc=beheerder_bcc)
            except MailError:
                app.logger.exception("Afwijzingsmail mislukt voor %s.", aanmelder["email"])
                mislukt.append(aanmelder["naam"])

        gelukt = len(aanmelders) - len(mislukt)
        flash(f"Afwijzingsmail verstuurd naar {gelukt} van {len(aanmelders)} aanmelder(s).")
        if mislukt:
            flash("Mislukt voor: " + ", ".join(mislukt) + " - controleer het e-mailadres en probeer het opnieuw.")
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
            drive_sync.verhuis_naar_oude_huurders(config, g.pand, bestaande.naam)
        if nieuwe_naam and nieuwe_naam != bestaande.naam:
            drive_sync.maak_huurder_map(config, g.pand, nieuwe_naam)
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

    def _bevestiging_metadata(pand_slug: str, getekend_bestandsnaam: str, sheet_kamers) -> dict:
        """Metadata (huurder_naam, kamer, email) voor de bevestigingsmail bij
        een volledig ondertekend contract - normaal gewoon de metadata die bij
        het afronden automatisch is meegekopieerd naar de getekende versie
        zelf (zie contracts.genereer_getekend_contract()). Voor oudere, al
        vóór die aanpassing getekende contracten (waarvan het concept en dus
        de eigen metadata inmiddels verwijderd kan zijn, zie
        contracts.verwijder_contract()) valt dit terug op de ondertekenronde
        (naam/mail van de huurder) en - voor de kamer - een zoekopdracht in de
        sheet op die naam. `sheet_kamers` is een lazy callable (géén directe
        SheetClient-aanroep) zodat de sheet alleen bevraagd wordt als deze
        terugvalroute daadwerkelijk nodig is."""
        metadata = contracts.lees_metadata(pand_slug, getekend_bestandsnaam, config.state_dir)
        if metadata.get("email") and metadata.get("kamer"):
            return metadata
        origineel = contracts.origineel_bestandsnaam(getekend_bestandsnaam)
        metadata = {**contracts.lees_metadata(pand_slug, origineel, config.state_dir), **metadata}
        ronde = ondertekenen.lees_ondertekenronde(pand_slug, origineel, config.state_dir)
        if ronde:
            huurder = next((o for o in ronde["ondertekenaars"] if o["rol"] == "huurder"), None)
            if huurder:
                metadata.setdefault("huurder_naam", huurder["naam"])
                metadata.setdefault("email", huurder["email"])
        if not metadata.get("kamer") and metadata.get("huurder_naam"):
            kamer = next((k for k in sheet_kamers() if k.naam == metadata["huurder_naam"]), None)
            if kamer:
                metadata["kamer"] = kamer.kamer
        return metadata

    @app.route("/pand/<pand_slug>/contracten")
    @login_required
    def contracten_overzicht(pand_slug: str):
        cache = state.load(pand_slug, config.state_dir)
        kamers_cache: list | None = None

        def _sheet_kamers():
            nonlocal kamers_cache
            if kamers_cache is None:
                kamers_cache = SheetClient(config, g.pand).get_kamers()
            return kamers_cache

        contracten = []
        for bestandsnaam in contracts.list_contracten(pand_slug, config.state_dir):
            getekend = contracts.is_getekend_contract(bestandsnaam)
            kan_bevestiging_mailen = False
            if getekend:
                # het bestaan van de getekende versie bewijst op zich al dat
                # volledig ondertekend is - alleen de betaling nog checken.
                metadata = _bevestiging_metadata(pand_slug, bestandsnaam, _sheet_kamers)
                if metadata.get("email"):
                    status = state.status_voor_kamer(cache, metadata.get("kamer", ""))
                    kan_bevestiging_mailen = bool(status and status["status"] == Status.BETAALD.value)
            ronde = ondertekenen.lees_ondertekenronde(pand_slug, bestandsnaam, config.state_dir)
            contracten.append({
                "bestandsnaam": bestandsnaam,
                "getekend": getekend,
                # alleen tonen als het ondertekenverzoek ook echt verstuurd is
                # (niet bij een geopend maar niet bevestigd voorbeeldscherm)
                "ronde": ronde if ronde and ronde.get("verzonden_op") else None,
                # "Mail bevestiging"-knop pas als zowel volledig ondertekend
                # is als de betaling (incl. borg) van de kamer binnen is - zie
                # contract_bevestiging() hieronder.
                "kan_bevestiging_mailen": kan_bevestiging_mailen,
            })
        return render_template("contracten.html", contracten=contracten)

    @app.route("/pand/<pand_slug>/contracten/<bestandsnaam>/bevestiging", methods=["GET", "POST"])
    @login_required
    def contract_bevestiging(pand_slug: str, bestandsnaam: str):
        if not contracts.is_getekend_contract(bestandsnaam):
            flash("Dit contract is nog niet volledig ondertekend door alle partijen.")
            return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))
        metadata = _bevestiging_metadata(
            pand_slug, bestandsnaam, lambda: SheetClient(config, g.pand).get_kamers()
        )
        if not metadata.get("email"):
            flash("Geen e-mailadres van de huurder bekend voor dit contract.")
            return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))
        status = state.status_voor_kamer(state.load(pand_slug, config.state_dir), metadata.get("kamer", ""))
        if not status or status["status"] != Status.BETAALD.value:
            flash("De betaling (inclusief borg) voor deze kamer is nog niet volledig ontvangen.")
            return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))

        if request.method == "POST":
            onderwerp = request.form.get("onderwerp", "").strip()
            tekst = request.form.get("tekst", "").strip()
            if not onderwerp or not tekst:
                flash("Onderwerp en tekst zijn verplicht.")
                return redirect(url_for(
                    "contract_bevestiging", pand_slug=pand_slug, bestandsnaam=bestandsnaam,
                ))
            bcc = _ontvangers(g.pand.slug, "contracten", list(dict.fromkeys(config.email_bcc + g.pand.extra_bcc)))
            try:
                verstuur_email(config, metadata["email"], onderwerp, tekst, bcc=bcc)
            except MailError:
                app.logger.exception("Bevestigingsmail naar %s is mislukt.", metadata["email"])
                flash("Versturen van de bevestigingsmail is mislukt.")
            else:
                flash(f"Bevestigingsmail verstuurd naar {metadata.get('huurder_naam') or metadata['email']}.")
            return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))

        if g.pand.heeft_bold_slot:
            bold_link = request.args.get("bold_link", "").strip()
            if not bold_link:
                return render_template("contract_bevestiging_bold_link.html", bestandsnaam=bestandsnaam)
            mail = contracts.bouw_bevestigingsmail(g.pand, metadata, bold_link)
        else:
            mail = contracts.bouw_bevestigingsmail(g.pand, metadata)

        return render_template(
            "contract_bevestiging.html", bestandsnaam=bestandsnaam,
            onderwerp=mail["onderwerp"], tekst=mail["tekst"],
        )

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
        # Query-param -> JS-attribuutnaam (zie de "velden"-map in contract_nieuw.html) van
        # velden die al zijn vooringevuld vanuit een aanmelding (Aanmeldingen > "Contract
        # maken") - die mogen niet worden overschreven door de gegevens van de kamer zelf.
        param_naar_attr = {
            "huurder_naam": "naam", "studentnummer": "studentnummer", "studierichting": "studierichting",
            "email": "email", "borgsteller_naam": "borgstellernaam", "borgsteller_relatie": "borgstellerrelatie",
            "ingangsdatum": "startdatum",
        }
        vooringevulde_velden = [attr for param, attr in param_naar_attr.items() if request.args.get(param, "").strip()]
        return render_template(
            "contract_nieuw.html", kamers=kamers, vandaag=date.today(), aantal_bewoners=aantal_bewoners,
            vooringevulde_velden=vooringevulde_velden,
        )

    @app.route("/pand/<pand_slug>/contracten/<bestandsnaam>/bewerken", methods=["GET", "POST"])
    @login_required
    def contract_bewerken(pand_slug: str, bestandsnaam: str):
        if contracts.is_getekend_contract(bestandsnaam):
            flash("Een al ondertekend contract kan niet meer bewerkt worden.")
            return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))
        try:
            contracts.lees_contract(pand_slug, bestandsnaam, config.state_dir)
        except FileNotFoundError:
            abort(404)
        if request.method == "POST":
            contracts.bewerk_contract(pand_slug, g.pand, bestandsnaam, request.form, config.state_dir)
            flash("Concept-huurcontract bijgewerkt.")
            return redirect(url_for("contracten_overzicht", pand_slug=pand_slug))
        metadata = contracts.lees_metadata(pand_slug, bestandsnaam, config.state_dir)
        return render_template("contract_bewerken.html", bestandsnaam=bestandsnaam, metadata=metadata)

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
        bcc_adressen = _ontvangers(g.pand.slug, "contracten", list(dict.fromkeys(config.email_bcc + g.pand.extra_bcc)))

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

    def _betaalverzoek_uit_metadata(metadata: dict) -> dict:
        huurprijs = parse_bedrag(metadata.get("huurprijs"))
        borg = parse_bedrag(metadata.get("borg"))
        try:
            ingangsdatum = date.fromisoformat(metadata.get("ingangsdatum_iso") or "")
        except ValueError:
            ingangsdatum = date.today()
        return ondertekenen.bereken_betaalverzoek(huurprijs, borg, ingangsdatum)

    def _bouw_huurder_tekenmail(metadata: dict, teken_url: str) -> dict[str, str]:
        betaalverzoek = _betaalverzoek_uit_metadata(metadata)
        return ondertekenen.bouw_betaal_en_tekenmail(g.pand, metadata, teken_url, betaalverzoek)

    def _verstuur_tekenverzoek_mails(ronde: dict, metadata: dict, huurder_override: dict | None = None) -> list[str]:
        """Mailt (opnieuw) elke nog niet getekende ondertekenaar in `ronde` -
        de huurder krijgt het betaalverzoek + tekenlink (desgewenst met een
        aangepaste onderwerp/tekst uit het voorbeeldscherm), de rest alleen
        de tekenlink. Geeft de e-mailadressen terug waarvoor het versturen
        mislukte (best-effort, net als bij 'mail het hele huishouden')."""
        mislukt = []
        bcc = _ontvangers(g.pand.slug, "contracten", config.email_bcc)
        for o in ronde["ondertekenaars"]:
            if not o["email"] or o["ondertekend_op"]:
                continue
            teken_url = _teken_url(o["token"])
            if o["rol"] == "huurder":
                mail = huurder_override or _bouw_huurder_tekenmail(metadata, teken_url)
            else:
                mail = ondertekenen.bouw_tekenmail_overig(o["rol"], o["naam"], g.pand, metadata, teken_url)
            try:
                verstuur_email(config, o["email"], mail["onderwerp"], mail["tekst"], bcc=bcc)
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
        huurder_naam = metadata.get("huurder_naam") or "Onbekend"
        pdf_bestandsnaam = Path(getekend_bestandsnaam).with_suffix(".pdf").name
        drive_sync.upload_bestand(config, pand, huurder_naam, pdf_bestandsnaam, pdf)
        documenten_url = _documenten_url(pand_slug, f"Huidige huurders/{huurder_naam}", extern=True)
        bcc = _ontvangers(pand_slug, "contracten", config.email_bcc)
        for o in ronde["ondertekenaars"]:
            if not o["email"]:
                continue
            mail = ondertekenen.bouw_getekend_contract_mail(
                pand, metadata, o["rol"], o["getekende_naam"] or o["naam"],
                documenten_url=documenten_url if o["rol"] == "verhuurder" else None,
            )
            try:
                verstuur_email(
                    config, o["email"], mail["onderwerp"], mail["tekst"], bcc=bcc,
                    bijlagen=[(pdf_bestandsnaam, "application/pdf", pdf)],
                )
            except MailError:
                app.logger.exception("Mail met ondertekend contract naar %s is mislukt.", o["email"])

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
        methods=["GET", "POST"],
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
            return redirect(url_for("contract_ondertekenstatus", pand_slug=pand_slug, bestandsnaam=bestandsnaam))
        if not doelwit["email"]:
            flash(f"Geen e-mailadres bekend voor {doelwit['naam']}.")
            return redirect(url_for("contract_ondertekenstatus", pand_slug=pand_slug, bestandsnaam=bestandsnaam))

        metadata = contracts.lees_metadata(pand_slug, bestandsnaam, config.state_dir)
        teken_url = _teken_url(doelwit["token"])
        is_huurder = doelwit["rol"] == "huurder"

        if request.method == "POST":
            onderwerp = request.form.get("onderwerp", "").strip()
            tekst = request.form.get("tekst", "").strip()
            if not onderwerp or not tekst:
                flash("Onderwerp en tekst zijn verplicht.")
                return redirect(url_for(
                    "contract_tekenverzoek_opnieuw", pand_slug=pand_slug,
                    bestandsnaam=bestandsnaam, ondertekenaar_id=ondertekenaar_id,
                ))
            # Bewust een smallere BCC dan de rest van de app (config.email_bcc,
            # alle mede-eigenaren) - deze herinneringen gaan alleen naar de
            # beheerder, zie EMAIL_BCC_BEHEERDER in config.py.
            bcc = _ontvangers(pand_slug, "contracten", config.email_bcc_beheerder or config.email_bcc)
            try:
                verstuur_email(config, doelwit["email"], onderwerp, tekst, bcc=bcc)
            except MailError:
                app.logger.exception("Herinneringsmail naar %s is mislukt.", doelwit["email"])
                flash(f"Mail naar {doelwit['naam']} is mislukt.")
            else:
                flash(f"Opnieuw gemaild naar {doelwit['naam']}.")
            return redirect(url_for("contract_ondertekenstatus", pand_slug=pand_slug, bestandsnaam=bestandsnaam))

        onderteken_herinnering = request.args.get("onderteken", "1") == "1"
        betaal_herinnering = request.args.get("betaal", "1") == "1"
        if is_huurder:
            if not onderteken_herinnering and not betaal_herinnering:
                onderteken_herinnering = True
            betaalverzoek = _betaalverzoek_uit_metadata(metadata)
            mail = ondertekenen.bouw_huurder_herinnering(
                g.pand, metadata, teken_url, betaalverzoek, onderteken_herinnering, betaal_herinnering
            )
        else:
            mail = ondertekenen.bouw_tekenmail_overig_herinnering(
                doelwit["rol"], doelwit["naam"], g.pand, metadata, teken_url
            )

        return render_template(
            "contract_tekenverzoek_opnieuw.html", bestandsnaam=bestandsnaam, doelwit=doelwit,
            is_huurder=is_huurder, onderteken_herinnering=onderteken_herinnering,
            betaal_herinnering=betaal_herinnering, onderwerp=mail["onderwerp"], tekst=mail["tekst"],
        )

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

    # --- Documenten (dezelfde automatisch aangemaakte "Steenhub <pandnaam>"-
    # Drive-map als drive_sync.py, doorbladerd via rclone - zie drive_browse.py) ---

    def _documenten_url(pand_slug: str, pad: str, extern: bool = False):
        if pad:
            return url_for("documenten", pand_slug=pand_slug, pad=pad, _external=extern)
        return url_for("documenten", pand_slug=pand_slug, _external=extern)

    def _documenten_kruimels(pad: str) -> list[tuple[str, str]]:
        """(naam, cumulatief-pad) voor elk segment van `pad`, voor het
        broodkruimelpad op de Documenten-pagina."""
        if not pad:
            return []
        cumulatief = []
        kruimels = []
        for deel in pad.strip("/").split("/"):
            cumulatief.append(deel)
            kruimels.append((deel, "/".join(cumulatief)))
        return kruimels

    @app.route("/pand/<pand_slug>/documenten")
    @app.route("/pand/<pand_slug>/documenten/<path:pad>")
    @login_required
    def documenten(pand_slug: str, pad: str = ""):
        if not drive_browse.is_ingesteld(config):
            return render_template("documenten.html", ingesteld=False, bestanden=[], kruimels=[], pad="")
        try:
            bestanden = drive_browse.list_bestanden(config, g.pand, pad)
        except drive_browse.DriveBrowseError as exc:
            flash(str(exc))
            bestanden = []
        return render_template(
            "documenten.html", ingesteld=True, bestanden=bestanden,
            kruimels=_documenten_kruimels(pad), pad=pad,
        )

    @app.route("/pand/<pand_slug>/documenten/upload", methods=["POST"])
    @login_required
    def documenten_upload(pand_slug: str):
        pad = request.form.get("pad", "")
        if not drive_browse.is_ingesteld(config):
            flash("Documenten zijn nog niet ingesteld (RCLONE_REMOTE ontbreekt, zie README).")
            return redirect(_documenten_url(pand_slug, pad))
        aantal = 0
        mislukt = False
        for bestand in request.files.getlist("bestand"):
            if bestand and bestand.filename:
                try:
                    drive_browse.upload_bestand(config, g.pand, pad, bestand.filename, bestand.read())
                    aantal += 1
                except drive_browse.DriveBrowseError:
                    app.logger.exception("Uploaden van een document is mislukt (pand %s).", pand_slug)
                    mislukt = True
        if mislukt:
            flash("Uploaden van (een deel van) de bestanden is helaas mislukt - probeer het opnieuw.")
        else:
            flash(f"{aantal} bestand(en) geupload." if aantal else "Geen bestand geselecteerd.")
        return redirect(_documenten_url(pand_slug, pad))

    @app.route("/pand/<pand_slug>/documenten/nieuwe-map", methods=["POST"])
    @login_required
    def documenten_nieuwe_map(pand_slug: str):
        pad = request.form.get("pad", "")
        if not drive_browse.is_ingesteld(config):
            flash("Documenten zijn nog niet ingesteld (RCLONE_REMOTE ontbreekt, zie README).")
            return redirect(_documenten_url(pand_slug, pad))
        naam = request.form.get("naam", "").strip()
        if naam:
            try:
                drive_browse.maak_map(config, g.pand, pad, naam)
                flash(f"Map '{naam}' aangemaakt.")
            except drive_browse.DriveBrowseError:
                app.logger.exception("Aanmaken van een map is mislukt (pand %s).", pand_slug)
                flash("Aanmaken van de map is helaas mislukt.")
        return redirect(_documenten_url(pand_slug, pad))

    @app.route("/pand/<pand_slug>/documenten/bestand/<path:pad>")
    @login_required
    def documenten_download(pand_slug: str, pad: str):
        try:
            inhoud = drive_browse.lees_bestand(config, g.pand, pad)
        except drive_browse.DriveBrowseError:
            abort(404)
        naam = pad.rsplit("/", 1)[-1]
        mimetype, _ = mimetypes.guess_type(naam)
        return Response(
            inhoud, mimetype=mimetype or "application/octet-stream",
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
            # Meldingsmail (best-effort, mag een geslaagde aanmelding nooit
            # laten mislukken) - bewust alleen naar de beheerder(s) uit
            # EMAIL_BCC_BEHEERDER (standaard alleen jmmreckman@gmail.com),
            # niet naar alle mede-eigenaren uit EMAIL_BCC.
            ontvangers = _ontvangers(pand_slug, "aanmeldingen", config.email_bcc_beheerder or config.email_bcc)
            if ontvangers:
                mail = bouw_nieuwe_aanmelding_mail(
                    g.pand, kamer_naam, aanmelding,
                    url_for("aanmeldingen_overzicht", pand_slug=pand_slug, _external=True),
                )
                try:
                    verstuur_email(config, ", ".join(ontvangers), mail["onderwerp"], mail["tekst"], bcc=[])
                except MailError:
                    app.logger.exception(
                        "Melding van nieuwe aanmelding (kamer %s, pand %s) is mislukt.", kamer_naam, pand_slug
                    )
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
