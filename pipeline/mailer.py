"""Email one edition as attachments: the HTML report and the JSON from export.py.

Everything about the recipient and the mail account comes from environment variables, which the
workflow fills from repository secrets, so no address or credential is ever in the repo.
  MAIL_TO         recipient address (required; comma-separated for several)

Microsoft Graph (preferred: mail is sent from a mailbox in your own Microsoft 365 tenant):
  GRAPH_TENANT_ID     the tenant's ID
  GRAPH_CLIENT_ID     the Entra app registration's application (client) ID; the app needs the
                      Mail.Send application permission with admin consent, ideally limited to the
                      one sending mailbox (Exchange RBAC for Applications / application access policy)
  MAIL_SENDER         the mailbox the mail is sent from
  GRAPH_CLIENT_SECRET optional. Without it the run signs in with GitHub's OIDC token through a
                      federated credential on the app registration, so no password is stored anywhere.
SMTP (used only if the Graph settings are absent):
  SMTP_HOST       mail server (required for SMTP)
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
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import smtplib
import ssl
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _post(url: str, data: bytes, headers: dict) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return json.loads(body) if body else {}


def _graph_error(e: Exception) -> str:
    """Error class and, for Graph or Entra errors, only their code: never message text or addresses."""
    if isinstance(e, urllib.error.HTTPError):
        try:
            err = json.loads(e.read() or b"{}")
            code = (err.get("error") or {}).get("code") if isinstance(err.get("error"), dict) else err.get("error")
        except Exception:  # noqa: BLE001
            code = None
        return f"HTTP {e.code}" + (f" {code}" if code else "")
    return type(e).__name__


def graph_token(tenant: str, client: str) -> str:
    form = {"client_id": client, "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default"}
    if os.environ.get("GRAPH_CLIENT_SECRET"):
        form["client_secret"] = os.environ["GRAPH_CLIENT_SECRET"]
    else:  # GitHub OIDC -> Entra federated credential: nothing secret is stored
        url, tok = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"), os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        if not url or not tok:
            raise RuntimeError("no GRAPH_CLIENT_SECRET and no GitHub OIDC token (the job needs id-token: write)")
        req = urllib.request.Request(url + "&audience=api://AzureADTokenExchange", headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            form["client_assertion"] = json.loads(r.read())["value"]
        form["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    t = _post(f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token",
              urllib.parse.urlencode(form).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
    return t["access_token"]


def send_graph(edition: str, files: dict[str, tuple[bytes, str]], sender: str, to: list[str], site: str) -> None:
    nice = date.fromisoformat(edition).strftime("%A %-d %B %Y")
    token = graph_token(os.environ["GRAPH_TENANT_ID"].strip(), os.environ["GRAPH_CLIENT_ID"].strip())
    body = {"message": {
        "subject": f"Parliamentary briefing: {nice}",
        "body": {"contentType": "Text", "content": f"The daily parliamentary briefing for {nice} is attached as HTML and JSON."
                                                   f"\n\nOnline: {site}{edition}.html\n\nSent automatically by the briefing workflow."},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": name, "contentType": ctype,
                         "contentBytes": base64.b64encode(data).decode()} for name, (data, ctype) in files.items()]},
        "saveToSentItems": True}
    _post(f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail", json.dumps(body).encode(),
          {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})


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
    graph = all((os.environ.get(k) or "").strip() for k in ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "MAIL_SENDER"))
    if not to or not (graph or host):
        print("::notice title=Email not sent::Add MAIL_TO and the GRAPH_* / MAIL_SENDER (or SMTP_*) repository secrets to email each edition.")
        return 0
    report = ROOT / "reports" / f"{a.edition}.html"
    if not report.exists():
        print(f"::error title=Email not sent::reports/{a.edition}.html does not exist")
        return 1
    site = os.environ.get("SITE_URL") or ""
    if graph:
        import export
        files = {f"parliamentary-briefing-{a.edition}.html": (report.read_bytes(), "text/html")}
        ed = export.edition(ROOT, a.edition, site)
        if ed:
            files[f"parliamentary-briefing-{a.edition}.json"] = (export.dumps(ed).encode(), "application/json")
        try:
            send_graph(a.edition, files, os.environ["MAIL_SENDER"].strip(), to, site)
        except Exception as e:  # noqa: BLE001 - report only the error type/code (logs are public)
            print(f"::error title=Email not sent::Microsoft Graph: {_graph_error(e)} (details withheld to keep addresses private)")
            return 1
        print(f"Emailed the {a.edition} edition ({len(files)} attachments) to {len(to)} recipient(s) via Microsoft Graph.")
        return 0
    user, password = os.environ.get("SMTP_USERNAME") or "", os.environ.get("SMTP_PASSWORD") or ""
    sender = os.environ.get("MAIL_FROM") or user
    port = int(os.environ.get("SMTP_PORT") or 587)
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
