from datetime import UTC, datetime

from careos.gateway import action_planner
from careos.gateway.action_planner import plan_action_request
from careos.gateway.action_proposals import StructuredActionProposal


class _PlannerAdapter:
    def get_win_binding(self, win_instance_id: str) -> dict:
        bindings = {
            "walk-1": {
                "win_instance_id": "walk-1",
                "win_definition_id": "def-walk-1",
                "care_plan_id": "cp-1",
                "patient_id": "patient-1",
                "title": "Evening walk",
                "category": "routine",
                "instructions": "Walk.",
                "criticality": "low",
                "flexibility": "flexible",
                "recurrence_type": "one_off",
            },
            "med-1": {
                "win_instance_id": "med-1",
                "win_definition_id": "def-med-1",
                "care_plan_id": "cp-1",
                "patient_id": "patient-1",
                "title": "Ecosprin 75mg",
                "category": "medication",
                "instructions": "Take Ecosprin.",
                "criticality": "high",
                "flexibility": "rigid",
                "recurrence_type": "daily",
            },
        }
        return dict(bindings[win_instance_id])


def _context() -> dict:
    return {
        "tenant_id": "tenant-1",
        "participant_id": "participant-1",
        "participant_role": "caregiver",
        "patient_id": "patient-1",
        "patient_timezone": "Asia/Kolkata",
        "patient_persona": "caregiver_managed_elder",
    }


def test_planner_compiles_one_off_update_to_reschedule_strategy() -> None:
    timeline = [
        {
            "win_instance_id": "walk-1",
            "title": "Evening walk",
            "category": "routine",
            "criticality": "low",
            "flexibility": "flexible",
            "scheduled_start": "2026-03-14T12:30:00+00:00",
            "scheduled_end": "2026-03-14T15:30:00+00:00",
            "current_state": "pending",
        }
    ]
    plan = plan_action_request("Move my walk to tomorrow morning", _context(), timeline, _PlannerAdapter())
    assert plan is not None
    assert plan.execution_strategy == "reschedule_one_off_task"
    assert plan.execution_payload["win_instance_id"] == "walk-1"


def test_planner_compiles_recurring_update_to_override_strategy() -> None:
    timeline = [
        {
            "win_instance_id": "med-1",
            "title": "Ecosprin 75mg",
            "category": "medication",
            "criticality": "high",
            "flexibility": "rigid",
            "scheduled_start": "2026-03-14T08:30:00+00:00",
            "scheduled_end": "2026-03-14T09:00:00+00:00",
            "current_state": "pending",
        }
    ]
    plan = plan_action_request("Move my Ecosprin 75mg to evening", _context(), timeline, _PlannerAdapter())
    assert plan is not None
    assert plan.execution_strategy == "override_recurring_task"
    assert plan.execution_payload["win_instance_id"] == "med-1"


def test_planner_returns_clarify_for_ambiguous_target() -> None:
    timeline = [
        {
            "win_instance_id": "med-1",
            "title": "Ecosprin 75mg",
            "category": "medication",
            "criticality": "high",
            "flexibility": "rigid",
            "scheduled_start": "2026-03-14T08:30:00+00:00",
            "scheduled_end": "2026-03-14T09:00:00+00:00",
            "current_state": "pending",
        },
        {
            "win_instance_id": "med-2",
            "title": "Ecosprin 75mg",
            "category": "medication",
            "criticality": "high",
            "flexibility": "rigid",
            "scheduled_start": "2026-03-14T12:30:00+00:00",
            "scheduled_end": "2026-03-14T13:00:00+00:00",
            "current_state": "pending",
        },
    ]
    plan = plan_action_request("Move my Ecosprin 75mg to evening", _context(), timeline, _PlannerAdapter())
    assert plan is not None
    assert plan.execution_strategy == "clarify_target"
    assert "multiple matches" in plan.confirmation_text.lower()
    assert "8:30 am" in plan.confirmation_text.lower()
    assert "12:30 pm" in plan.confirmation_text.lower()
    assert "reply with the time or item number" in plan.confirmation_text.lower()


def test_planner_passes_patient_context_into_proposal_generation(monkeypatch) -> None:
    captured: dict = {}

    def _fake_propose(text: str, context: dict, timeline: list[dict] | None = None):  # noqa: ANN001
        captured["text"] = text
        captured["context"] = dict(context)
        captured["timeline"] = list(timeline or [])
        return StructuredActionProposal(
            action_type="create_task",
            entity_type="routine",
            category="routine",
            title="Extra hydration",
            instructions="Drink water in the afternoon.",
            patient_id="patient-1",
            tenant_id="tenant-1",
            actor_id="participant-1",
            start_at=datetime(2026, 3, 14, 9, 0, tzinfo=UTC),
            end_at=datetime(2026, 3, 14, 10, 0, tzinfo=UTC),
            criticality="low",
            flexibility="flexible",
            confirmation_text="ok",
        )

    monkeypatch.setattr(action_planner, "propose_structured_action", _fake_propose)

    context = _context()
    context["patient_context"] = {
        "clinical_facts": [{"fact_key": "recent_procedure", "summary": "Recent stent placement"}],
        "recent_observations": [{"observation_key": "sleep", "summary": "Slept 4 hours last night"}],
        "day_plans": [{"plan_key": "doctor_visit", "summary": "Doctor visit at 4 PM today"}],
    }
    timeline = []

    plan = plan_action_request("Plan extra hydration today", context, timeline, _PlannerAdapter())

    assert plan is not None
    assert captured["context"]["patient_context"]["clinical_facts"][0]["fact_key"] == "recent_procedure"
    assert captured["context"]["patient_context"]["recent_observations"][0]["observation_key"] == "sleep"
    assert captured["context"]["patient_context"]["day_plans"][0]["plan_key"] == "doctor_visit"
