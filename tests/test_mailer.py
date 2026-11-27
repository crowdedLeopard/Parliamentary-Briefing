import base64
import io
import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import mailer  # noqa: E402

ENV = {"MAIL_TO": "reader@example.org", "GRAPH_TENANT_ID": "t-1", "GRAPH_CLIENT_ID": "c-1",
       "MAIL_SENDER": "sender@example.org", "GRAPH_CLIENT_SECRET": "s", "SITE_URL": "https://site/"}


def test_graph_send(monkeypatch, capsys):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    calls = []

    def post(url, data, headers):
        calls.append((url, data))
        return {"access_token": "tok"} if "login.microsoftonline.com" in url else {}
    monkeypatch.setattr(mailer, "_post", post)
    assert mailer.main(["--edition", "2026-11-26"]) == 0
    assert "t-1/oauth2/v2.0/token" in calls[0][0]
    assert calls[1][0].endswith("/users/sender%40example.org/sendMail")
    msg = json.loads(calls[1][1])["message"]
    names = [a["name"] for a in msg["attachments"]]
    assert names == ["parliamentary-briefing-2026-11-26.html", "parliamentary-briefing-2026-11-26.json"]
    ed = json.loads(base64.b64decode(msg["attachments"][1]["contentBytes"]))
    assert ed["edition"] == "2026-11-26" and ed["links"]["html"] == "https://site/2026-11-26.html"
    out = capsys.readouterr().out
    assert "reader@" not in out and "sender@" not in out and "1 recipient" in out


def test_graph_failure_hides_addresses(monkeypatch, capsys):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)

    def post(url, data, headers):
        body = json.dumps({"error": {"code": "ErrorInvalidRecipients", "message": "reader@example.org is bad"}}).encode()
        raise urllib.error.HTTPError(url, 400, "bad", {}, io.BytesIO(body))
    monkeypatch.setattr(mailer, "_post", post)
    assert mailer.main(["--edition", "2026-11-26"]) == 1
    out = capsys.readouterr().out
    assert "ErrorInvalidRecipients" in out and "reader@" not in out


def test_not_configured(monkeypatch, capsys):
    for k in list(ENV) + ["SMTP_HOST"]:
        monkeypatch.delenv(k, raising=False)
    assert mailer.main(["--edition", "2026-11-26"]) == 0
    assert "Email not sent" in capsys.readouterr().out
