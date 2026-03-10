from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from careos.db.repositories.store import Store
from careos.domain.enums.core import WinState
from careos.domain.models.api import AdherenceSummaryResponse, PatientStatusResponse, PatientTodayResponse


class WinService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def today(self, patient_id: str, at: datetime | None = None) -> PatientTodayResponse:
        now = at or datetime.now(UTC)
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

    def next_text(self, patient_id: str, at: datetime | None = None) -> str:
        now = at or datetime.now(UTC)
        item = self.store.next_item(patient_id, now)
        if item is None:
            return "No pending wins. Everything due today is handled."
        return f"Next: {item.scheduled_start.strftime('%H:%M')} {item.title} [{item.current_state.value}]"

    def status(self, patient_id: str, at: datetime | None = None) -> PatientStatusResponse:
        now = at or datetime.now(UTC)
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
