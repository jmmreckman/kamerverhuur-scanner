"""Kaart-website (kansen.steenhub.nl): toont de actieve kansen die de dagelijkse
Funda-scan al in state.json heeft verzameld, op een kaart + als lijst met filters.
Login is een simpel gedeeld wachtwoord per gebruiker (KANSEN_APP_USERS), los van
de Gmail-/SMTP-instellingen van de scanner zelf - zie rotterdam_scanner/config.py.

Starten (development): python3 -m kansen_site.app
Starten (productie): gunicorn 'kansen_site.app:create_app()'
"""
from __future__ import annotations

import hmac
from functools import wraps

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

from rotterdam_scanner import pipeline
from rotterdam_scanner.config import Config, load_config
from rotterdam_scanner.handmatig import parse_bestand
from rotterdam_scanner.state import StateStore


def _kloppend_wachtwoord(config: Config, gebruiker: str, wachtwoord: str) -> bool:
    verwacht = config.kansen_app_users.get(gebruiker)
    if verwacht is None:
        return False
    # Tijdsveilig vergelijken (hmac.compare_digest) i.p.v. == , zodat de
    # responstijd niets verraadt over hoeveel tekens van het wachtwoord kloppen.
    return hmac.compare_digest(verwacht, wachtwoord)


def _listing_naar_json(item) -> dict:
    return {
        "object_id": item.object_id,
        "url": item.url,
        "weergavenaam": item.weergavenaam,
        "wijknaam": item.wijknaam,
        "lat": item.lat,
        "lon": item.lon,
        "prijs": item.prijs,
        "prijs_per_m2": item.prijs_per_m2,
        "bag_oppervlakte": item.bag_oppervlakte,
        "oppervlakte_advertentie": item.oppervlakte_advertentie,
        "aantal_kamers_mogelijk": item.aantal_kamers_mogelijk,
        "winst_pm_pp": item.winst_pm_pp,
        "eigen_inleg_pp": item.eigen_inleg_pp,
        "opslag_percentage": item.opslag_percentage,
        "huurprijsopslag_signalen": item.huurprijsopslag_signalen,
        "woz_check_nodig": item.woz_check_nodig,
        "woz_check_url": item.woz_check_url,
        "opmerking": item.opmerking,
        "eerst_gezien": item.eerst_gezien,
        "laatst_gezien": item.laatst_gezien,
    }


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)

    if config is None:
        config = load_config()

    if not config.kansen_app_users:
        raise SystemExit(
            "KANSEN_APP_USERS ontbreekt of is leeg - vul minstens 1 gebruiker:wachtwoord-paar in "
            "(zie .env.example), anders zou de kaart zonder wachtwoord open staan."
        )
    if not config.kansen_app_secret_key:
        raise SystemExit("KANSEN_APP_SECRET_KEY ontbreekt - vul een willekeurige, geheime waarde in.")

    app.secret_key = config.kansen_app_secret_key

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("gebruiker"):
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)

        return wrapped

    @app.route("/login", methods=["GET", "POST"])
    def login():
        fout = None
        if request.method == "POST":
            gebruiker = request.form.get("gebruiker", "").strip()
            wachtwoord = request.form.get("wachtwoord", "")
            if _kloppend_wachtwoord(config, gebruiker, wachtwoord):
                session["gebruiker"] = gebruiker
                return redirect(request.args.get("next") or url_for("kaart"))
            fout = "Onjuiste gebruikersnaam of wachtwoord."
        return render_template("login.html", fout=fout)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.pop("gebruiker", None)
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def kaart():
        return render_template("kaart.html", gebruiker=session["gebruiker"])

    @app.route("/api/kansen")
    @login_required
    def api_kansen():
        state = StateStore(config.state_path)
        actief = [item for item in state.all() if item.status == "actief" and item.lat is not None and item.lon is not None]
        return jsonify([_listing_naar_json(item) for item in actief])

    @app.route("/ververs", methods=["POST"])
    @login_required
    def ververs():
        # Mail-gebaseerde scan (alleen nieuwe woningen sinds gisteren) - een
        # handmatige "Ververs nu" laat 'm meteen draaien i.p.v. te wachten op
        # de volgende geplande scan.
        result = pipeline.run(config)
        return jsonify({
            "nieuw_actief": len(result.nieuw_actief),
            "nieuw_afgevallen": len(result.nieuw_afgevallen),
            "fouten": result.fouten,
        })

    @app.route("/kansen/<object_id>/verwijderen", methods=["POST"])
    @login_required
    def kans_verwijderen(object_id):
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404
        reden = request.form.get("reden", "").strip() or "Handmatig verwijderd via kansen.steenhub.nl."
        item.status = "afgevallen"
        item.handmatig_verwijderd = True
        item.afvalreden = reden
        state.upsert(item)
        state.save()
        return jsonify({"ok": True})

    @app.route("/kansen/<object_id>/terugplaatsen", methods=["POST"])
    @login_required
    def kans_terugplaatsen(object_id):
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404
        item.status = "actief"
        item.handmatig_verwijderd = False
        item.afvalreden = None
        state.upsert(item)
        state.save()
        flash(f"{item.weergavenaam} teruggeplaatst.")
        return redirect(url_for("verwijderd"))

    @app.route("/verwijderd")
    @login_required
    def verwijderd():
        state = StateStore(config.state_path)
        items = sorted(
            (item for item in state.all() if item.handmatig_verwijderd),
            key=lambda item: item.laatst_gezien, reverse=True,
        )
        return render_template("verwijderd.html", items=items, gebruiker=session["gebruiker"])

    @app.route("/handmatig-toevoegen", methods=["GET", "POST"])
    @login_required
    def handmatig_toevoegen():
        # Voor achterstanden/gebieden die de mail-alert niet dekt: plak een
        # lijst adressen ("POSTCODE HUISNUMMER [funda-link]", één per regel)
        # of een ruwe kopieer-plak van een Funda-resultatenpagina - zelfde
        # parser (rotterdam_scanner/handmatig.py) en dezelfde checks als het
        # bestaande CLI-script handmatig_toevoegen.py, nu ook vanaf de
        # website bereikbaar.
        resultaat = None
        if request.method == "POST":
            tekst = request.form.get("tekst", "")
            forceer_herprocessen = request.form.get("forceer_herprocessen") == "on"
            listings, parse_fouten = parse_bestand(tekst)
            if not listings:
                flash("Geen enkel adres kon uit de geplakte tekst gelezen worden.")
            else:
                run_result = pipeline.run_handmatig(
                    config, listings, forceer_herprocessen=forceer_herprocessen,
                )
                resultaat = {
                    "aangeleverd": len(listings),
                    "nieuw_actief": len(run_result.nieuw_actief),
                    "nieuw_afgevallen": len(run_result.nieuw_afgevallen),
                    "nieuw_onbekend_adres": len(run_result.nieuw_onbekend_adres),
                    "fouten": parse_fouten + run_result.fouten,
                }
        return render_template(
            "handmatig_toevoegen.html", resultaat=resultaat, gebruiker=session["gebruiker"],
        )

    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5001)
