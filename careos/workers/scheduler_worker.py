from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from careos.app_context import context
from careos.db.connection import get_connection
from careos.db.repositories.store import InMemoryStore, PostgresStore
from careos.domain.enums.core import PersonaType
from careos.domain.enums.core import WinState
from careos.integrations.twilio.sender import TwilioVoiceSender, TwilioWhatsAppSender
from careos.integrations.twilio.twiml import voice_response
from careos.logging import configure_logging, get_logger
from careos.settings import settings

configure_logging(settings.log_level)
logger = get_logger("scheduler_worker")


def _patient_ids() -> list[str]:
    raw = settings.scheduler_patient_ids or os.getenv("CAREOS_SCHEDULER_PATIENT_IDS", "")
    if raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    return context.store.list_schedulable_patients()


def _recipient_endpoints(patient_id: str) -> list[dict]:
    store = context.store
    if isinstance(store, InMemoryStore):
        endpoints: list[dict] = []
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
            endpoints.append(
                {
                    "participant_id": str(participant["id"]),
                    "phone_number": phone,
                    "role": str(participant.get("role", "")),
                    "link": store.get_caregiver_link(str(participant["id"]), patient_id) or {},
                }
            )
            seen.add(endpoint)
        return endpoints

    if isinstance(store, PostgresStore):
        sql = """
        SELECT p.id, p.phone_number, p.role, cpl.relationship, cpl.notification_policy, cpl.can_edit_plan
        FROM caregiver_patient_links cpl
        JOIN participants p ON p.id = cpl.caregiver_participant_id
        WHERE cpl.patient_id = %s
          AND p.active = true
        """
        with get_connection(store.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (patient_id,))
            rows = cur.fetchall()
            endpoints: list[dict] = []
            for row in rows:
                if not row[1]:
                    continue
                link = {
                    "caregiver_participant_id": str(row[0]),
                    "patient_id": patient_id,
                    "relationship": row[3],
                    "notification_policy": row[4] or {},
                    "can_edit_plan": bool(row[5]),
                }
                from careos.db.repositories.store import caregiver_link_metadata

                link.update(caregiver_link_metadata(link))
                endpoints.append(
                    {
                        "participant_id": str(row[0]),
                        "phone_number": str(row[1]),
                        "role": str(row[2]),
                        "link": link,
                    }
                )
            return endpoints

    return []


def _notification_channels(link: dict, notification_kind: str) -> set[str]:
    preferences = dict((link.get("link") or {}).get("notification_preferences") or {})
    mapping = {
        "due_reminders": "due_reminders",
        "critical_alerts": "critical_alerts",
        "daily_summary": "daily_summary",
        "low_adherence_alerts": "low_adherence_alerts",
    }
    key = mapping[notification_kind]
    preference = preferences.get(key, False)
    if isinstance(preference, bool):
        return {"whatsapp"} if preference else set()
    if isinstance(preference, str):
        raw_channel = preference
    elif isinstance(preference, dict):
        if not bool(preference.get("enabled", True)):
            return set()
        raw_channel = str(preference.get("channel", "whatsapp"))
    else:
        return set()
    normalized = raw_channel.strip().lower().replace("text", "whatsapp")
    if normalized in {"", "off", "disabled", "none"}:
        return set()
    if normalized in {"both", "voice_and_whatsapp", "whatsapp_and_voice"}:
        return {"whatsapp", "voice"}
    if normalized in {"whatsapp", "voice"}:
        return {normalized}
    return {"whatsapp"}


def _recipient_allows_notification(recipient: dict, notification_kind: str) -> bool:
    role = str(recipient.get("role", "")).strip().lower()
    if notification_kind == "due_reminders":
        return role in {"patient", "caregiver"}
    return role == "caregiver"


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


def _build_voice_sender() -> TwilioVoiceSender | None:
    if not settings.enable_scheduler_voice_calls:
        return None
    if not settings.twilio_account_sid or not settings.twilio_auth_token or not settings.voice_caller_id:
        logger.warning("scheduler_voice_disabled_missing_twilio_config")
        return None
    try:
        return TwilioVoiceSender(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.voice_caller_id,
        )
    except ValueError:
        logger.warning("scheduler_voice_disabled_invalid_twilio_config")
        return None


def _voice_body_for_notification(*, message_type: str, body: str, title: str | None = None, category: str | None = None) -> str:
    if message_type == "scheduled_reminder":
        if str(category or "").strip().lower() == "medication":
            label = str(title or "your medication").strip() or "your medication"
            return (
                "This is CareOS. It is time for "
                f"{label}. After taking it, reply Taken on WhatsApp. "
                "If you took multiple medicines, reply done all meds on WhatsApp."
            )
        label = str(title or "your task").strip() or "your task"
        return f"This is CareOS. Reminder: {label} is due now. Please confirm on WhatsApp once completed."
    if message_type == "critical_missed_status_alert":
        return f"This is CareOS. {body} Please check WhatsApp for details."
    return f"This is CareOS. {body}"


