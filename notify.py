"""Text-only notices: the family group on Telegram, the caretaker by Vonage SMS.

  TELEGRAM_BOT_TOKEN + TELEGRAM_FAMILY_CHAT_ID           family group (text only, never a photo)
  VONAGE_API_KEY + VONAGE_API_SECRET + VONAGE_FROM + CARETAKER_PHONE   caretaker SMS (escalation, STOP alerts)

A channel whose env is missing is a DryRun: it logs what it would have sent and says so. Every send, live or not,
is appended to logs/governance.jsonl. Photos of the organizer go only to the caretaker, through trust.py.
"""
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).parent
LOG = HERE / "logs" / "governance.jsonl"
UA = {"User-Agent": "doseday/0.1"}


def log(event: str, **kw) -> dict:
    row = {"t": round(time.time(), 3), "event": event, **kw}
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


class DryRun:
    live = False

    def __init__(self, name: str):
        self.name = name

    def send(self, text: str):
        log("send", channel=self.name, live=False, text=text)


class FamilyTelegram:
    name, live = "family-telegram", True

    def __init__(self, token: str, chat_id: str, http=None):
        import requests
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = str(chat_id)
        self.http = http or requests.Session()
        self.http.headers.update(UA)

    def send(self, text: str):
        # sendMessage only: the family group is told what happened, it never sees the patient's pills
        body = self.http.post(self.url, data={"chat_id": self.chat_id, "text": text[:4096]}, timeout=20).json()
        if not body.get("ok"):
            raise RuntimeError(f"telegram sendMessage: {body.get('description')}")
        log("send", channel=self.name, live=True, text=text)


class VonageSMS:
    # Vonage trial accounts reach only numbers verified on the dashboard (inferred from their docs; confirm there)
    name, live = "vonage-sms", True
    URL = "https://rest.nexmo.com/sms/json"

    def __init__(self, key: str, secret: str, sender: str, to: str, http=None):
        import requests
        self.form = {"api_key": key, "api_secret": secret, "from": sender, "to": to}
        self.http = http or requests.Session()
        self.http.headers.update(UA)

    def send(self, text: str):
        body = self.http.post(self.URL, data={**self.form, "text": text[:640]}, timeout=20).json()
        msg = (body.get("messages") or [{}])[0]
        if msg.get("status") != "0":
            raise RuntimeError(f"vonage sms: {msg.get('error-text', 'no status')}")
        log("send", channel=self.name, live=True, text=text)


def family():
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_FAMILY_CHAT_ID")
    return FamilyTelegram(tok, chat) if tok and chat else DryRun("family-telegram")


def sms():
    keys = [os.environ.get(k) for k in ("VONAGE_API_KEY", "VONAGE_API_SECRET", "VONAGE_FROM", "CARETAKER_PHONE")]
    return VonageSMS(*keys) if all(keys) else DryRun("vonage-sms")


def safe_send(ch, text: str):
    """A failed notice is logged, never raised: it must not break a STOP or a decision."""
    try:
        ch.send(text)
    except Exception as e:
        log("send_failed", channel=ch.name, live=ch.live, text=text, error=f"{type(e).__name__}: {str(e)[:160]}")
