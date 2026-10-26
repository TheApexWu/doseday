"""Text-only notices: the family group on Telegram, the caretaker by Vonage SMS.

  TELEGRAM_BOT_TOKEN + TELEGRAM_FAMILY_CHAT_ID           family group (text only, never a photo)
  VONAGE_API_KEY + VONAGE_API_SECRET + VONAGE_FROM + CARETAKER_PHONE   caretaker SMS (escalation, STOP alerts)
  VONAGE_CHANNEL=whatsapp   the same notices over Vonage's Messages API sandbox instead of SMS (no US carrier
                            registration needed; the phone joins the sandbox first). VONAGE_FROM is then optional.

  python notify.py test     send one test notice to the caretaker and print whether it went out live

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


class VonageWhatsApp:
    """Vonage Messages API sandbox: free, allow-listed phones only, for demos. US SMS needs 10DLC registration."""
    name, live = "vonage-whatsapp", True
    URL = "https://messages-sandbox.nexmo.com/v1/messages"
    SANDBOX_FROM = "14157386102"  # Vonage's shared WhatsApp sandbox number; the dashboard's Sandbox page shows it

    def __init__(self, key: str, secret: str, sender: str, to: str, http=None):
        import requests
        self.auth, self.sender, self.to = (key, secret), sender or self.SANDBOX_FROM, to.lstrip("+")
        self.http = http or requests.Session()
        self.http.headers.update(UA)

    def send(self, text: str):
        r = self.http.post(self.URL, auth=self.auth, timeout=20, json={
            "from": self.sender, "to": self.to, "channel": "whatsapp", "message_type": "text", "text": text[:640]})
        if r.status_code != 202:
            raise RuntimeError(f"vonage whatsapp {r.status_code}: {r.text[:160]}")
        log("send", channel=self.name, live=True, text=text)


def family():
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_FAMILY_CHAT_ID")
    return FamilyTelegram(tok, chat) if tok and chat else DryRun("family-telegram")


def sms():
    key, secret, sender, to = (os.environ.get(k) for k in ("VONAGE_API_KEY", "VONAGE_API_SECRET", "VONAGE_FROM",
                                                            "CARETAKER_PHONE"))
    if os.environ.get("VONAGE_CHANNEL", "sms").lower() == "whatsapp":
        ch = VonageWhatsApp(key, secret, sender, to) if key and secret and to else DryRun("vonage-whatsapp")
    else:
        ch = VonageSMS(key, secret, sender, to) if key and secret and sender and to else DryRun("vonage-sms")
    tok, care = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CARETAKER_ID")
    if isinstance(ch, DryRun) and tok and care:
        # no Vonage account yet: the reminder goes to the caretaker's own Telegram chat instead of nowhere
        ch = FamilyTelegram(tok, care)
        ch.name = "caretaker-telegram"
    return ch


def safe_send(ch, text: str):
    """A failed notice is logged, never raised: it must not break a STOP or a decision."""
    try:
        ch.send(text)
    except Exception as e:
        log("send_failed", channel=ch.name, live=ch.live, text=text, error=f"{type(e).__name__}: {str(e)[:160]}")


if __name__ == "__main__":
    import sys

    import config
    config.load_dotenv()
    if sys.argv[1:] != ["test"]:
        raise SystemExit("usage: python notify.py test")
    ch = sms()
    ch.send(f"Doseday test notice at {time.strftime('%H:%M')}. If this reached your phone, the demo text will too.")
    print(f"{ch.name}: {'sent live' if ch.live else 'dry run only (Vonage keys missing from .env), nothing sent'}")
