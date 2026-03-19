import json
from types import SimpleNamespace

from careos.domain.enums.core import PersonaType, Role, WinState
from careos.domain.models.api import CommandResult, ParticipantContext
from careos.conversation.openclaw_engine import OpenClawConversationEngine


def test_candidate_paths_include_compat_variants() -> None:
    engine = OpenClawConversationEngine(base_url="http://127.0.0.1:9999", fallback_path="/custom/fallback")
    paths = engine._candidate_paths()
    assert paths[0] == "/custom/fallback"
    assert "/v1/careos/fallback" in paths
    assert "/api/v1/careos/fallback" in paths


def test_extract_text_supports_multiple_response_shapes() -> None:
    text, action = OpenClawConversationEngine._extract_text({"text": "hello", "action": "openclaw_fallback"})
    assert text == "hello"
    assert action == "openclaw_fallback"

    text, _ = OpenClawConversationEngine._extract_text({"response": "hi"})
    assert text == "hi"

    text, _ = OpenClawConversationEngine._extract_text({"message": "yo"})
    assert text == "yo"

    text, _ = OpenClawConversationEngine._extract_text({"choices": [{"message": {"content": "from choices"}}]})
    assert text == "from choices"

    text, _ = OpenClawConversationEngine._extract_text(
        {"output": [{"content": [{"type": "output_text", "text": "from output"}]}]},
    )
    assert text == "from output"


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _FakeWinService:
    def today(self, patient_id: str, at=None):  # noqa: ANN001
        return SimpleNamespace(
            timeline=[
                SimpleNamespace(
                    title="Brilinta 90mg",
                    category="medication",
                    scheduled_start=SimpleNamespace(isoformat=lambda: "2026-03-19T08:00:00+00:00"),
                    current_state=WinState.PENDING,
                ),
                SimpleNamespace(
                    title="Pantoprazole 40mg",
                    category="medication",
                    scheduled_start=SimpleNamespace(isoformat=lambda: "2026-03-19T07:00:00+00:00"),
                    current_state=WinState.PENDING,
                ),
            ]
        )

    def prn_definitions(self, patient_id: str) -> list[dict[str, str]]:
        return [{"title": "Sorbitrate 5mg (SOS)", "instructions": "Use only if chest pain occurs"}]


def _context() -> ParticipantContext:
    return ParticipantContext(
        tenant_id="tenant-1",
        participant_id="participant-1",
        participant_role=Role.CAREGIVER,
        patient_id="patient-1",
        patient_timezone="UTC",
        patient_persona=PersonaType.CAREGIVER_MANAGED_ELDER,
    )


def test_handle_prefers_openresponses_and_includes_med_grounding(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout=0):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"text": "Grounded answer", "action": "openclaw_fallback"})

    monkeypatch.setattr("careos.conversation.openclaw_engine.urlopen", _fake_urlopen)
    engine = OpenClawConversationEngine(
        base_url="http://127.0.0.1:8115",
        responses_path="/v1/responses",
        gateway_token="token-1",
        win_service=_FakeWinService(),
    )

    result = engine.handle("Which of these are blood thinners?", _context())

    assert result == CommandResult(action="openclaw_fallback", text="Grounded answer")
    assert str(captured["url"]).endswith("/v1/responses")
    prompt = captured["payload"]["input"][0]["content"][0]["text"]  # type: ignore[index]
    assert "Brilinta 90mg" in prompt
    assert "Pantoprazole 40mg" in prompt
    assert "Sorbitrate 5mg (SOS)" in prompt
    assert "careos_get_medications" in prompt
    assert "blood thinners" in prompt


def test_handle_remote_payload_includes_grounding_and_tool_hints(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_remote(payload, context):  # noqa: ANN001
        captured["payload"] = payload
        return CommandResult(action="openclaw_fallback", text="Remote answer")

    engine = OpenClawConversationEngine(
        base_url="http://openclaw.example",
        gateway_token="",
        win_service=_FakeWinService(),
    )
    monkeypatch.setattr(engine, "_call_remote", _fake_remote)

    result = engine.handle("Categorize medicines by purpose.", _context())

    assert result == CommandResult(action="openclaw_fallback", text="Remote answer")
    payload = captured["payload"]  # type: ignore[assignment]
    assert payload["tool_hints"] == ["careos_get_medications", "careos_get_today", "careos_get_status"]
    assert payload["grounding"]["active_medications"]  # type: ignore[index]
    assert any(
        row["category"] == "blood thinner" for row in payload["grounding"]["medication_knowledge"]  # type: ignore[index]
    )
