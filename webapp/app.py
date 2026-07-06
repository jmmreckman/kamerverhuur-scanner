"""Flask-website voor Mahoniestraat 15: dashboard, kamers, betalingen-check en
contracten. Login is beperkt tot de gebruikers in users.json (jij + Justin).

Starten (development): python -m webapp.app
Starten (productie): zie README (gunicorn + webapp.app:create_app()).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from dotenv import load_dotenv
from flask import Flask, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, login_required, login_user, logout_user

from kamerverhuur_scanner import state
from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.drive_client import DriveClient
from kamerverhuur_scanner.models import Tenant
from kamerverhuur_scanner.runner import run_check
from kamerverhuur_scanner.sheet_client import SheetClient
from kamerverhuur_scanner.utils import parse_bedrag

from . import ads, contracts
from .auth import User, load_users, verify_login
from .reliability import bereken_betrouwbaarheid

load_dotenv()


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)

    if config is None:
        try:
            config = Config.load()
        except ConfigError as exc:
            raise SystemExit(f"Configuratiefout: {exc}") from exc

    app.secret_key = config.flask_secret_key

    @app.template_filter("eur")
    def eur(value) -> str:
        return f"{Decimal(str(value)):.2f}"

    @app.template_filter("status_klasse")
    def status_klasse(status_tekst: str) -> str:
        return "status-" + status_tekst.lower().replace(" ", "-")

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(username: str) -> User | None:
        users = load_users(config.users_file)
        return User(username) if username in users else None

    def _kamer_of_404(sheet: SheetClient, kamer_naam: str) -> Tenant:
        for kamer in sheet.get_kamers():
            if kamer.kamer == kamer_naam:
                return kamer
        abort(404, f"Kamer '{kamer_naam}' niet gevonden.")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            users = load_users(config.users_file)
            if verify_login(users, username, password):
                login_user(User(username))
                return redirect(url_for("dashboard"))
            flash("Onjuiste gebruikersnaam of wachtwoord.")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        cache = state.load()
        totalen = None
        if cache:
            totalen = {
                "verwacht": sum(Decimal(r["verwacht_bedrag"]) for r in cache["resultaten"]),
                "ontvangen": sum(Decimal(r["ontvangen_bedrag"]) for r in cache["resultaten"]),
            }
        return render_template("dashboard.html", cache=cache, totalen=totalen)

    @app.route("/huurders")
    @login_required
    def huurders():
        sheet = SheetClient(config)
        kamers = sheet.get_kamers()
        sheet_url = f"https://docs.google.com/spreadsheets/d/{config.google_sheet_id}/edit"
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
        }

    @app.route("/huurders/nieuw", methods=["GET", "POST"])
    @login_required
    def huurder_nieuw():
        if request.method == "POST":
            sheet = SheetClient(config)
            sheet.add_kamer(**_kamer_form_naar_velden(request.form))
            flash("Nieuwe kamer toegevoegd.")
            return redirect(url_for("huurders"))
        return render_template("huurder_bewerken.html", kamer=None)

    @app.route("/huurders/<kamer_naam>/bewerken", methods=["GET", "POST"])
    @login_required
    def huurder_bewerken(kamer_naam: str):
        sheet = SheetClient(config)
        kamer = _kamer_of_404(sheet, kamer_naam)
        if request.method == "POST":
            sheet.update_kamer(row_index=kamer.row_index, **_kamer_form_naar_velden(request.form))
            flash(f"Kamer {kamer_naam} bijgewerkt.")
            return redirect(url_for("huurders"))
        return render_template("huurder_bewerken.html", kamer=kamer)

    @app.route("/betalingen", methods=["GET", "POST"])
    @login_required
    def betalingen():
        net_gecontroleerd = None
        if request.method == "POST":
            _tenants, results, unmatched = run_check(config, dry_run=False)
            net_gecontroleerd = {"results": results, "unmatched": unmatched}
        return render_template("betalingen.html", net_gecontroleerd=net_gecontroleerd, cache=state.load())

    @app.route("/kamers")
    @login_required
    def kamers_overzicht():
        sheet = SheetClient(config)
        return render_template("kamers.html", kamers=sheet.get_kamers(), cache=state.load())

    @app.route("/kamers/<kamer_naam>")
    @login_required
    def kamer_detail(kamer_naam: str):
        sheet = SheetClient(config)
        kamer = _kamer_of_404(sheet, kamer_naam)
        geschiedenis = sheet.get_geschiedenis(kamer_naam)
        return render_template(
            "kamer_detail.html",
            kamer=kamer,
            geschiedenis=list(reversed(geschiedenis)),
            betrouwbaarheid=bereken_betrouwbaarheid(geschiedenis),
            cache_status=state.status_voor_kamer(state.load(), kamer_naam),
            contracten=contracts.list_contracten_voor_kamer(kamer_naam),
        )

    @app.route("/kamers/<kamer_naam>/advertentie")
    @login_required
    def kamer_advertentie(kamer_naam: str):
        sheet = SheetClient(config)
        kamer = _kamer_of_404(sheet, kamer_naam)
        return render_template("advertentie.html", kamer=kamer, advertentie=ads.genereer_advertentie(kamer))

    @app.route("/contracten")
    @login_required
    def contracten_overzicht():
        return render_template("contracten.html", contracten=contracts.list_contracten())

    @app.route("/contracten/nieuw", methods=["GET", "POST"])
    @login_required
    def contract_nieuw():
        sheet = SheetClient(config)
        if request.method == "POST":
            bestandsnaam = contracts.genereer_contract(request.form)
            return redirect(url_for("contract_bekijken", bestandsnaam=bestandsnaam))
        return render_template("contract_nieuw.html", kamers=sheet.get_kamers(), vandaag=date.today())

    @app.route("/contracten/<bestandsnaam>")
    @login_required
    def contract_bekijken(bestandsnaam: str):
        try:
            html = contracts.lees_contract(bestandsnaam)
        except FileNotFoundError:
            abort(404)
        return Response(html, mimetype="text/html")

    def _documenten_url(folder_id: str | None):
        return url_for("documenten", folder_id=folder_id) if folder_id else url_for("documenten")

    @app.route("/documenten")
    @app.route("/documenten/map/<folder_id>")
    @login_required
    def documenten(folder_id: str | None = None):
        if not config.google_drive_folder_id:
            return render_template("documenten.html", bestanden=None, kruimels=[], folder_id=None)
        drive = DriveClient(config)
        return render_template(
            "documenten.html",
            bestanden=drive.list_bestanden(folder_id),
            kruimels=drive.get_pad(folder_id),
            folder_id=folder_id,
        )

    @app.route("/documenten/upload", methods=["POST"])
    @login_required
    def documenten_upload():
        folder_id = request.form.get("folder_id") or None
        if not config.google_drive_folder_id:
            flash("Documenten zijn nog niet ingesteld (GOOGLE_DRIVE_FOLDER_ID ontbreekt in .env).")
            return redirect(_documenten_url(folder_id))
        drive = DriveClient(config)
        aantal = 0
        for bestand in request.files.getlist("bestand"):
            if bestand and bestand.filename:
                drive.upload_bestand(bestand.filename, bestand.mimetype, bestand.read(), folder_id=folder_id)
                aantal += 1
        flash(f"{aantal} bestand(en) geupload." if aantal else "Geen bestand geselecteerd.")
        return redirect(_documenten_url(folder_id))

    @app.route("/documenten/nieuwe-map", methods=["POST"])
    @login_required
    def documenten_nieuwe_map():
        folder_id = request.form.get("folder_id") or None
        if not config.google_drive_folder_id:
            flash("Documenten zijn nog niet ingesteld (GOOGLE_DRIVE_FOLDER_ID ontbreekt in .env).")
            return redirect(_documenten_url(folder_id))
        naam = request.form.get("naam", "").strip()
        if naam:
            DriveClient(config).maak_map(naam, folder_id=folder_id)
            flash(f"Map '{naam}' aangemaakt.")
        return redirect(_documenten_url(folder_id))

    @app.route("/documenten/<file_id>/download")
    @login_required
    def documenten_download(file_id: str):
        drive = DriveClient(config)
        naam, mimetype, inhoud = drive.download_bestand(file_id)
        return Response(
            inhoud,
            mimetype=mimetype,
            headers={"Content-Disposition": f'attachment; filename="{naam}"'},
        )

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
