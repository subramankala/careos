from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from careos.db.repositories.store import InMemoryStore
from careos.domain.enums.core import Criticality, Flexibility, WinState
from careos.domain.models.api import TimelineItem
from careos.workers import scheduler_worker


class _Policy:
    def decide(self, *, criticality, flexibility, persona):  # noqa: ANN001
        return SimpleNamespace(reminder_offsets_minutes=[0], channel="whatsapp", tone="firm_supportive")


class _Sender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send_text(self, *, to_number: str, body: str) -> str:
        self.calls.append((to_number, body))
        return "SM_TEST"


def test_scheduler_push_sends_once_and_is_idempotent(monkeypatch) -> None:
    store = InMemoryStore()
    patient_id = "patient-1"
    participant_id = "participant-1"
    store.participants[participant_id] = {
        "id": participant_id,
        "tenant_id": "tenant-1",
        "role": "caregiver",
        "display_name": "Caregiver",
        "phone_number": "whatsapp:+15550001111",
        "active": True,
    }
    store.links.append({"id": "link-1", "caregiver_participant_id": participant_id, "patient_id": patient_id})

    now = datetime.now(UTC).replace(second=0, microsecond=0)
    timeline = [
        TimelineItem(
            win_instance_id="win-1",
            title="Due med",
            category="medication",
            criticality=Criticality.HIGH,
            flexibility=Flexibility.RIGID,
            scheduled_start=now - timedelta(minutes=1),
            scheduled_end=now + timedelta(minutes=10),
            current_state=WinState.DUE,
        )
    ]

    monkeypatch.setattr(store, "get_patient_profile", lambda patient: {"tenant_id": "tenant-1", "persona_type": "caregiver_managed_elder"})
    monkeypatch.setattr(store, "ensure_recurrence_instances", lambda patient, ts: 0)
    monkeypatch.setattr(store, "list_today", lambda patient, ts: timeline)

    sender = _Sender()
    monkeypatch.setattr(scheduler_worker, "context", SimpleNamespace(store=store, policy_engine=_Policy()))
    monkeypatch.setattr(scheduler_worker, "_patient_ids", lambda: [patient_id])
    monkeypatch.setattr(scheduler_worker, "_build_sender", lambda: sender)

    first = scheduler_worker.run_once(now=now)
    second = scheduler_worker.run_once(now=now)

    assert first == 1
    assert second == 0
    assert len(sender.calls) == 1
    assert sender.calls[0][0] == "whatsapp:+15550001111"
