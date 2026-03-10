from __future__ import annotations

from fastapi import Request

from careos.settings import settings

try:
    from twilio.request_validator import RequestValidator
except Exception:  # pragma: no cover
    RequestValidator = None  # type: ignore[assignment]


def validate_signature(request: Request, form_data: dict[str, str]) -> bool:
    if not settings.validate_twilio_signature:
        return True
    if not settings.twilio_auth_token or RequestValidator is None:
        return False
    signature = request.headers.get("X-Twilio-Signature", "")
    validator = RequestValidator(settings.twilio_auth_token)
    return validator.validate(_public_url(request), form_data, signature)


def _public_url(request: Request) -> str:
    if settings.public_webhook_base_url:
        base = settings.public_webhook_base_url.rstrip("/")
        query = f"?{request.url.query}" if request.url.query else ""
        return f"{base}{request.url.path}{query}"
    return str(request.url)
