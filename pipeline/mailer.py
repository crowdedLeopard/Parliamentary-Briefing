"""Email one edition's HTML report as an attachment.

Everything about the recipient and the mail account comes from environment variables, which the
workflow fills from repository secrets, so no address or credential is ever in the repo:
  MAIL_TO         recipient address (required; comma-separated for several)
  SMTP_HOST       mail server, e.g. smtp.gmail.com (required)
  SMTP_PORT       465 = SSL, anything else = STARTTLS (default 587)
  SMTP_USERNAME   login for the mail server
  SMTP_PASSWORD   password or app password
  MAIL_FROM       sender address (default: SMTP_USERNAME)
Privacy: no address is ever printed. The log says only how many recipients were sent to, and a
failure reports the error type without its text (which could quote an address). GitHub also masks
secret values in logs. Addresses appear only in the message headers themselves.
If MAIL_TO or SMTP_HOST is missing the script says so and exits 0, so the daily build never fails
because email is not set up.

Usage: python pipeline/mailer.py --edition YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build_message(edition: str, html: bytes, sender: str, to: list[str], site: str) -> EmailMessage:
    nice = date.fromisoformat(edition).strftime("%A %-d %B %Y")
    msg = EmailMessage()
    msg["Subject"] = f"Parliamentary briefing: {nice}"
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.set_content(
        f"The daily parliamentary briefing for {nice} is attached as HTML ({edition}.html).\n\n"
        f"Online: {site}{edition}.html\n\nSent automatically by the briefing workflow.\n")
    msg.add_attachment(html, maintype="text", subtype="html", filename=f"parliamentary-briefing-{edition}.html")
    return msg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edition", required=True)
    a = ap.parse_args(argv)
    date.fromisoformat(a.edition)  # reject anything that is not a date
    to = [x.strip() for x in (os.environ.get("MAIL_TO") or "").split(",") if x.strip()]
    host = (os.environ.get("SMTP_HOST") or "").strip()
    if not to or not host:
        print("::notice title=Email not sent::Add the MAIL_TO and SMTP_* repository secrets to email each edition.")
        return 0
    report = ROOT / "reports" / f"{a.edition}.html"
    if not report.exists():
        print(f"::error title=Email not sent::reports/{a.edition}.html does not exist")
        return 1
    user, password = os.environ.get("SMTP_USERNAME") or "", os.environ.get("SMTP_PASSWORD") or ""
    sender = os.environ.get("MAIL_FROM") or user
    port = int(os.environ.get("SMTP_PORT") or 587)
    site = os.environ.get("SITE_URL") or ""
    msg = build_message(a.edition, report.read_bytes(), sender, to, site)
    try:
        send(msg, host, port, user, password)
    except Exception as e:
        # Never print the exception text: SMTP errors can quote the recipient or sender address,
        # and this repo's Action logs are public. The error class is enough to diagnose.
        print(f"::error title=Email not sent::{type(e).__name__} while sending (details withheld to keep addresses private)")
        return 1
    print(f"Emailed the {a.edition} edition to {len(to)} recipient(s).")
    return 0


def send(msg: EmailMessage, host: str, port: int, user: str, password: str) -> None:
    ctx = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=60)
    else:
        server = smtplib.SMTP(host, port, timeout=60)
        server.starttls(context=ctx)
    with server:
        if user:
            server.login(user, password)
        server.send_message(msg)


if __name__ == "__main__":
    sys.exit(main())
