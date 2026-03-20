"""
PDF verwerker: extraheert tekst uit Magister documenten en andere PDF's.
Gebruikt pdfplumber (beste voor tekst-PDFs) met fallback naar pymupdf.
"""
from pathlib import Path

from ..database import get_connection


def extraheer_tekst(pdf_pad: Path) -> str:
    """Extraheer platte tekst uit een PDF bestand."""
    tekst = _probeer_pdfplumber(pdf_pad)
    if not tekst or len(tekst.strip()) < 50:
        tekst = _probeer_pymupdf(pdf_pad)
    return tekst or ""


def _probeer_pdfplumber(pdf_pad: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(pdf_pad) as pdf:
            paginas = []
            for pagina in pdf.pages:
                t = pagina.extract_text()
                if t:
                    paginas.append(t)
        return "\n\n".join(paginas)
    except ImportError:
        return ""
    except Exception as e:
        print(f"  pdfplumber fout bij {pdf_pad.name}: {e}")
        return ""


def _probeer_pymupdf(pdf_pad: Path) -> str:
    try:
        import fitz  # pymupdf
        doc = fitz.open(pdf_pad)
        paginas = [pagina.get_text() for pagina in doc]
        return "\n\n".join(paginas)
    except ImportError:
        return ""
    except Exception as e:
        print(f"  pymupdf fout bij {pdf_pad.name}: {e}")
        return ""


def verwerk_onverwerkte_pdfs():
    """
    Verwerk alle documenten zonder geëxtraheerde tekst.
    Slaat de tekst op in de database voor AI-verwerking.
    """
    conn = get_connection()
    docs = conn.execute("""
        SELECT id, bestandsnaam, lokaal_pad
        FROM documenten
        WHERE lokaal_pad IS NOT NULL
          AND (volledige_tekst IS NULL OR volledige_tekst = '')
    """).fetchall()
    conn.close()

    if not docs:
        return

    print(f"PDF verwerker: {len(docs)} document(en) te verwerken...")
    verwerkt = 0

    for doc in docs:
        pad = Path(doc["lokaal_pad"])
        if not pad.exists():
            continue

        tekst = extraheer_tekst(pad)
        if not tekst:
            continue

        conn = get_connection()
        conn.execute("""
            UPDATE documenten
            SET volledige_tekst = ?,
                bijgewerkt_op = datetime('now')
            WHERE id = ?
        """, (tekst[:50000], doc["id"]))  # max 50k tekens per doc
        conn.commit()
        conn.close()
        verwerkt += 1

    print(f"  → {verwerkt} PDF(s) geëxtraheerd.")
