"""Send Django mail through Brevo's HTTPS API.

Hosts such as Render's free tier block outbound SMTP ports, so Gmail SMTP
cannot connect there. Brevo accepts the same messages over port 443.
"""
import json
import logging
import urllib.error
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

API_URL = "https://api.brevo.com/v3/smtp/email"


def _address(value):
    name, email = parseaddr(value)
    return {"email": email, "name": name} if name else {"email": email}


class BrevoEmailBackend(BaseEmailBackend):
    def __init__(self, api_key=None, timeout=None, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.api_key = api_key or settings.BREVO_API_KEY
        self.timeout = timeout or getattr(settings, "EMAIL_TIMEOUT", 20)

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            try:
                if self._send(message):
                    sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
                logger.exception("Brevo could not send %r", message.subject)
        return sent

    def _send(self, message):
        recipients = message.to or []
        if not (recipients or message.cc or message.bcc):
            return False
        payload = {
            "sender": _address(message.from_email or settings.DEFAULT_FROM_EMAIL),
            "subject": message.subject,
            "textContent": message.body or " ",
        }
        if recipients:
            payload["to"] = [_address(value) for value in recipients]
        if message.cc:
            payload["cc"] = [_address(value) for value in message.cc]
        if message.bcc:
            payload["bcc"] = [_address(value) for value in message.bcc]
        if not recipients:
            payload["to"] = payload.pop("cc", None) or payload.pop("bcc")
        if message.reply_to:
            payload["replyTo"] = _address(message.reply_to[0])
        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                payload["htmlContent"] = content

        request = urllib.request.Request(
            API_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"api-key": self.api_key, "accept": "application/json", "content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                accepted = 200 <= response.status < 300
                if accepted:
                    try:
                        message_id = json.loads(response.read() or b"{}").get("messageId", "")
                    except ValueError:
                        message_id = ""
                    logger.info("Brevo accepted %r (messageId %s)", message.subject, message_id or "unknown")
                return accepted
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise RuntimeError(f"Brevo rejected the email ({error.code}): {detail}") from error