def _send_scheduler_message(
    *,
    tenant_id: str,
    patient_id: str,
    participant_id: str,
    phone_number: str,
    body: str,
    message_type: str,
    channel: str,
    correlation_id: str,
    idempotency_key: str,
    whatsapp_sender: TwilioWhatsAppSender | None,
    voice_sender: TwilioVoiceSender | None,
    extra_payload: dict | None = None,
) -> bool:
    inserted = context.store.log_message_event(
        tenant_id=tenant_id,
        patient_id=patient_id,
        participant_id=participant_id,
        direction="outbound",
        channel=channel,
        message_type=message_type,
        body=body,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        payload={
            "to": phone_number,
            "push_enabled": (whatsapp_sender if channel == "whatsapp" else voice_sender) is not None,
            **(extra_payload or {}),
        },
    )
    if not inserted:
        return False
    if channel == "whatsapp" and whatsapp_sender is not None:
        try:
            sid = whatsapp_sender.send_text(to_number=phone_number, body=body)
            logger.info(
                "scheduler_push_sent",
                patient_id=patient_id,
                participant_id=participant_id,
                message_type=message_type,
                channel=channel,
                twilio_message_sid=sid,
            )
        except Exception:
            logger.exception(
                "scheduler_push_failed",
                patient_id=patient_id,
                participant_id=participant_id,
                message_type=message_type,
                channel=channel,
            )
    if channel == "voice" and voice_sender is not None:
        try:
            sid = voice_sender.place_call(
                to_number=phone_number,
                twiml=voice_response(
                    body,
                    voice=settings.scheduler_voice_name,
                    language=settings.scheduler_voice_language,
                ),
            )
            logger.info(
                "scheduler_voice_sent",
                patient_id=patient_id,
                participant_id=participant_id,
                message_type=message_type,
                channel=channel,
                twilio_call_sid=sid,
            )
        except Exception:
            logger.exception(
                "scheduler_voice_failed",
                patient_id=patient_id,
                participant_id=participant_id,
                message_type=message_type,
                channel=channel,
            )
    return True


def _status_alerts(patient_id: str, evaluated_at: datetime, timeline: list) -> list[tuple[str, str, dict]]:
    if not settings.enable_scheduler_status_alerts:
        return []
    alerts: list[tuple[str, str, dict]] = []
    profile = context.store.get_patient_profile(patient_id) or {}
    timezone_name = str(profile.get("timezone") or settings.default_timezone)
    local_now = evaluated_at.astimezone(ZoneInfo(timezone_name))
    grace_minutes = max(int(settings.scheduler_critical_missed_grace_minutes), 0)
    critical_missed = [
        item
        for item in timeline
        if item.current_state == WinState.MISSED
        and item.criticality.value == "high"
        and (evaluated_at - item.scheduled_end).total_seconds() >= grace_minutes * 60
    ]
    if critical_missed:
        titles = [item.title for item in critical_missed[:5]]
        body = "Caregiver alert: critical wins missed today:\n" + "\n".join(f"- {title}" for title in titles)
        if len(critical_missed) > 5:
            body += f"\n- and {len(critical_missed) - 5} more"
        alerts.append(
            (
                "critical_missed_status_alert",
                body,
                {
                    "alert_kind": "critical_missed",
                    "missed_count": len(critical_missed),
                    "date": evaluated_at.date().isoformat(),
                },
            )
        )

    status_counts = context.store.status_counts(patient_id, evaluated_at)
    adherence = context.store.adherence_summary(patient_id, evaluated_at.date())
    score = float(adherence.get("score", 0.0))
    activity_count = sum(int(status_counts.get(key, 0)) for key in ("completed", "due", "missed", "skipped", "pending", "delayed"))
    if activity_count > 0 and score < float(settings.scheduler_low_adherence_threshold):
        body = (
            "Caregiver status alert: today's adherence is "
            f"{score:.1f}% (completed={int(status_counts.get('completed', 0))}, "
            f"due={int(status_counts.get('due', 0))}, missed={int(status_counts.get('missed', 0))}, "
            f"skipped={int(status_counts.get('skipped', 0))})."
        )
        alerts.append(
            (
                "low_adherence_status_alert",
                body,
                {
                    "alert_kind": "low_adherence",
                    "score": score,
                    "threshold": float(settings.scheduler_low_adherence_threshold),
                    "date": evaluated_at.date().isoformat(),
                },
            )
        )
    summary_hour = int(settings.scheduler_daily_summary_hour_local)
    if activity_count > 0 and local_now.hour >= summary_hour:
        body = (
            "Caregiver daily summary: "
            f"adherence={score:.1f}%, completed={int(status_counts.get('completed', 0))}, "
            f"due={int(status_counts.get('due', 0))}, missed={int(status_counts.get('missed', 0))}, "
            f"skipped={int(status_counts.get('skipped', 0))}."
        )
        alerts.append(
            (
                "daily_status_summary",
                body,
                {
                    "alert_kind": "daily_summary",
                    "score": score,
                    "date": local_now.date().isoformat(),
                    "local_hour": local_now.hour,
                },
            )
        )
    return alerts


