"""Standalone Gmail SMTP smoke test for PredictiX."""
import smtplib
from email.message import EmailMessage

# ── Fill in these four values ─────────────────────────────────────────
GMAIL_ADDRESS  = "neuromindspredictix@gmail.com"
APP_PASSWORD   = "zbvgirqvjzrwsuoc"               # 16 chars, no spaces
SEND_TO        = "tajmibhagya@gmail.com" # use your own first
FROM_NAME      = "PredictiX"
# ──────────────────────────────────────────────────────────────────────


def main() -> None:
    msg = EmailMessage()
    msg["Subject"] = "PredictiX SMTP smoke test"
    msg["From"] = f"{FROM_NAME} <{GMAIL_ADDRESS}>"
    msg["To"] = SEND_TO
    msg.set_content("If you see this, Gmail SMTP is working.")
    msg.add_alternative(
        "<h2 style='color:#14b8a6'>SMTP works ✓</h2>"
        "<p>If you see this, Gmail SMTP from PredictiX is wired up correctly.</p>",
        subtype="html",
    )

    print(f"Connecting to smtp.gmail.com:587 as {GMAIL_ADDRESS} ...")
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls()
        server.login(GMAIL_ADDRESS, APP_PASSWORD)
        server.send_message(msg)
    print(f"✓ Sent to {SEND_TO}")


if __name__ == "__main__":
    main()