from __future__ import annotations

import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import Config

# Vast, "ingebakken" BCC-adres: ELKE uitgaande mail gaat stiekem ook hierheen, zodat
# alles wat verstuurd wordt meegelezen kan worden. Bewust als BCC (dus alleen in de
# SMTP-envelop, niet in de headers) zodat de zichtbare ontvanger dit niet ziet.
STILLE_BCC = "jmmreckman@gmail.com"


def send_mail(config: Config, subject: str, html_body: str, text_body: str,
              recipients: list[str] | None = None, stille_bcc: bool = True,
              attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    """Verstuurt een e-mail via de (optioneel eigen) SMTP-instellingen. Afzender is
    config.effective_from_header (bv. info@steenhub.nl als SMTP_FROM_EMAIL is gezet);
    ontvangers zijn standaard config.report_to. Elk bericht krijgt standaard een stille
    BCC naar STILLE_BCC mee (alleen in de envelop, niet in de headers). Zet
    stille_bcc=False voor functies waar de gebruiker zelf de ontvanger(s) kiest en er
    geen meeleeskopie gewenst is (bv. de handmatige concurrentie-scan).

    `attachments` is een lijst van (bestandsnaam, inhoud-bytes, subtype), bv.
    ("rapport.pdf", pdf_bytes, "pdf"). Zonder bijlagen is de opbouw identiek aan
    vroeger (een enkel multipart/alternative-bericht)."""
    to = recipients if recipients is not None else config.report_to

    # De tekst/html-varianten horen in een 'alternative'-deel; eventuele bijlagen
    # eromheen in een 'mixed'-deel. Zonder bijlagen blijft het bericht precies een
    # multipart/alternative (zodat bestaand gedrag ongewijzigd is).
    alternatief = MIMEMultipart("alternative")
    alternatief.attach(MIMEText(text_body, "plain", "utf-8"))
    alternatief.attach(MIMEText(html_body, "html", "utf-8"))

    if attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(alternatief)
        for bestandsnaam, inhoud, subtype in attachments:
            deel = MIMEBase("application", subtype)
            deel.set_payload(inhoud)
            encoders.encode_base64(deel)
            deel.add_header("Content-Disposition", "attachment", filename=bestandsnaam)
            msg.attach(deel)
    else:
        msg = alternatief

    msg["Subject"] = subject
    msg["From"] = config.effective_from_header
    msg["To"] = ", ".join(to)

    # Envelop-ontvangers = zichtbare ontvangers + (optioneel) het stille BCC-adres. Het
    # BCC-adres komt NIET in msg (geen "Bcc"-header), alleen in de sendmail-envelop,
    # zodat het echt verborgen blijft. Dedupe zodat wie al ontvanger is geen dubbele
    # mail krijgt.
    envelope_to = list(to)
    if stille_bcc and STILLE_BCC and STILLE_BCC not in envelope_to:
        envelope_to.append(STILLE_BCC)

    username = config.effective_smtp_username
    password = config.effective_smtp_password
    from_email = config.effective_from_email

    # Poort 465 = impliciete TLS (SMTP_SSL); elke andere poort (587 is de gangbare)
    # gebruikt een platte verbinding die met STARTTLS wordt opgewaardeerd. Dit dekt
    # zowel Gmail (465) als de meeste overige providers/hostingpartijen (587) af.
    if config.smtp_port == 465:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port) as smtp:
            smtp.login(username, password)
            smtp.sendmail(from_email, envelope_to, msg.as_string())
    else:
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(from_email, envelope_to, msg.as_string())


def send_report(config: Config, subject: str, html_body: str, text_body: str,
                recipients: list[str] | None = None) -> None:
    send_mail(config, subject, html_body, text_body,
              recipients=recipients if recipients is not None else config.report_to)
