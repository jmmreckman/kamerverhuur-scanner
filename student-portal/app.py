import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, abort

app = Flask(__name__)
app.secret_key = "mentorles-portal-geheim-2024"

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "portal.db")
WERKBLADEN_DIR = os.path.join(os.path.dirname(__file__), "werkbladen")
DOCENT_WACHTWOORD = "docent123"  # Verander dit in iets sterkers!


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS leerlingen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT UNIQUE NOT NULL,
            pin TEXT
        );
        CREATE TABLE IF NOT EXISTS antwoorden (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leerling_id INTEGER NOT NULL,
            les_bestand TEXT NOT NULL,
            inhoud TEXT NOT NULL DEFAULT '',
            bijgewerkt_op TEXT NOT NULL,
            UNIQUE(leerling_id, les_bestand),
            FOREIGN KEY (leerling_id) REFERENCES leerlingen(id)
        );
    """)
    conn.commit()

    # Voeg standaard leerlingen toe als de tabel leeg is
    cursor = conn.execute("SELECT COUNT(*) FROM leerlingen")
    if cursor.fetchone()[0] == 0:
        leerlingen_met_pin = [
            ("Aiden",       "2824"),
            ("Amayah",      "1409"),
            ("Anna",        "5506"),
            ("Eline",       "5012"),
            ("Emily",       "4657"),
            ("Felina",      "3286"),
            ("Fiene",       "2679"),
            ("Fiene Marie", "9935"),
            ("Jeremy",      "2424"),
            ("Lauren",      "7912"),
            ("Liv",         "1520"),
            ("Lorenzo",     "1488"),
            ("Lou",         "2535"),
            ("Luuk",        "4582"),
            ("Magali",      "4811"),
            ("Nai",         "9279"),
            ("Reva",        "1434"),
            ("Thije",       "4257"),
        ]
        for naam, pin in leerlingen_met_pin:
            conn.execute("INSERT INTO leerlingen (naam, pin) VALUES (?, ?)", (naam, pin))
        conn.commit()
    conn.close()


def get_werkbladen():
    bestanden = sorted([
        f for f in os.listdir(WERKBLADEN_DIR)
        if f.lower().endswith(".pdf")
    ])
    lessen = []
    for f in bestanden:
        naam = os.path.splitext(f)[0]
        parts = naam.split(" ", 2)
        if len(parts) >= 3:
            titel = parts[2].strip()
        else:
            titel = naam
        lessen.append({"bestand": f, "titel": titel})
    return lessen


# ---------- Inloggen ----------

@app.route("/")
def index():
    if "leerling_id" in session:
        return redirect(url_for("dashboard"))
    conn = get_db()
    leerlingen = conn.execute("SELECT id, naam FROM leerlingen ORDER BY naam").fetchall()
    conn.close()
    return render_template("login.html", leerlingen=leerlingen)


@app.route("/inloggen", methods=["POST"])
def inloggen():
    leerling_id = request.form.get("leerling_id")
    pin = request.form.get("pin", "").strip()
    if not leerling_id:
        return redirect(url_for("index"))
    conn = get_db()
    leerling = conn.execute(
        "SELECT id, naam, pin FROM leerlingen WHERE id = ?", (leerling_id,)
    ).fetchone()
    conn.close()
    if not leerling:
        return redirect(url_for("index"))
    if leerling["pin"] and leerling["pin"] != pin:
        return render_template("login.html",
                               leerlingen=conn_leerlingen(),
                               fout="Verkeerde PIN. Probeer opnieuw.")
    session["leerling_id"] = leerling["id"]
    session["leerling_naam"] = leerling["naam"]
    return redirect(url_for("dashboard"))


def conn_leerlingen():
    conn = get_db()
    leerlingen = conn.execute("SELECT id, naam FROM leerlingen ORDER BY naam").fetchall()
    conn.close()
    return leerlingen


@app.route("/uitloggen")
def uitloggen():
    session.clear()
    return redirect(url_for("index"))


# ---------- Leerling dashboard ----------

@app.route("/dashboard")
def dashboard():
    if "leerling_id" not in session:
        return redirect(url_for("index"))
    lessen = get_werkbladen()
    conn = get_db()
    opgeslagen = conn.execute(
        "SELECT les_bestand, bijgewerkt_op FROM antwoorden WHERE leerling_id = ?",
        (session["leerling_id"],)
    ).fetchall()
    conn.close()
    opgeslagen_map = {r["les_bestand"]: r["bijgewerkt_op"] for r in opgeslagen}
    for les in lessen:
        les["opgeslagen"] = opgeslagen_map.get(les["bestand"])
    return render_template("dashboard.html", lessen=lessen,
                           naam=session["leerling_naam"])


@app.route("/les/<path:bestand>")
def les(bestand):
    if "leerling_id" not in session:
        return redirect(url_for("index"))
    veilig_pad = os.path.join(WERKBLADEN_DIR, os.path.basename(bestand))
    if not os.path.isfile(veilig_pad):
        abort(404)
    lessen = get_werkbladen()
    les_info = next((l for l in lessen if l["bestand"] == os.path.basename(bestand)), None)
    if not les_info:
        abort(404)
    conn = get_db()
    rij = conn.execute(
        "SELECT inhoud FROM antwoorden WHERE leerling_id = ? AND les_bestand = ?",
        (session["leerling_id"], os.path.basename(bestand))
    ).fetchone()
    conn.close()
    antwoorden = rij["inhoud"] if rij else ""
    return render_template("les.html", les=les_info, bestand=bestand,
                           antwoorden=antwoorden, naam=session["leerling_naam"])


@app.route("/opslaan/<path:bestand>", methods=["POST"])
def opslaan(bestand):
    if "leerling_id" not in session:
        return jsonify({"ok": False, "fout": "Niet ingelogd"}), 401
    inhoud = request.json.get("inhoud", "")
    nu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    conn.execute("""
        INSERT INTO antwoorden (leerling_id, les_bestand, inhoud, bijgewerkt_op)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(leerling_id, les_bestand)
        DO UPDATE SET inhoud = excluded.inhoud, bijgewerkt_op = excluded.bijgewerkt_op
    """, (session["leerling_id"], os.path.basename(bestand), inhoud, nu))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "tijd": nu})


@app.route("/werkblad/<path:bestand>")
def werkblad(bestand):
    if "leerling_id" not in session and not session.get("docent"):
        abort(403)
    return send_from_directory(WERKBLADEN_DIR, os.path.basename(bestand))


# ---------- Docent-overzicht ----------

@app.route("/docent", methods=["GET", "POST"])
def docent():
    if not session.get("docent"):
        if request.method == "POST":
            if request.form.get("wachtwoord") == DOCENT_WACHTWOORD:
                session["docent"] = True
                return redirect(url_for("docent"))
            else:
                return render_template("docent_login.html", fout="Verkeerd wachtwoord")
        return render_template("docent_login.html", fout=None)

    conn = get_db()
    leerlingen = conn.execute("SELECT id, naam, pin FROM leerlingen ORDER BY naam").fetchall()
    lessen = get_werkbladen()
    alle_antwoorden = conn.execute(
        "SELECT leerling_id, les_bestand, inhoud, bijgewerkt_op FROM antwoorden"
    ).fetchall()
    conn.close()

    antwoord_map = {}
    for a in alle_antwoorden:
        antwoord_map[(a["leerling_id"], a["les_bestand"])] = {
            "inhoud": a["inhoud"],
            "tijd": a["bijgewerkt_op"]
        }

    return render_template("docent.html", leerlingen=leerlingen, lessen=lessen,
                           antwoord_map=antwoord_map)


@app.route("/docent/leerling-opslaan", methods=["POST"])
def docent_leerling_opslaan():
    if not session.get("docent"):
        abort(403)
    data = request.json
    conn = get_db()
    actie = data.get("actie")
    if actie == "naam_wijzigen":
        conn.execute("UPDATE leerlingen SET naam = ? WHERE id = ?",
                     (data["naam"], data["id"]))
    elif actie == "pin_wijzigen":
        pin = data.get("pin", "").strip() or None
        conn.execute("UPDATE leerlingen SET pin = ? WHERE id = ?",
                     (pin, data["id"]))
    elif actie == "toevoegen":
        conn.execute("INSERT INTO leerlingen (naam, pin) VALUES (?, ?)",
                     (data["naam"], data.get("pin") or None))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/docent/antwoord/<int:leerling_id>/<path:bestand>")
def docent_antwoord(leerling_id, bestand):
    if not session.get("docent"):
        abort(403)
    conn = get_db()
    rij = conn.execute(
        "SELECT inhoud, bijgewerkt_op FROM antwoorden WHERE leerling_id = ? AND les_bestand = ?",
        (leerling_id, os.path.basename(bestand))
    ).fetchone()
    leerling = conn.execute("SELECT naam FROM leerlingen WHERE id = ?", (leerling_id,)).fetchone()
    conn.close()
    if not rij:
        return jsonify({"inhoud": "", "tijd": None, "naam": leerling["naam"] if leerling else "?"})
    return jsonify({"inhoud": rij["inhoud"], "tijd": rij["bijgewerkt_op"],
                    "naam": leerling["naam"] if leerling else "?"})


@app.route("/docent/uitloggen")
def docent_uitloggen():
    session.pop("docent", None)
    return redirect(url_for("docent"))


if __name__ == "__main__":
    init_db()
    print("\n=== Mentorlessen Portaal ===")
    print("Draait op: http://localhost:5000")
    print("Docent-pagina: http://localhost:5000/docent  (wachtwoord: docent123)")
    print("Druk op Ctrl+C om te stoppen\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
