"""Standalone Gmail SMTP smoke test for PredictiX.

Credentials are read from environment variables so nothing secret is committed.
Set them before running, e.g.:

    export SMTP_GMAIL_ADDRESS="you@gmail.com"
    export SMTP_APP_PASSWORD="your-16-char-app-password"
    export SMTP_SEND_TO="recipient@example.com"      # optional, defaults to sender
    python -m app.test_email
"""
import os
import smtplib
import sys
from email.message import EmailMessage

FROM_NAME = os.getenv("SMTP_FROM_NAME", "PredictiX")


def main() -> None:
    gmail_address = os.getenv("SMTP_GMAIL_ADDRESS") or os.getenv("SMTP_USERNAME")
    app_password = os.getenv("SMTP_APP_PASSWORD") or os.getenv("SMTP_PASSWORD")
    send_to = os.getenv("SMTP_SEND_TO") or gmail_address

    if not gmail_address or not app_password:
        sys.exit(
            "Missing SMTP credentials. Set SMTP_GMAIL_ADDRESS and "
            "SMTP_APP_PASSWORD (or SMTP_USERNAME / SMTP_PASSWORD) in the "
            "environment before running this smoke test."
        )

    msg = EmailMessage()
    msg["Subject"] = "PredictiX SMTP smoke test"
    msg["From"] = f"{FROM_NAME} <{gmail_address}>"
    msg["To"] = send_to
    msg.set_content("If you see this, Gmail SMTP is working.")
    msg.add_alternative(
        "<h2 style='color:#14b8a6'>SMTP works ✓</h2>"
        "<p>If you see this, Gmail SMTP from PredictiX is wired up correctly.</p>",
        subtype="html",
    )

    print(f"Connecting to smtp.gmail.com:587 as {gmail_address} ...")
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls()
        server.login(gmail_address, app_password)
        server.send_message(msg)
    print(f"✓ Sent to {send_to}")


if __name__ == "__main__":
    main()
