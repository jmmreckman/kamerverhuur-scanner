from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import Config


def send_mail(config: Config, subject: str, html_body: str, text_body: str,
              recipients: list[str] | None = None) -> None:
    """Verstuurt een e-mail via de (optioneel eigen) SMTP-instellingen. Afzender is
    config.effective_from_header (bv. info@steenhub.nl als SMTP_FROM_EMAIL is gezet);
    ontvangers zijn standaard config.report_to."""
    to = recipients if recipients is not None else config.report_to

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.effective_from_header
    msg["To"] = ", ".join(to)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    username = config.effective_smtp_username
    password = config.effective_smtp_password
    from_email = config.effective_from_email

    # Poort 465 = impliciete TLS (SMTP_SSL); elke andere poort (587 is de gangbare)
    # gebruikt een platte verbinding die met STARTTLS wordt opgewaardeerd. Dit dekt
    # zowel Gmail (465) als de meeste overige providers/hostingpartijen (587) af.
    if config.smtp_port == 465:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port) as smtp:
            smtp.login(username, password)
            smtp.sendmail(from_email, to, msg.as_string())
    else:
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(from_email, to, msg.as_string())


def send_report(config: Config, subject: str, html_body: str, text_body: str,
                recipients: list[str] | None = None) -> None:
    send_mail(config, subject, html_body, text_body,
              recipients=recipients if recipients is not None else config.report_to)
