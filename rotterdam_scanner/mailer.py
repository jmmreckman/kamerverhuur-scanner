from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import Config


def send_report(config: Config, subject: str, html_body: str, text_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.gmail_address
    msg["To"] = ", ".join(config.report_to)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port) as smtp:
        smtp.login(config.gmail_address, config.gmail_app_password)
        smtp.sendmail(config.gmail_address, config.report_to, msg.as_string())
