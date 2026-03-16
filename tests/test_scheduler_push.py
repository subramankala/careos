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

    def event_policy_flags(self, *, criticality, flexibility):  # noqa: ANN001
        return SimpleNamespace(as_payload=lambda: {"criticality": str(criticality), "flexibility": str(flexibility)})

    def normalize_event_policy_flags(self, payload):  # noqa: ANN001
        return SimpleNamespace(as_payload=lambda: dict(payload))


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

    assert first == 2
    assert second == 0
    assert len(sender.calls) == 2
    assert sender.calls[0][0] == "whatsapp:+15550001111"
    assert "reply 'taken' once completed" in sender.calls[0][1].lower()


def test_scheduler_sends_missed_critical_status_alert_once_per_day(monkeypatch) -> None:
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
            title="Critical med",
            category="medication",
            criticality=Criticality.HIGH,
            flexibility=Flexibility.RIGID,
            scheduled_start=now - timedelta(hours=2),
            scheduled_end=now - timedelta(hours=1, minutes=30),
            current_state=WinState.MISSED,
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

    assert first == 2
    assert second == 0
    assert any("critical wins missed today" in body.lower() for _, body in sender.calls)


def test_scheduler_sends_low_adherence_status_alert_once_per_day(monkeypatch) -> None:
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
            title="Routine",
            category="routine",
            criticality=Criticality.LOW,
            flexibility=Flexibility.FLEXIBLE,
            scheduled_start=now - timedelta(hours=1),
            scheduled_end=now - timedelta(minutes=30),
            current_state=WinState.MISSED,
        )
    ]

    monkeypatch.setattr(store, "get_patient_profile", lambda patient: {"tenant_id": "tenant-1", "persona_type": "caregiver_managed_elder"})
    monkeypatch.setattr(store, "ensure_recurrence_instances", lambda patient, ts: 0)
    monkeypatch.setattr(store, "list_today", lambda patient, ts: timeline)
    monkeypatch.setattr(store, "status_counts", lambda patient, ts: {"completed": 0, "due": 0, "missed": 1, "skipped": 0})
    monkeypatch.setattr(store, "adherence_summary", lambda patient, day: {"score": 0.0, "high_criticality_completion_rate": 0.0, "all_completion_rate": 0.0})

    sender = _Sender()
    monkeypatch.setattr(scheduler_worker, "context", SimpleNamespace(store=store, policy_engine=_Policy()))
    monkeypatch.setattr(scheduler_worker, "_patient_ids", lambda: [patient_id])
    monkeypatch.setattr(scheduler_worker, "_build_sender", lambda: sender)

    first = scheduler_worker.run_once(now=now)
    second = scheduler_worker.run_once(now=now)

    assert first == 1
    assert second == 0
    assert any("adherence is 0.0%" in body.lower() for _, body in sender.calls)


def test_scheduler_critical_missed_alert_respects_grace_period(monkeypatch) -> None:
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
            title="Critical med",
            category="medication",
            criticality=Criticality.HIGH,
            flexibility=Flexibility.RIGID,
            scheduled_start=now - timedelta(minutes=20),
            scheduled_end=now - timedelta(minutes=10),
            current_state=WinState.MISSED,
        )
    ]

    monkeypatch.setattr(store, "get_patient_profile", lambda patient: {"tenant_id": "tenant-1", "persona_type": "caregiver_managed_elder", "timezone": "UTC"})
    monkeypatch.setattr(store, "ensure_recurrence_instances", lambda patient, ts: 0)
    monkeypatch.setattr(store, "list_today", lambda patient, ts: timeline)
    monkeypatch.setattr(store, "status_counts", lambda patient, ts: {"completed": 0, "due": 0, "missed": 1, "skipped": 0})
    monkeypatch.setattr(store, "adherence_summary", lambda patient, day: {"score": 100.0, "high_criticality_completion_rate": 0.0, "all_completion_rate": 100.0})

    sender = _Sender()
    monkeypatch.setattr(scheduler_worker, "context", SimpleNamespace(store=store, policy_engine=_Policy()))
    monkeypatch.setattr(scheduler_worker, "_patient_ids", lambda: [patient_id])
    monkeypatch.setattr(scheduler_worker, "_build_sender", lambda: sender)
    monkeypatch.setattr(scheduler_worker.settings, "scheduler_critical_missed_grace_minutes", 30)

    sent = scheduler_worker.run_once(now=now)

    assert sent == 0
    assert sender.calls == []


