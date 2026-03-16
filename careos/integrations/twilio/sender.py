from __future__ import annotations

from twilio.rest import Client


def _normalize_whatsapp_address(value: str) -> str:
    text = value.strip()
    if text.lower().startswith("whatsapp:"):
        return f"whatsapp:{text.split(':', 1)[1]}"
    return f"whatsapp:{text}"


def _normalize_phone_number(value: str) -> str:
    text = value.strip()
    if text.lower().startswith("whatsapp:"):
        return text.split(":", 1)[1]
    return text


class TwilioWhatsAppSender:
    def __init__(self, *, account_sid: str, auth_token: str, from_number: str) -> None:
        if not account_sid:
            raise ValueError("missing Twilio account sid")
        if not auth_token:
            raise ValueError("missing Twilio auth token")
        if not from_number:
            raise ValueError("missing Twilio WhatsApp sender number")
        self.client = Client(account_sid, auth_token)
        self.from_number = _normalize_whatsapp_address(from_number)

    def send_text(self, *, to_number: str, body: str) -> str:
        message = self.client.messages.create(
            from_=self.from_number,
            to=_normalize_whatsapp_address(to_number),
            body=body,
        )
        return str(message.sid)


class TwilioVoiceSender:
    def __init__(self, *, account_sid: str, auth_token: str, from_number: str) -> None:
        if not account_sid:
            raise ValueError("missing Twilio account sid")
        if not auth_token:
            raise ValueError("missing Twilio auth token")
        if not from_number:
            raise ValueError("missing Twilio voice caller id")
        self.client = Client(account_sid, auth_token)
        self.from_number = _normalize_phone_number(from_number)

    def place_call(self, *, to_number: str, twiml: str) -> str:
        call = self.client.calls.create(
            from_=self.from_number,
            to=_normalize_phone_number(to_number),
            twiml=twiml,
        )
        return str(call.sid)
