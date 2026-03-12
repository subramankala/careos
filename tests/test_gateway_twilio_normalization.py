from careos.gateway.routes.twilio_gateway import _normalize_sender_phone


def test_normalize_sender_phone_recovers_plus_from_form_decoding() -> None:
    assert _normalize_sender_phone("whatsapp: 14085157095") == "whatsapp:+14085157095"
    assert _normalize_sender_phone("whatsapp:+14085157095") == "whatsapp:+14085157095"
    assert _normalize_sender_phone("whatsapp:14085157095") == "whatsapp:+14085157095"
