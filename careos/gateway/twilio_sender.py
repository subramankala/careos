from __future__ import annotations

from careos.integrations.twilio.sender import TwilioWhatsAppSender
from careos.settings import settings


def build_sender() -> TwilioWhatsAppSender | None:
    if not settings.twilio_account_sid or not settings.twilio_auth_token or not settings.twilio_whatsapp_number:
        return None
    return TwilioWhatsAppSender(
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_whatsapp_number,
    )
