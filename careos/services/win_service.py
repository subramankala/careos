from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from careos.db.repositories.store import Store
from careos.domain.enums.core import WinState
from careos.domain.models.api import AdherenceSummaryResponse, PatientStatusResponse, PatientTodayResponse


class WinService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def today(self, patient_id: str, at: datetime | None = None) -> PatientTodayResponse:
        now = at or datetime.now(UTC)
        self.store.ensure_recurrence_instances(patient_id, now)
        profile = self.store.get_patient_profile(patient_id) or {"timezone": "UTC"}
        timezone_name = str(profile.get("timezone", "UTC"))
        timezone = ZoneInfo(timezone_name)
        timeline = self.store.list_today(patient_id, now)
        return PatientTodayResponse(
            patient_id=patient_id,
            date=now.astimezone(timezone).date().isoformat(),
            timezone=timezone_name,
            timeline=timeline,
        )

    def day(self, patient_id: str, day_value: date) -> PatientTodayResponse:
        profile = self.store.get_patient_profile(patient_id) or {"timezone": "UTC"}
        timezone_name = str(profile.get("timezone", "UTC"))
        timezone = ZoneInfo(timezone_name)
        at = datetime.combine(day_value, time(12, 0), tzinfo=timezone).astimezone(UTC)
        return self.today(patient_id, at=at)

    def next_text(self, patient_id: str, at: datetime | None = None) -> str:
        now = at or datetime.now(UTC)
        self.store.ensure_recurrence_instances(patient_id, now)
        profile = self.store.get_patient_profile(patient_id) or {"timezone": "UTC"}
        timezone_name = str(profile.get("timezone", "UTC"))
        timezone = ZoneInfo(timezone_name)
        item = self.store.next_item(patient_id, now)
        if item is None:
            return "No pending wins. Everything due today is handled."
        local_time = item.scheduled_start.astimezone(timezone).strftime("%H:%M")
        return f"Next: {local_time} {item.title} [{item.current_state.value}]"

    def prn_definitions(self, patient_id: str) -> list[dict[str, str]]:
        return self.store.list_prn_definitions(patient_id)

    def status(self, patient_id: str, at: datetime | None = None) -> PatientStatusResponse:
        now = at or datetime.now(UTC)
        self.store.ensure_recurrence_instances(patient_id, now)
        counts = self.store.status_counts(patient_id, now)
        completed = counts.get(WinState.COMPLETED.value, 0)
        due = counts.get(WinState.DUE.value, 0)
        missed = counts.get(WinState.MISSED.value, 0)
        skipped = counts.get(WinState.SKIPPED.value, 0)
        total = max(sum(counts.values()), 1)
        score = round((completed / total) * 100, 1)
        return PatientStatusResponse(
            patient_id=patient_id,
            completed_count=completed,
            due_count=due,
            missed_count=missed,
            skipped_count=skipped,
            adherence_score=score,
        )

    def complete(self, win_instance_id: str, actor_id: str) -> None:
        self.store.mark_win(win_instance_id, actor_id, WinState.COMPLETED)

    def skip(self, win_instance_id: str, actor_id: str) -> None:
        self.store.mark_win(win_instance_id, actor_id, WinState.SKIPPED)

    def delay(self, win_instance_id: str, actor_id: str, minutes: int) -> None:
        self.store.mark_win(win_instance_id, actor_id, WinState.DELAYED, minutes=minutes)

    def escalate(self, win_instance_id: str, actor_id: str) -> None:
        self.store.mark_win(win_instance_id, actor_id, WinState.ESCALATED)

    def adherence_summary(self, patient_id: str, day: date | None = None) -> AdherenceSummaryResponse:
        target_day = day or datetime.now(UTC).date()
        data = self.store.adherence_summary(patient_id, target_day)
        return AdherenceSummaryResponse(
            patient_id=patient_id,
            date=target_day.isoformat(),
            score=data["score"],
            high_criticality_completion_rate=data["high_criticality_completion_rate"],
            all_completion_rate=data["all_completion_rate"],
        )
