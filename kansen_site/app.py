"""Kaart-website (kansen.steenhub.nl): toont de actieve kansen die de dagelijkse
Funda-scan al in state.json heeft verzameld, op een kaart + als lijst met filters.
Login is een simpel gedeeld wachtwoord per gebruiker (KANSEN_APP_USERS), los van
de Gmail-/SMTP-instellingen van de scanner zelf - zie rotterdam_scanner/config.py.

Starten (development): python3 -m kansen_site.app
Starten (productie): gunicorn 'kansen_site.app:create_app()'
"""
from __future__ import annotations

import hmac
import json
from dataclasses import asdict
from functools import wraps

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from rotterdam_scanner import den_haag, pipeline
from rotterdam_scanner.config import Config, load_config
from rotterdam_scanner.handmatig import parse_bestand
from rotterdam_scanner.investering import AANTAL_INVESTEERDERS, RekenUitgangspunten, bereken_rekentool
from rotterdam_scanner.investering import aantal_kamers_mogelijk as bereken_aantal_kamers_mogelijk
from rotterdam_scanner.investering import bereken_met_aantal_kamers as bereken_investering
from rotterdam_scanner.state import StateStore

# Velden op de rekentool-pagina (kansen.steenhub.nl), in weergavevolgorde. `soort`
# stuurt de opmaak/parsing: "euro" en "aantal" staan gelijk aan hun opgeslagen
# waarde; "procent" wordt als heel getal getoond/ingevoerd (8, niet 0,08) en bij
# opslaan door 100 gedeeld. De keys komen exact overeen met RekenUitgangspunten.
REKENVELDEN = [
    ("koopsom", "Koopsom", "euro"),
    ("aantal_kamers", "Aantal kamers", "aantal"),
    ("aantal_investeerders", "Aantal investeerders", "aantal"),
    ("overdrachtsbelasting", "Overdrachtsbelasting", "procent"),
    ("bar", "BAR", "procent"),
    ("kale_huur_per_kamer", "Kale huur per kamer", "euro"),
    ("servicekosten_per_kamer", "Servicekosten per kamer", "euro"),
    ("vaste_kosten_per_huurder", "Vaste kosten per maand per huurder", "euro"),
    ("kosten_koper_ex_ovb", "Kosten koper (excl. overdrachtsbelasting)", "euro"),
    ("verbouwkosten", "Verbouwkosten", "euro"),
    ("rente", "Rente", "procent"),
    ("taxatie_verhouding_voor_verhoging", "Taxatieverhouding waarde vóór verhoging", "procent"),
    ("ltv", "LTV (leenbaar t.o.v. taxatie)", "procent"),
]


_PROCENT_VELDEN = {key for key, _label, soort in REKENVELDEN if soort == "procent"}


def _reken_uitgangspunten_dict(item) -> dict:
    """Standaardaannames (RekenUitgangspunten) met de koopsom en het aantal kamers
    voorgevuld uit de woning zelf. Percentages als fractie (0.08)."""
    return asdict(RekenUitgangspunten(
        koopsom=float(item.prijs or 0),
        aantal_kamers=int(item.aantal_kamers_mogelijk or 0),
    ))


def _huidige_uitgangspunten(item) -> dict:
    """De voor déze woning geldende uitgangspunten: standaard + voorvulling,
    overschreven door wat de gebruiker eerder op de rekenpagina heeft aangepast."""
    uitg = _reken_uitgangspunten_dict(item)
    for key, waarde in (item.berekening or {}).items():
        if key in uitg:
            uitg[key] = waarde
    return uitg


def _velden_voor_weergave(uitg: dict) -> list[dict]:
    velden = []
    for key, label, soort in REKENVELDEN:
        waarde = uitg[key]
        if soort == "procent":
            waarde = round(waarde * 100, 4)
        # Hele getallen zonder ".0" tonen (bv. 550 i.p.v. 550.0) - schoner invulveld.
        if isinstance(waarde, float) and waarde.is_integer():
            waarde = int(waarde)
        velden.append({"key": key, "label": label, "soort": soort, "waarde": waarde})
    return velden


