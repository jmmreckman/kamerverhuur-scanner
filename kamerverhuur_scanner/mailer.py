"""Verstuurt e-mails (betaalherinnering / ingebrekestelling) via SMTP.

Vereist SMTP_HOST/SMTP_PORT/SMTP_USERNAME/SMTP_PASSWORD/SMTP_FROM_EMAIL in
.env (zie README) - zonder die instellingen geeft verstuur_email() een
duidelijke MailError in plaats van de app te laten crashen.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import Config


class MailError(RuntimeError):
    """SMTP niet (volledig) geconfigureerd, of versturen is mislukt."""


def verstuur_email(config: Config, aan: str, onderwerp: str, tekst: str) -> None:
    if not (config.smtp_host and config.smtp_username and config.smtp_password and config.smtp_from_email):
        raise MailError(
            "E-mail versturen is nog niet ingesteld - vul SMTP_HOST, SMTP_PORT, "
            "SMTP_USERNAME, SMTP_PASSWORD en SMTP_FROM_EMAIL in .env in (zie README)."
        )

    msg = EmailMessage()
    msg["Subject"] = onderwerp
    afzender = f"{config.smtp_from_naam} <{config.smtp_from_email}>" if config.smtp_from_naam else config.smtp_from_email
    msg["From"] = afzender
    msg["To"] = aan
    if config.email_bcc:
        msg["Bcc"] = ", ".join(config.email_bcc)
    msg.set_content(tekst)

    try:
        if config.smtp_port == 465:
            with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=20) as smtp:
                smtp.login(config.smtp_username, config.smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                smtp.login(config.smtp_username, config.smtp_password)
                smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Versturen via SMTP is mislukt: {exc}") from exc