def test_scheduler_sends_daily_summary_after_local_summary_hour(monkeypatch) -> None:
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

    now = datetime(2026, 3, 14, 15, 30, tzinfo=UTC)
    timeline = [
        TimelineItem(
            win_instance_id="win-1",
            title="Routine",
            category="routine",
            criticality=Criticality.LOW,
            flexibility=Flexibility.FLEXIBLE,
            scheduled_start=now - timedelta(hours=2),
            scheduled_end=now - timedelta(hours=1, minutes=30),
            current_state=WinState.COMPLETED,
        )
    ]

    monkeypatch.setattr(store, "get_patient_profile", lambda patient: {"tenant_id": "tenant-1", "persona_type": "caregiver_managed_elder", "timezone": "Asia/Kolkata"})
    monkeypatch.setattr(store, "ensure_recurrence_instances", lambda patient, ts: 0)
    monkeypatch.setattr(store, "list_today", lambda patient, ts: timeline)
    monkeypatch.setattr(store, "status_counts", lambda patient, ts: {"completed": 1, "due": 0, "missed": 0, "skipped": 0})
    monkeypatch.setattr(store, "adherence_summary", lambda patient, day: {"score": 100.0, "high_criticality_completion_rate": 100.0, "all_completion_rate": 100.0})

    sender = _Sender()
    monkeypatch.setattr(scheduler_worker, "context", SimpleNamespace(store=store, policy_engine=_Policy()))
    monkeypatch.setattr(scheduler_worker, "_patient_ids", lambda: [patient_id])
    monkeypatch.setattr(scheduler_worker, "_build_sender", lambda: sender)
    monkeypatch.setattr(scheduler_worker.settings, "scheduler_daily_summary_hour_local", 20)

    sent = scheduler_worker.run_once(now=now)

    assert sent == 1
    assert any("caregiver daily summary" in body.lower() for _, body in sender.calls)


def test_scheduler_discovers_schedulable_patients_from_store_when_env_override_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(scheduler_worker.settings, "scheduler_patient_ids", "")
    monkeypatch.setattr(scheduler_worker, "context", SimpleNamespace(store=SimpleNamespace(list_schedulable_patients=lambda: ["patient-a", "patient-b"])))
    discovered = scheduler_worker._patient_ids()
    assert discovered == ["patient-a", "patient-b"]


def test_scheduler_observer_does_not_receive_due_reminders(monkeypatch) -> None:
    store = InMemoryStore()
    patient_id = "patient-1"
    participant_id = "participant-1"
    store.participants[participant_id] = {
        "id": participant_id,
        "tenant_id": "tenant-1",
        "role": "caregiver",
        "display_name": "Observer",
        "phone_number": "whatsapp:+15550001111",
        "active": True,
    }
    store.link_caregiver(participant_id, patient_id, preset="observer")

    now = datetime(2026, 3, 14, 10, 0, tzinfo=UTC)
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

    monkeypatch.setattr(store, "get_patient_profile", lambda patient: {"tenant_id": "tenant-1", "persona_type": "caregiver_managed_elder", "timezone": "UTC"})
    monkeypatch.setattr(store, "ensure_recurrence_instances", lambda patient, ts: 0)
    monkeypatch.setattr(store, "list_today", lambda patient, ts: timeline)
    monkeypatch.setattr(store, "status_counts", lambda patient, ts: {"completed": 1, "due": 0, "missed": 0, "skipped": 0})
    monkeypatch.setattr(store, "adherence_summary", lambda patient, day: {"score": 100.0, "high_criticality_completion_rate": 100.0, "all_completion_rate": 100.0})
    monkeypatch.setattr(scheduler_worker.settings, "scheduler_daily_summary_hour_local", 23)

    sender = _Sender()
    monkeypatch.setattr(scheduler_worker, "context", SimpleNamespace(store=store, policy_engine=_Policy()))
    monkeypatch.setattr(scheduler_worker, "_patient_ids", lambda: [patient_id])
    monkeypatch.setattr(scheduler_worker, "_build_sender", lambda: sender)

    sent = scheduler_worker.run_once(now=now)

    assert sent == 0
    assert sender.calls == []
