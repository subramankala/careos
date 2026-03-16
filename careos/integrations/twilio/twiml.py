def message_response(text: str) -> str:
    safe = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'


def voice_response(text: str, *, voice: str = "alice", language: str = "en") -> str:
    from twilio.twiml.voice_response import Say, VoiceResponse

    response = VoiceResponse()
    response.append(Say(text, voice=voice, language=language))
    return str(response)
