from careos.gateway.action_planner import plan_action_request


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
