from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from careos.app_context import context
from careos.db.connection import get_connection
from careos.db.repositories.store import InMemoryStore, PostgresStore
from careos.domain.enums.core import PersonaType
from careos.domain.enums.core import WinState
from careos.integrations.twilio.sender import TwilioWhatsAppSender
from careos.logging import configure_logging, get_logger
from careos.settings import settings

configure_logging(settings.log_level)
logger = get_logger("scheduler_worker")


def _patient_ids() -> list[str]:
    raw = settings.scheduler_patient_ids or os.getenv("CAREOS_SCHEDULER_PATIENT_IDS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _recipient_endpoints(patient_id: str) -> list[tuple[str, str]]:
    store = context.store
    if isinstance(store, InMemoryStore):
        endpoints: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for link in store.links:
            if str(link["patient_id"]) != str(patient_id):
                continue
            participant = store.participants.get(str(link["caregiver_participant_id"]))
            if not participant or not participant.get("active", False):
                continue
            phone = str(participant.get("phone_number", "")).strip()
            if not phone:
                continue
            endpoint = (str(participant["id"]), phone)
            if endpoint in seen:
                continue
            endpoints.append(endpoint)
            seen.add(endpoint)
        return endpoints

    if isinstance(store, PostgresStore):
        sql = """
        SELECT p.id, p.phone_number
        FROM caregiver_patient_links cpl
        JOIN participants p ON p.id = cpl.caregiver_participant_id
        WHERE cpl.patient_id = %s
          AND p.active = true
        """
        with get_connection(store.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (patient_id,))
            rows = cur.fetchall()
            return [(str(row[0]), str(row[1])) for row in rows if row[1]]

    return []


def _build_sender() -> TwilioWhatsAppSender | None:
    if not settings.enable_scheduler_whatsapp_push:
        return None
    if not settings.twilio_account_sid or not settings.twilio_auth_token or not settings.twilio_whatsapp_number:
        logger.warning("scheduler_push_disabled_missing_twilio_config")
        return None
    try:
        return TwilioWhatsAppSender(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_whatsapp_number,
        )
    except ValueError:
        logger.warning("scheduler_push_disabled_invalid_twilio_config")
        return None


def run_once(now: datetime | None = None) -> int:
    patients = _patient_ids()
    evaluated_at = now or datetime.now(UTC)
    sender = _build_sender()
    sent = 0
    for patient_id in patients:
        profile = context.store.get_patient_profile(patient_id) or {}
        tenant_id = str(profile.get("tenant_id", "unknown"))
        persona_raw = str(profile.get("persona_type", PersonaType.CAREGIVER_MANAGED_ELDER.value))
        persona = PersonaType(persona_raw) if persona_raw in {p.value for p in PersonaType} else PersonaType.CAREGIVER_MANAGED_ELDER
        context.store.ensure_recurrence_instances(patient_id, evaluated_at)
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
                recipients = _recipient_endpoints(patient_id)
                if not recipients:
                    logger.warning("scheduler_no_recipients", patient_id=patient_id, win_instance_id=item.win_instance_id)
                    continue
                for participant_id, phone_number in recipients:
                    message_body = f"Reminder: {item.title} is due now."
                    idempotency_key = (
                        f"sched:{item.win_instance_id}:{item.scheduled_start.isoformat()}:due_v1:{participant_id}"
                    )
                    inserted = context.store.log_message_event(
                        tenant_id=tenant_id,
                        patient_id=patient_id,
                        participant_id=participant_id,
                        direction="outbound",
                        channel=decision.channel,
                        message_type="scheduled_reminder",
                        body=message_body,
                        correlation_id=f"sched:{patient_id}:{item.win_instance_id}:{participant_id}",
                        idempotency_key=idempotency_key,
                        payload={"tone": decision.tone, "to": phone_number, "push_enabled": sender is not None},
                    )
                    if not inserted:
                        continue
                    if sender is not None and decision.channel == "whatsapp":
                        try:
                            sid = sender.send_text(to_number=phone_number, body=message_body)
                            logger.info(
                                "scheduler_push_sent",
                                patient_id=patient_id,
                                participant_id=participant_id,
                                win_instance_id=item.win_instance_id,
                                twilio_message_sid=sid,
                            )
                        except Exception:
                            logger.exception(
                                "scheduler_push_failed",
                                patient_id=patient_id,
                                participant_id=participant_id,
                                win_instance_id=item.win_instance_id,
                            )
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
