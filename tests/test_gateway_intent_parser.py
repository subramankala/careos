from careos.gateway.intent_parser import parse_intent
from careos.settings import settings


def _ctx() -> dict:
    return {
        "tenant_id": "tenant-1",
        "participant_id": "participant-1",
        "participant_role": "caregiver",
        "patient_id": "patient-1",
        "patient_timezone": "Asia/Kolkata",
        "patient_persona": "caregiver_managed_elder",
    }


def _today() -> dict:
    return {"patient_id": "patient-1", "date": "2026-03-12", "timezone": "Asia/Kolkata", "timeline": []}


def _status() -> dict:
    return {"completed_count": 2, "due_count": 1, "missed_count": 0, "skipped_count": 0, "adherence_score": 66.7}


def test_rule_parse_set_critical_only_today_when_llm_unset() -> None:
    previous_key = settings.openai_api_key
    settings.openai_api_key = ""
    try:
        parsed = parse_intent(
            "I did not sleep well today, only send critical reminders",
            context=_ctx(),
            today=_today(),
            status=_status(),
        )
        assert parsed.intent == "set_critical_only_today"
    finally:
        settings.openai_api_key = previous_key


def test_rule_parse_medication_count_when_llm_unset() -> None:
    previous_key = settings.openai_api_key
    settings.openai_api_key = ""
    try:
        parsed = parse_intent(
            "what is total count of meds I took today?",
            context=_ctx(),
            today=_today(),
            status=_status(),
        )
        assert parsed.intent == "med_count_today"
    finally:
        settings.openai_api_key = previous_key


def test_rule_parse_delay_item_when_llm_unset() -> None:
    previous_key = settings.openai_api_key
    settings.openai_api_key = ""
    try:
        parsed = parse_intent(
            "delay 2 30",
            context=_ctx(),
            today=_today(),
            status=_status(),
        )
        assert parsed.intent == "delay"
        assert parsed.args["item_no"] == 2
        assert parsed.args["minutes"] == 30
    finally:
        settings.openai_api_key = previous_key
