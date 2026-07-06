"""Versturen van de rapportage via Gmail SMTP met een app-wachtwoord."""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import Config

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 465


def send_report(config: Config, subject: str, html_body: str, text_body: str) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config.gmail_address
    message["To"] = config.email_to
    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT) as server:
        server.login(config.gmail_address, config.gmail_app_password)
        server.sendmail(config.gmail_address, [config.email_to], message.as_string())