def run_once(now: datetime | None = None) -> int:
    patients = _patient_ids()
    evaluated_at = now or datetime.now(UTC)
    whatsapp_sender = _build_sender()
    voice_sender = _build_voice_sender()
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
            event_policy = context.policy_engine.event_policy_flags(
                criticality=item.criticality,
                flexibility=item.flexibility,
            )
            normalized_policy = context.policy_engine.normalize_event_policy_flags(event_policy.as_payload())
            if 0 in decision.reminder_offsets_minutes:
                recipients = _recipient_endpoints(patient_id)
                if not recipients:
                    logger.warning("scheduler_no_recipients", patient_id=patient_id, win_instance_id=item.win_instance_id)
                    continue
                for recipient in recipients:
                    if not _recipient_allows_notification(recipient, "due_reminders"):
                        continue
                    channels = _notification_channels(recipient, "due_reminders")
                    if not channels:
                        continue
                    participant_id = str(recipient["participant_id"])
                    phone_number = str(recipient["phone_number"])
                    message_body = f"Reminder: {item.title} is due now. Reply 'Taken' once completed."
                    voice_body = _voice_body_for_notification(
                        message_type="scheduled_reminder",
                        body=message_body,
                        title=str(item.title),
                        category=str(item.category),
                    )
                    for channel in sorted(channels):
                        if channel == "voice" and voice_sender is None:
                            if whatsapp_sender is None:
                                continue
                            channel = "whatsapp"
                        if channel == "whatsapp" and decision.channel != "whatsapp" and voice_sender is not None:
                            continue
                        delivered = _send_scheduler_message(
                            tenant_id=tenant_id,
                            patient_id=patient_id,
                            participant_id=participant_id,
                            phone_number=phone_number,
                            body=voice_body if channel == "voice" else message_body,
                            message_type="scheduled_reminder",
                            channel=channel,
                            correlation_id=f"sched:{patient_id}:{item.win_instance_id}:{participant_id}:{channel}",
                            idempotency_key=(
                                f"sched:{item.win_instance_id}:{item.scheduled_start.isoformat()}:due_v1:{participant_id}:{channel}"
                            ),
                            whatsapp_sender=whatsapp_sender if channel == "whatsapp" else None,
                            voice_sender=voice_sender if channel == "voice" else None,
                            extra_payload={
                                "tone": decision.tone,
                                "event_policy": normalized_policy.as_payload(),
                                "win_instance_id": str(item.win_instance_id),
                                "title": str(item.title),
                                "scheduled_start": item.scheduled_start.isoformat(),
                                "category": str(item.category),
                            },
                        )
                        if delivered:
                            sent += 1
        recipients = _recipient_endpoints(patient_id)
        if recipients:
            for message_type, message_body, payload in _status_alerts(patient_id, evaluated_at, timeline):
                notification_kind = (
                    "critical_alerts"
                    if message_type == "critical_missed_status_alert"
                    else "daily_summary"
                    if message_type == "daily_status_summary"
                    else "low_adherence_alerts"
                )
                for recipient in recipients:
                    if not _recipient_allows_notification(recipient, notification_kind):
                        continue
                    channels = _notification_channels(recipient, notification_kind)
                    if not channels:
                        continue
                    participant_id = str(recipient["participant_id"])
                    phone_number = str(recipient["phone_number"])
                    voice_body = _voice_body_for_notification(
                        message_type=message_type,
                        body=message_body,
                    )
                    for channel in sorted(channels):
                        if channel == "voice" and voice_sender is None:
                            if whatsapp_sender is None:
                                continue
                            channel = "whatsapp"
                        delivered = _send_scheduler_message(
                            tenant_id=tenant_id,
                            patient_id=patient_id,
                            participant_id=participant_id,
                            phone_number=phone_number,
                            body=voice_body if channel == "voice" else message_body,
                            message_type=message_type,
                            channel=channel,
                            correlation_id=(
                                f"sched:{patient_id}:{message_type}:{evaluated_at.date().isoformat()}:{participant_id}:{channel}"
                            ),
                            idempotency_key=(
                                f"sched:{patient_id}:{message_type}:{evaluated_at.date().isoformat()}:{participant_id}:{channel}"
                            ),
                            whatsapp_sender=whatsapp_sender if channel == "whatsapp" else None,
                            voice_sender=voice_sender if channel == "voice" else None,
                            extra_payload=payload,
                        )
                        if delivered:
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