def _laad_steenhub_users(pad: str) -> dict:
    """Leest de users.json van de steenhub.nl-app (read-only ingekoppeld, zie
    deploy/docker-compose.yml). Elke gebruiker heeft daar een 'wachtwoord_hash'
    (werkzeug). Ontbreekt/onleesbaar het bestand, dan gewoon geen steenhub-logins."""
    try:
        with open(pad, encoding="utf-8") as bestand:
            data = json.load(bestand)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _steenhub_login_beschikbaar(config: Config) -> bool:
    if not config.steenhub_users_file:
        return False
    users = _laad_steenhub_users(config.steenhub_users_file)
    return any(isinstance(a, dict) and a.get("wachtwoord_hash") for a in users.values())


def _kloppend_wachtwoord(config: Config, gebruiker: str, wachtwoord: str) -> bool:
    # 1) Eigen KANSEN_APP_USERS (los wachtwoord per gebruiker uit de env).
    verwacht = config.kansen_app_users.get(gebruiker)
    if verwacht is not None and hmac.compare_digest(verwacht, wachtwoord):
        # Tijdsveilig vergelijken (hmac.compare_digest) i.p.v. == , zodat de
        # responstijd niets verraadt over hoeveel tekens van het wachtwoord kloppen.
        return True
    # 2) Zelfde accounts als steenhub.nl (users.json met werkzeug-hashes), zodat je
    # met je steenhub-login ook op de kaart-website kunt. Elke poging leest het
    # bestand opnieuw, zodat een nieuwe steenhub-gebruiker meteen werkt zonder de
    # kansen-container te herstarten.
    if config.steenhub_users_file:
        account = _laad_steenhub_users(config.steenhub_users_file).get(gebruiker)
        if isinstance(account, dict) and account.get("wachtwoord_hash"):
            return check_password_hash(account["wachtwoord_hash"], wachtwoord)
    return False


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
        "primaire_oppervlakte": item.primaire_oppervlakte,
        "bag_oppervlakte": item.bag_oppervlakte,
        "oppervlakte_advertentie": item.oppervlakte_advertentie,
        "aantal_kamers_mogelijk": item.aantal_kamers_mogelijk,
        "aantal_kamers_handmatig": item.aantal_kamers_handmatig,
        "winst_pm_pp": item.winst_pm_pp,
        "eigen_inleg_pp": item.eigen_inleg_pp,
        # Investeerder-onafhankelijke totalen, zodat de kaart zelf kan omrekenen
        # naar 1/2/3 investeerders (winst_pm_pp/eigen_inleg_pp staan al gedeeld
        # door AANTAL_INVESTEERDERS; de totalen zijn dat maal het aantal).
        "winst_pm_totaal": None if item.winst_pm_pp is None else item.winst_pm_pp * AANTAL_INVESTEERDERS,
        "eigen_inleg_na_ophoging_totaal": None if item.eigen_inleg_pp is None else item.eigen_inleg_pp * AANTAL_INVESTEERDERS,
        "schakelgeld_totaal": item.schakelgeld_totaal,
        "opslag_percentage": item.opslag_percentage,
        "huurprijsopslag_signalen": item.huurprijsopslag_signalen,
        "stad": item.stad,
        "check_signalen": item.check_signalen,
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

    if not config.kansen_app_users and not _steenhub_login_beschikbaar(config):
        raise SystemExit(
            "Geen inlogbron: KANSEN_APP_USERS is leeg én er is geen bruikbaar STEENHUB_USERS_FILE "
            "(users.json van steenhub.nl). Vul minstens 1 gebruiker:wachtwoord-paar in KANSEN_APP_USERS "
            "in (zie .env.example) of koppel de steenhub-users.json in, anders zou de kaart zonder "
            "wachtwoord open staan."
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

    @app.route("/kansen/<object_id>/kamers", methods=["POST"])
    @login_required
    def kans_kamers_aanpassen(object_id):
        # Laat de gebruiker het aantal kamers per woning handmatig corrigeren (de
        # 18m2-vuistregel klopt in de praktijk niet altijd, bv. bij een ongunstige
        # plattegrond) - winst/eigen inleg worden meteen met dat aantal herberekend.
        # Leeg veld = terug naar de automatisch berekende waarde.
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404

        ruwe_waarde = request.form.get("aantal_kamers", "").strip()
        if ruwe_waarde == "":
            item.aantal_kamers_handmatig = False
            oppervlakte = item.primaire_oppervlakte
            if item.stad == "den_haag":
                item.aantal_kamers_mogelijk = den_haag.bereken_max_bewoners(oppervlakte) if oppervlakte else None
            else:
                item.aantal_kamers_mogelijk = bereken_aantal_kamers_mogelijk(oppervlakte) if oppervlakte else None
        else:
            try:
                aantal = int(ruwe_waarde)
            except ValueError:
                return jsonify({"fout": "Ongeldig aantal kamers."}), 400
            if aantal < 0:
                return jsonify({"fout": "Aantal kamers moet 0 of hoger zijn."}), 400
            item.aantal_kamers_mogelijk = aantal
            item.aantal_kamers_handmatig = True

        if item.prijs and item.aantal_kamers_mogelijk:
            investering = bereken_investering(
                item.aantal_kamers_mogelijk, item.prijs, item.opslag_percentage, m2=item.primaire_oppervlakte
            )
            item.winst_pm_pp = investering.winst_pm_pp if investering else None
            item.eigen_inleg_pp = investering.eigen_inleg_na_ophoging_pp if investering else None
            item.schakelgeld_totaal = investering.totale_zelf_in_te_leggen if investering else None
        else:
            item.winst_pm_pp = None
            item.eigen_inleg_pp = None
            item.schakelgeld_totaal = None

        state.upsert(item)
        state.save()
        return jsonify(_listing_naar_json(item))

    @app.route("/woning/<object_id>/berekening")
    @login_required
    def berekening(object_id):
        # Rekentool per woning: koopsom (vraagprijs) en aantal kamers voorgevuld,
        # alle uitgangspunten aanpasbaar; wat je invult wordt automatisch bij de
        # woning bewaard (zie berekening_opslaan) en de sommen rechts rollen er
        # meteen uit (zie static/berekening.js).
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            abort(404)
        uitg = _huidige_uitgangspunten(item)
        resultaat = bereken_rekentool(RekenUitgangspunten(**uitg))
        return render_template(
            "berekening.html", item=item, velden=_velden_voor_weergave(uitg),
            resultaat=asdict(resultaat), gebruiker=session["gebruiker"],
        )

    @app.route("/woning/<object_id>/berekening", methods=["POST"])
    @login_required
    def berekening_opslaan(object_id):
        # Auto-opslag vanaf de rekenpagina: neemt de ingevulde uitgangspunten over,
        # bewaart ze bij de woning en geeft de doorgerekende sommen terug als JSON.
        state = StateStore(config.state_path)
        item = state.get(object_id)
        if item is None:
            return jsonify({"fout": "Onbekende woning."}), 404

        data = request.get_json(silent=True) or {}
        uitg = _huidige_uitgangspunten(item)
        for key, _label, soort in REKENVELDEN:
            if key not in data:
                continue
            ruw = str(data[key]).replace(",", ".").strip()
            if ruw == "":
                continue
            try:
                waarde = float(ruw)
            except ValueError:
                return jsonify({"fout": f"Ongeldige waarde voor {key}."}), 400
            uitg[key] = waarde / 100 if soort == "procent" else waarde
        uitg["aantal_kamers"] = int(round(uitg["aantal_kamers"]))
        uitg["aantal_investeerders"] = int(round(uitg["aantal_investeerders"])) or 1

        item.berekening = uitg
        state.upsert(item)
        state.save()
        resultaat = bereken_rekentool(RekenUitgangspunten(**uitg))
        return jsonify(asdict(resultaat))

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
                    "al_bekend": len(run_result.al_bekend),
                    "fouten": parse_fouten + run_result.fouten,
                }
        return render_template(
            "handmatig_toevoegen.html", resultaat=resultaat, gebruiker=session["gebruiker"],
        )

    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5001)
