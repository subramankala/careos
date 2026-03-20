import json

from careos.gateway.action_proposals import propose_structured_action
from careos.settings import settings


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_llm_action_payload_includes_patient_context_and_timeline(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout=0):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "create_task",
                                    "entity_type": "routine",
                                    "category": "routine",
                                    "title": "Extra hydration",
                                    "instructions": "Drink extra water today.",
                                    "start_offset_hours": 1,
                                    "end_offset_hours": 2,
                                    "criticality": "low",
                                    "flexibility": "flexible",
                                    "confidence": 0.9,
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("careos.gateway.action_proposals.urlopen", _fake_urlopen)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_model", "gpt-test")

    proposal = propose_structured_action(
        "Plan extra hydration today",
        {
            "tenant_id": "tenant-1",
            "participant_id": "participant-1",
            "patient_id": "patient-1",
            "patient_timezone": "UTC",
            "patient_context": {
                "clinical_facts": [{"fact_key": "recent_procedure", "summary": "Recent stent placement"}],
                "recent_observations": [{"observation_key": "sleep", "summary": "Slept 4 hours last night"}],
                "day_plans": [{"plan_key": "doctor_visit", "summary": "Doctor visit at 4 PM today"}],
            },
        },
        timeline=[
            {
                "win_instance_id": "walk-1",
                "title": "Morning Walk",
                "category": "routine",
                "scheduled_start": "2026-03-20T08:00:00+00:00",
                "scheduled_end": "2026-03-20T09:00:00+00:00",
                "current_state": "pending",
            }
        ],
    )

    assert proposal is not None
    payload = captured["payload"]  # type: ignore[assignment]
    user_payload = json.loads(payload["messages"][1]["content"])  # type: ignore[index]
    assert user_payload["patient_context"]["clinical_facts"][0]["fact_key"] == "recent_procedure"
    assert user_payload["patient_context"]["recent_observations"][0]["observation_key"] == "sleep"
    assert user_payload["patient_context"]["day_plans"][0]["plan_key"] == "doctor_visit"
    assert user_payload["timeline_preview"][0]["win_instance_id"] == "walk-1"
