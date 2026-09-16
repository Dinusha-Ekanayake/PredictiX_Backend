"""SMTP email sender, works with Gmail, SendGrid, Brevo, or any SMTP relay."""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

log = logging.getLogger(__name__)


class EmailSendError(Exception):
    """Raised when an email cannot be sent."""


def _get_smtp_config() -> dict:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM_EMAIL")
    from_name = os.getenv("SMTP_FROM_NAME", "PredictiX")

    missing = [
        k for k, v in {
            "SMTP_HOST": host,
            "SMTP_USERNAME": username,
            "SMTP_PASSWORD": password,
            "SMTP_FROM_EMAIL": from_email,
        }.items() if not v
    ]
    if missing:
        raise EmailSendError(f"SMTP not configured. Missing env vars: {', '.join(missing)}")

    return {
        "host": host, "port": port, "username": username,
        "password": password, "from_email": from_email, "from_name": from_name,
    }


def send_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> None:
    """Send an email via SMTP. Raises EmailSendError on failure."""
    cfg = _get_smtp_config()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f'{cfg["from_name"]} <{cfg["from_email"]}>'
    msg["To"] = to_email
    if reply_to:
        msg["Reply-To"] = reply_to

    if plain_body is None:
        plain_body = "Please view this email in an HTML-capable client."
    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            server.starttls()
            server.login(cfg["username"], cfg["password"])
            server.send_message(msg)
        log.info("Email sent to %s — subject: %r", to_email, subject)
    except Exception as exc:
        log.exception("SMTP send failed for %s", to_email)
        raise EmailSendError(f"Failed to send email: {exc}") from exc