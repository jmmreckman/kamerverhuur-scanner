"""
Magister connector via de (unofficial) REST API.

Magister heeft geen officiële publieke API maar draait intern op een
gedocumenteerde REST API. Bestaande reverse-engineering projecten:
  - https://github.com/elisaado/magister.js
  - https://github.com/Luc-Mcgrady/Anki-Magister

Aanpak: session-based login → JSON endpoints ophalen.

Let op: Magister kan API-endpoints wijzigen. Test na school-updates.

Setup:
  Vul in config.py:
    MAGISTER_SCHOOL_URL = "https://rscollege.magister.net"
    MAGISTER_USERNAME   = "jouw.naam@rscollege.nl"
    MAGISTER_PASSWORD   = "jouwwachtwoord"
"""
import re
from datetime import datetime, timedelta
from pathlib import Path

import requests

from ..config import MAGISTER_PASSWORD, MAGISTER_SCHOOL_URL, MAGISTER_USERNAME
from ..database import (
    get_alle_leerlingen,
    get_connection,
    sla_communicatie_op,
    update_sync_log,
    voeg_tijdlijn_toe,
)

DOCS_DIR = Path(__file__).parent.parent / "data" / "magister_docs"


class MagisterClient:
    """Sessie-gebaseerde Magister API client."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MentorAssistent/1.0"})
        self.base = MAGISTER_SCHOOL_URL.rstrip("/")
        self._aangemeld = False

    def aanmelden(self):
        """Login bij Magister via de API."""
        # Stap 1: haal CSRF token op
        resp = self.session.get(f"{self.base}/api/sessie", timeout=15)

        # Stap 2: login
        resp = self.session.post(
            f"{self.base}/api/sessie",
            json={
                "gebruikersnaam": MAGISTER_USERNAME,
                "wachtwoord": MAGISTER_PASSWORD,
            },
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Magister login mislukt: {resp.status_code} {resp.text[:200]}")
        self._aangemeld = True
        print("Magister: ingelogd.")

    def _get(self, pad: str, **kwargs) -> dict | list:
        if not self._aangemeld:
            self.aanmelden()
        resp = self.session.get(f"{self.base}{pad}", timeout=20, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def get_account_info(self) -> dict:
        return self._get("/api/account?noCache=true")

    def get_leerlingen(self) -> list[dict]:
        """Haal mentorleerlingen op."""
        account = self.get_account_info()
        persoon_id = account.get("Persoon", {}).get("Id")
        if not persoon_id:
            raise RuntimeError("Kan persoon ID niet ophalen uit Magister account.")
        leerlingen = self._get(f"/api/personen/{persoon_id}/leerlingen")
        return leerlingen.get("Items", leerlingen) if isinstance(leerlingen, dict) else leerlingen

    def get_berichten(self, map_naam: str = "inbox", limiet: int = 20) -> list[dict]:
        """Haal berichten op uit Magister berichtencentrum."""
        berichten = self._get(f"/api/berichten?map={map_naam}&top={limiet}")
        return berichten.get("items", berichten) if isinstance(berichten, dict) else berichten

    def get_bericht_detail(self, bericht_id: int) -> dict:
        return self._get(f"/api/berichten/{bericht_id}")

    def get_studiewijzer_documenten(self, leerling_id: int) -> list[dict]:
        """Haal documenten/bijlagen op voor een leerling."""
        try:
            docs = self._get(f"/api/leerlingen/{leerling_id}/documenten?top=50")
            return docs.get("Items", docs) if isinstance(docs, dict) else docs
        except Exception:
            return []

    def get_absenties(self, leerling_id: int, dagen: int = 30) -> list[dict]:
        """Haal absenties op voor de afgelopen X dagen."""
        tot = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        van = (datetime.now() - timedelta(days=dagen)).strftime("%Y-%m-%dT%H:%M:%S")
        try:
            data = self._get(
                f"/api/leerlingen/{leerling_id}/absenties",
                params={"van": van, "tot": tot, "top": 100},
            )
            return data.get("Items", data) if isinstance(data, dict) else data
        except Exception:
            return []

    def download_document(self, document_url: str, pad: Path) -> bool:
        """Download een document naar lokaal pad."""
        try:
            resp = self.session.get(
                f"{self.base}{document_url}" if document_url.startswith("/") else document_url,
                timeout=30,
                stream=True,
            )
            resp.raise_for_status()
            pad.parent.mkdir(parents=True, exist_ok=True)
            pad.write_bytes(resp.content)
            return True
        except Exception as e:
            print(f"  ⚠ Download mislukt {document_url}: {e}")
            return False


# ── Sync functie ──────────────────────────────────────────────────────────────

def sync_magister():
    """
    Synchroniseer Magister data:
    - Nieuwe berichten uit berichtencentrum
    - Documenten per mentorleerling
    - Absenties per mentorleerling
    """
    print("Synchroniseren Magister...")
    try:
        client = MagisterClient()
        client.aanmelden()

        # 1. Berichten
        _sync_magister_berichten(client)

        # 2. Per mentorleerling: documenten en absenties
        _sync_leerling_data(client)

        update_sync_log("magister")
        print("  → Magister sync compleet.")

    except Exception as e:
        update_sync_log("magister", status="fout", foutmelding=str(e))
        print(f"  ⚠ Magister sync mislukt: {e}")
        raise


def _sync_magister_berichten(client: MagisterClient):
    """Sla nieuwe Magister berichten op in communicatie tabel."""
    berichten = client.get_berichten(limiet=30)
    nieuw = 0
    for bericht in berichten:
        bericht_id = bericht.get("Id") or bericht.get("id")
        if not bericht_id:
            continue

        # Haal detail op voor volledige inhoud
        try:
            detail = client.get_bericht_detail(bericht_id)
        except Exception:
            detail = bericht

        inhoud = detail.get("Tekst") or detail.get("tekst") or ""
        # Verwijder HTML
        inhoud = re.sub(r"<[^>]+>", " ", inhoud).strip()
        inhoud = re.sub(r"\s+", " ", inhoud)

        afzender = (
            detail.get("Afzender", {}) or {}
        )

        sla_communicatie_op({
            "bron": "magister",
            "extern_id": f"mag_{bericht_id}",
            "richting": "inkomend",
            "van_email": afzender.get("Naam") or afzender.get("naam"),
            "aan_email": "mentor",
            "onderwerp": detail.get("Onderwerp") or detail.get("onderwerp"),
            "inhoud": inhoud[:8000],
            "datum": detail.get("VerstuurdOp") or detail.get("verstuurdOp")
                     or datetime.now().isoformat(),
        })
        nieuw += 1

    print(f"  → {nieuw} Magister bericht(en) verwerkt.")


def _sync_leerling_data(client: MagisterClient):
    """Sync documenten en absenties per bekende mentorleerling."""
    conn = get_connection()
    leerlingen = conn.execute(
        "SELECT id, magister_id, voornaam, achternaam FROM leerlingen WHERE magister_id IS NOT NULL"
    ).fetchall()
    conn.close()

    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    for leerling in leerlingen:
        leerling_id = leerling["id"]
        magister_id = int(leerling["magister_id"])
        naam = f"{leerling['voornaam']} {leerling['achternaam']}"

        # Documenten
        try:
            docs = client.get_studiewijzer_documenten(magister_id)
            _verwerk_documenten(client, docs, leerling_id, naam)
        except Exception as e:
            print(f"  ⚠ Documenten {naam}: {e}")

        # Absenties
        try:
            absenties = client.get_absenties(magister_id)
            _verwerk_absenties(absenties, leerling_id, naam)
        except Exception as e:
            print(f"  ⚠ Absenties {naam}: {e}")


def _verwerk_documenten(client: MagisterClient, docs: list, leerling_id: int, naam: str):
    conn = get_connection()
    nieuw = 0
    for doc in docs:
        doc_id = doc.get("Id") or doc.get("id")
        bestandsnaam = doc.get("Naam") or doc.get("naam") or f"document_{doc_id}"
        if not bestandsnaam.lower().endswith(".pdf"):
            bestandsnaam += ".pdf"

        bestaand = conn.execute(
            "SELECT id FROM documenten WHERE leerling_id = ? AND bestandsnaam = ?",
            (leerling_id, bestandsnaam)
        ).fetchone()
        if bestaand:
            continue

        lokaal_pad = DOCS_DIR / str(leerling_id) / bestandsnaam
        download_url = doc.get("Url") or doc.get("url") or ""

        if download_url:
            client.download_document(download_url, lokaal_pad)

        conn.execute("""
            INSERT INTO documenten (leerling_id, bestandsnaam, lokaal_pad, bron, datum_document)
            VALUES (?, ?, ?, 'magister', ?)
        """, (
            leerling_id,
            bestandsnaam,
            str(lokaal_pad) if lokaal_pad.exists() else None,
            doc.get("Datum") or doc.get("datum"),
        ))
        nieuw += 1

    conn.commit()
    conn.close()
    if nieuw:
        print(f"  → {nieuw} nieuw(e) document(en) voor {naam}.")


def _verwerk_absenties(absenties: list, leerling_id: int, naam: str):
    if not absenties:
        return
    conn = get_connection()
    nieuw = 0
    for abs_ in absenties:
        abs_id = abs_.get("Id") or abs_.get("id")
        if not abs_id:
            continue
        bestaand = conn.execute(
            "SELECT id FROM tijdlijn WHERE leerling_id = ? AND type = 'absentie' AND beschrijving LIKE ?",
            (leerling_id, f"%{abs_id}%")
        ).fetchone()
        if bestaand:
            continue

        reden = abs_.get("Omschrijving") or abs_.get("omschrijving") or "onbekend"
        datum = abs_.get("Begin") or abs_.get("begin") or datetime.now().isoformat()

        conn.execute("""
            INSERT INTO tijdlijn (leerling_id, datum, type, titel, beschrijving, aangemaakt_door)
            VALUES (?, ?, 'absentie', ?, ?, 'systeem')
        """, (
            leerling_id,
            datum[:10],
            f"Absentie: {reden}",
            f"Magister absentie ID {abs_id}: {reden}",
        ))
        nieuw += 1

    conn.commit()
    conn.close()
    if nieuw:
        print(f"  → {nieuw} absentie(s) voor {naam} in tijdlijn.")
