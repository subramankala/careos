from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from careos.app_context import context
from careos.domain.enums.core import PersonaType
from careos.domain.enums.core import WinState
from careos.logging import configure_logging, get_logger
from careos.settings import settings

configure_logging(settings.log_level)
logger = get_logger("scheduler_worker")


def _patient_ids() -> list[str]:
    raw = settings.scheduler_patient_ids or os.getenv("CAREOS_SCHEDULER_PATIENT_IDS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def run_once(now: datetime | None = None) -> int:
    patients = _patient_ids()
    evaluated_at = now or datetime.now(UTC)
    sent = 0
    for patient_id in patients:
        profile = context.store.get_patient_profile(patient_id) or {}
        tenant_id = str(profile.get("tenant_id", "unknown"))
        persona_raw = str(profile.get("persona_type", PersonaType.CAREGIVER_MANAGED_ELDER.value))
        persona = PersonaType(persona_raw) if persona_raw in {p.value for p in PersonaType} else PersonaType.CAREGIVER_MANAGED_ELDER
        timeline = context.store.list_today(patient_id, evaluated_at)
        for item in timeline:
            if item.current_state != WinState.DUE:
                continue
            decision = context.policy_engine.decide(
                criticality=item.criticality,
                flexibility=item.flexibility,
                persona=persona,
            )
            if 0 in decision.reminder_offsets_minutes:
                inserted = context.store.log_message_event(
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                    participant_id=None,
                    direction="outbound",
                    channel=decision.channel,
                    message_type="scheduled_reminder",
                    body=f"Reminder: {item.title} is due now.",
                    correlation_id=f"sched:{patient_id}:{item.win_instance_id}",
                    idempotency_key=f"sched:{item.win_instance_id}:{item.scheduled_start.isoformat()}:due_v1",
                    payload={"tone": decision.tone},
                )
                if inserted:
                    sent += 1
    return sent


def run_forever(poll_seconds: int | None = None) -> None:
    patients = _patient_ids()
    interval = poll_seconds if poll_seconds is not None else settings.scheduler_poll_seconds
    logger.info("scheduler_started", patients=patients)
    while True:
        run_once()
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
