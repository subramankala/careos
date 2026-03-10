from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from careos.db.connection import get_connection
from careos.domain.enums.core import Criticality, Flexibility, PersonaType, Role, WinState
from careos.domain.models.api import (
    AddWinsRequest,
    CarePlanCreate,
    ParticipantContext,
    ParticipantCreate,
    PatientCreate,
    TenantCreate,
    TimelineItem,
)


@dataclass
class CarePlanPatch:
    status: str | None = None
    effective_end: datetime | None = None


class Store(ABC):
    @abstractmethod
    def create_tenant(self, payload: TenantCreate) -> dict:
        raise NotImplementedError

    @abstractmethod
    def create_patient(self, payload: PatientCreate) -> dict:
        raise NotImplementedError

    @abstractmethod
    def create_participant(self, payload: ParticipantCreate) -> dict:
        raise NotImplementedError

    @abstractmethod
    def link_caregiver(self, caregiver_participant_id: str, patient_id: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def create_care_plan(self, payload: CarePlanCreate) -> dict:
        raise NotImplementedError

    @abstractmethod
    def patch_care_plan(self, care_plan_id: str, patch: CarePlanPatch) -> dict:
        raise NotImplementedError

    @abstractmethod
    def add_wins(self, care_plan_id: str, payload: AddWinsRequest) -> dict:
        raise NotImplementedError

    @abstractmethod
    def resolve_participant_context(self, phone_number: str) -> ParticipantContext | None:
        raise NotImplementedError

    @abstractmethod
    def get_patient_profile(self, patient_id: str) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    def list_today(self, patient_id: str, now: datetime) -> list[TimelineItem]:
        raise NotImplementedError

    @abstractmethod
    def next_item(self, patient_id: str, now: datetime) -> TimelineItem | None:
        raise NotImplementedError

    @abstractmethod
    def mark_win(self, win_instance_id: str, actor_id: str, state: WinState, minutes: int = 0) -> TimelineItem | None:
        raise NotImplementedError

    @abstractmethod
    def status_counts(self, patient_id: str, now: datetime) -> dict[str, int]:
        raise NotImplementedError

    @abstractmethod
    def adherence_summary(self, patient_id: str, day: date) -> dict[str, float]:
        raise NotImplementedError

    @abstractmethod
    def log_message_event(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        participant_id: str | None,
        direction: str,
        channel: str,
        message_type: str,
        body: str,
        correlation_id: str,
        idempotency_key: str,
        payload: dict,
    ) -> bool:
        raise NotImplementedError


class InMemoryStore(Store):
    def __init__(self) -> None:
        self.tenants: dict[str, dict] = {}
        self.patients: dict[str, dict] = {}
        self.participants: dict[str, dict] = {}
        self.links: list[dict] = []
        self.care_plans: dict[str, dict] = {}
        self.win_definitions: dict[str, dict] = {}
        self.win_instances: dict[str, dict] = {}
        self.win_to_title: dict[str, str] = {}
        self.win_to_category: dict[str, str] = {}
        self.win_to_criticality: dict[str, Criticality] = {}
        self.win_to_flexibility: dict[str, Flexibility] = {}
        self.win_to_temporary_start: dict[str, datetime | None] = {}
        self.win_to_temporary_end: dict[str, datetime | None] = {}
        self.message_idempotency: set[str] = set()
        self.default_patient_for_participant: dict[str, str] = {}

    def create_patient(self, payload: PatientCreate) -> dict:
        patient_id = str(uuid4())
        row = payload.model_dump()
        row["id"] = patient_id
        self.patients[patient_id] = row
        return row

    def create_tenant(self, payload: TenantCreate) -> dict:
        tenant_id = str(uuid4())
        row = payload.model_dump()
        row["id"] = tenant_id
        self.tenants[tenant_id] = row
        return row

    def create_participant(self, payload: ParticipantCreate) -> dict:
        pid = str(uuid4())
        row = payload.model_dump()
        row["id"] = pid
        self.participants[pid] = row
        return row

    def link_caregiver(self, caregiver_participant_id: str, patient_id: str) -> dict:
        link = {
            "id": str(uuid4()),
            "caregiver_participant_id": caregiver_participant_id,
            "patient_id": patient_id,
        }
        self.links.append(link)
        self.default_patient_for_participant[caregiver_participant_id] = patient_id
        return link

    def create_care_plan(self, payload: CarePlanCreate) -> dict:
        cid = str(uuid4())
        row = payload.model_dump()
        row["id"] = cid
        self.care_plans[cid] = row
        return row

    def patch_care_plan(self, care_plan_id: str, patch: CarePlanPatch) -> dict:
        row = self.care_plans[care_plan_id]
        if patch.status is not None:
            row["status"] = patch.status
        if patch.effective_end is not None:
            row["effective_end"] = patch.effective_end
        return row

    def add_wins(self, care_plan_id: str, payload: AddWinsRequest) -> dict:
        created = 0
        for definition in payload.definitions:
            definition_id = str(uuid4())
            self.win_definitions[definition_id] = {
                "id": definition_id,
                "care_plan_id": care_plan_id,
                **definition.model_dump(),
            }
            for instance in payload.instances:
                win_id = str(uuid4())
                self.win_instances[win_id] = {
                    "id": win_id,
                    "patient_id": payload.patient_id,
                    "win_definition_id": definition_id,
                    "scheduled_start": instance.scheduled_start,
                    "scheduled_end": instance.scheduled_end,
                    "current_state": WinState.PENDING,
                }
                self.win_to_title[win_id] = definition.title
                self.win_to_category[win_id] = definition.category
                self.win_to_criticality[win_id] = definition.criticality
                self.win_to_flexibility[win_id] = definition.flexibility
                self.win_to_temporary_start[win_id] = definition.temporary_start
                self.win_to_temporary_end[win_id] = definition.temporary_end
                created += 1
        return {"created": created}

    def resolve_participant_context(self, phone_number: str) -> ParticipantContext | None:
        normalized = _normalize_phone(phone_number)
        participant = next(
            (p for p in self.participants.values() if _normalize_phone(p["phone_number"]) == normalized and p["active"]),
            None,
        )
        if participant is None:
            return None

        linked_patient_ids = sorted(
            {
                str(link["patient_id"])
                for link in self.links
                if str(link["caregiver_participant_id"]) == str(participant["id"])
            }
        )
        if len(linked_patient_ids) != 1:
            return None
        patient_id = linked_patient_ids[0]

        patient = self.patients[patient_id]
        return ParticipantContext(
            tenant_id=participant["tenant_id"],
            participant_id=participant["id"],
            participant_role=participant["role"],
            patient_id=patient_id,
            patient_timezone=patient["timezone"],
            patient_persona=patient["persona_type"],
        )

    def get_patient_profile(self, patient_id: str) -> dict | None:
        patient = self.patients.get(patient_id)
        if patient is None:
            return None
        return {
            "patient_id": str(patient_id),
            "tenant_id": str(patient["tenant_id"]),
            "timezone": str(patient.get("timezone", "UTC") or "UTC"),
            "persona_type": str(patient.get("persona_type", PersonaType.CAREGIVER_MANAGED_ELDER.value)),
        }

    def list_today(self, patient_id: str, now: datetime) -> list[TimelineItem]:
        profile = self.get_patient_profile(patient_id)
        timezone = ZoneInfo(profile["timezone"]) if profile else ZoneInfo("UTC")
        now_utc = _ensure_utc(now)
        day = now_utc.astimezone(timezone).date()
        rows: list[TimelineItem] = []
        for win in self.win_instances.values():
            if win["patient_id"] != patient_id:
                continue
            start = _ensure_dt(win["scheduled_start"])
            end = _ensure_dt(win["scheduled_end"])
            current_state = win["current_state"]
            if current_state == WinState.SUPERSEDED:
                continue
            if start.astimezone(timezone).date() != day:
                continue
            temp_start = self.win_to_temporary_start.get(str(win["id"]))
            temp_end = self.win_to_temporary_end.get(str(win["id"]))
            if temp_start is not None and start < _ensure_dt(temp_start):
                continue
            if temp_end is not None and start > _ensure_dt(temp_end):
                continue
            state = _derived_state(current_state, start, end, now_utc)
            rows.append(
                TimelineItem(
                    win_instance_id=win["id"],
                    title=self.win_to_title[win["id"]],
                    category=self.win_to_category[win["id"]],
                    criticality=self.win_to_criticality[win["id"]],
                    flexibility=self.win_to_flexibility[win["id"]],
                    scheduled_start=start,
                    scheduled_end=end,
                    current_state=state,
                )
            )
        return sorted(rows, key=lambda item: item.scheduled_start)

    def next_item(self, patient_id: str, now: datetime) -> TimelineItem | None:
        for item in self.list_today(patient_id, now):
            if item.current_state in {WinState.PENDING, WinState.DUE, WinState.DELAYED}:
                return item
        return None

    def mark_win(self, win_instance_id: str, actor_id: str, state: WinState, minutes: int = 0) -> TimelineItem | None:
        win = self.win_instances.get(win_instance_id)
        if win is None:
            return None
        if state == WinState.DELAYED and minutes > 0:
            win["scheduled_start"] = _ensure_dt(win["scheduled_start"]) + timedelta(minutes=minutes)
            win["scheduled_end"] = _ensure_dt(win["scheduled_end"]) + timedelta(minutes=minutes)
        win["current_state"] = state
        items = self.list_today(win["patient_id"], datetime.now(UTC))
        return next((item for item in items if item.win_instance_id == win_instance_id), None)

    def status_counts(self, patient_id: str, now: datetime) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for item in self.list_today(patient_id, now):
            counts[item.current_state.value] += 1
        return dict(counts)

    def adherence_summary(self, patient_id: str, day: date) -> dict[str, float]:
        now = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        items = self.list_today(patient_id, now)
        total = max(len(items), 1)
        complete = len([item for item in items if item.current_state == WinState.COMPLETED])
        high = [item for item in items if item.criticality == Criticality.HIGH]
        high_done = len([item for item in high if item.current_state == WinState.COMPLETED])
        high_total = max(len(high), 1)
        return {
            "score": round((complete / total) * 100, 1),
            "high_criticality_completion_rate": round((high_done / high_total) * 100, 1),
            "all_completion_rate": round((complete / total) * 100, 1),
        }

    def log_message_event(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        participant_id: str | None,
        direction: str,
        channel: str,
        message_type: str,
        body: str,
        correlation_id: str,
        idempotency_key: str,
        payload: dict,
    ) -> bool:
        if idempotency_key in self.message_idempotency:
            return False
        self.message_idempotency.add(idempotency_key)
        return True


class PostgresStore(Store):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def create_patient(self, payload: PatientCreate) -> dict:
        sql = """
        INSERT INTO patients (tenant_id, display_name, timezone, primary_language, persona_type, risk_level, status)
        VALUES (%(tenant_id)s, %(display_name)s, %(timezone)s, %(primary_language)s, %(persona_type)s, %(risk_level)s, %(status)s)
        RETURNING id, tenant_id, display_name, timezone, primary_language, persona_type, risk_level, status
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, payload.model_dump(mode="json"))
            row = cur.fetchone()
            return _row_dict(cur, row)

    def create_tenant(self, payload: TenantCreate) -> dict:
        sql = """
        INSERT INTO tenants (name, type, timezone, status)
        VALUES (%(name)s, %(type)s, %(timezone)s, %(status)s)
        RETURNING id, name, type, timezone, status
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, payload.model_dump(mode="json"))
            return _row_dict(cur, cur.fetchone())

    def create_participant(self, payload: ParticipantCreate) -> dict:
        sql = """
        INSERT INTO participants (tenant_id, role, display_name, phone_number, preferred_channel, preferred_language, active)
        VALUES (%(tenant_id)s, %(role)s, %(display_name)s, %(phone_number)s, %(preferred_channel)s, %(preferred_language)s, %(active)s)
        RETURNING id, tenant_id, role, display_name, phone_number, preferred_channel, preferred_language, active
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, payload.model_dump(mode="json"))
            return _row_dict(cur, cur.fetchone())

    def link_caregiver(self, caregiver_participant_id: str, patient_id: str) -> dict:
        sql = """
        INSERT INTO caregiver_patient_links (caregiver_participant_id, patient_id)
        VALUES (%(caregiver_participant_id)s, %(patient_id)s)
        RETURNING id, caregiver_participant_id, patient_id
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, {"caregiver_participant_id": caregiver_participant_id, "patient_id": patient_id})
            return _row_dict(cur, cur.fetchone())

    def create_care_plan(self, payload: CarePlanCreate) -> dict:
        sql = """
        INSERT INTO care_plans (patient_id, created_by_participant_id, status, version, effective_start, effective_end, source_type)
        VALUES (%(patient_id)s, %(created_by_participant_id)s, %(status)s, %(version)s, %(effective_start)s, %(effective_end)s, %(source_type)s)
        RETURNING id, patient_id, created_by_participant_id, status, version, effective_start, effective_end, source_type
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, payload.model_dump(mode="json"))
            return _row_dict(cur, cur.fetchone())

    def patch_care_plan(self, care_plan_id: str, patch: CarePlanPatch) -> dict:
        sql = """
        UPDATE care_plans
        SET status = COALESCE(%(status)s, status),
            effective_end = COALESCE(%(effective_end)s, effective_end),
            updated_at = now()
        WHERE id = %(care_plan_id)s
        RETURNING id, patient_id, status, version, effective_start, effective_end
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, {"status": patch.status, "effective_end": patch.effective_end, "care_plan_id": care_plan_id})
            return _row_dict(cur, cur.fetchone())

    def add_wins(self, care_plan_id: str, payload: AddWinsRequest) -> dict:
        created = 0
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            for definition in payload.definitions:
                cur.execute(
                    """
                    INSERT INTO win_definitions
                    (care_plan_id, category, title, instructions, why_it_matters, criticality, flexibility, temporary_start, temporary_end, default_channel_policy, escalation_policy)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        care_plan_id,
                        definition.category,
                        definition.title,
                        definition.instructions,
                        definition.why_it_matters,
                        definition.criticality.value,
                        definition.flexibility.value,
                        definition.temporary_start,
                        definition.temporary_end,
                        json.dumps(definition.default_channel_policy),
                        json.dumps(definition.escalation_policy),
                    ),
                )
                definition_id = cur.fetchone()[0]
                for instance in payload.instances:
                    cur.execute(
                        """
                        INSERT INTO win_instances (win_definition_id, patient_id, scheduled_start, scheduled_end, current_state)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (definition_id, payload.patient_id, instance.scheduled_start, instance.scheduled_end, WinState.PENDING.value),
                    )
                    created += 1
        return {"created": created}

    def resolve_participant_context(self, phone_number: str) -> ParticipantContext | None:
        normalized = _normalize_phone(phone_number)
        participant_sql = """
        SELECT p.id, p.tenant_id, p.role
        FROM participants p
        WHERE p.active = true
          AND regexp_replace(replace(p.phone_number, 'whatsapp:', ''), '[^0-9+]', '', 'g')
              = regexp_replace(%(phone)s, '[^0-9+]', '', 'g')
        LIMIT 1
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(participant_sql, {"phone": normalized})
            participant_row = cur.fetchone()
            if participant_row is None:
                return None
            participant = _row_dict(cur, participant_row)

            cur.execute(
                """
                SELECT patient_id
                FROM caregiver_patient_links
                WHERE caregiver_participant_id = %s
                ORDER BY created_at ASC
                """,
                (participant["id"],),
            )
            linked = [str(row[0]) for row in cur.fetchall()]
            unique_linked = sorted(set(linked))
            if len(unique_linked) != 1:
                return None
            patient_id = unique_linked[0]

            cur.execute(
                "SELECT timezone, persona_type FROM patients WHERE id = %s",
                (patient_id,),
            )
            patient = cur.fetchone()
            if patient is None:
                return None
            patient_timezone, patient_persona = patient
            return ParticipantContext(
                tenant_id=str(participant["tenant_id"]),
                participant_id=str(participant["id"]),
                participant_role=Role(participant["role"]),
                patient_id=str(patient_id),
                patient_timezone=str(patient_timezone),
                patient_persona=PersonaType(patient_persona),
            )

    def get_patient_profile(self, patient_id: str) -> dict | None:
        sql = """
        SELECT id, tenant_id, timezone, persona_type
        FROM patients
        WHERE id = %s
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (patient_id,))
            row = cur.fetchone()
            if row is None:
                return None
            data = _row_dict(cur, row)
            return {
                "patient_id": str(data["id"]),
                "tenant_id": str(data["tenant_id"]),
                "timezone": str(data["timezone"] or "UTC"),
                "persona_type": str(data["persona_type"] or PersonaType.CAREGIVER_MANAGED_ELDER.value),
            }

    def list_today(self, patient_id: str, now: datetime) -> list[TimelineItem]:
        profile = self.get_patient_profile(patient_id)
        timezone = ZoneInfo((profile or {}).get("timezone", "UTC"))
        now_utc = _ensure_utc(now)
        local_day = now_utc.astimezone(timezone).date()
        local_start = datetime.combine(local_day, datetime.min.time(), tzinfo=timezone)
        local_end = datetime.combine(local_day, datetime.max.time(), tzinfo=timezone)
        day_start = local_start.astimezone(UTC)
        day_end = local_end.astimezone(UTC)
        sql = """
        SELECT wi.id, wi.scheduled_start, wi.scheduled_end, wi.current_state,
               wd.title, wd.category, wd.criticality, wd.flexibility
        FROM win_instances wi
        JOIN win_definitions wd ON wd.id = wi.win_definition_id
        WHERE wi.patient_id = %(patient_id)s
          AND wi.scheduled_start BETWEEN %(day_start)s AND %(day_end)s
          AND wi.current_state <> 'superseded'
          AND (wd.temporary_start IS NULL OR wi.scheduled_start >= wd.temporary_start)
          AND (wd.temporary_end IS NULL OR wi.scheduled_start <= wd.temporary_end)
        ORDER BY wi.scheduled_start ASC
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, {"patient_id": patient_id, "day_start": day_start, "day_end": day_end})
            rows = []
            for row in cur.fetchall():
                data = _row_dict(cur, row)
                state = _derived_state(WinState(data["current_state"]), data["scheduled_start"], data["scheduled_end"], now_utc)
                rows.append(
                    TimelineItem(
                        win_instance_id=str(data["id"]),
                        title=str(data["title"]),
                        category=str(data["category"]),
                        criticality=Criticality(data["criticality"]),
                        flexibility=Flexibility(data["flexibility"]),
                        scheduled_start=data["scheduled_start"],
                        scheduled_end=data["scheduled_end"],
                        current_state=state,
                    )
                )
            return rows

    def next_item(self, patient_id: str, now: datetime) -> TimelineItem | None:
        items = self.list_today(patient_id, now)
        for item in items:
            if item.current_state in {WinState.PENDING, WinState.DUE, WinState.DELAYED}:
                return item
        return None

    def mark_win(self, win_instance_id: str, actor_id: str, state: WinState, minutes: int = 0) -> TimelineItem | None:
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            if state == WinState.DELAYED and minutes > 0:
                cur.execute(
                    """
                    UPDATE win_instances
                    SET current_state = %s,
                        scheduled_start = scheduled_start + make_interval(mins => %s),
                        scheduled_end = scheduled_end + make_interval(mins => %s)
                    WHERE id = %s
                    RETURNING patient_id
                    """,
                    (state.value, minutes, minutes, win_instance_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE win_instances
                    SET current_state = %s,
                        completion_time = CASE WHEN %s = 'completed' THEN now() ELSE completion_time END,
                        completed_by = %s
                    WHERE id = %s
                    RETURNING patient_id
                    """,
                    (state.value, state.value, actor_id, win_instance_id),
                )
            row = cur.fetchone()
            if row is None:
                return None
            patient_id = str(row[0])
            return self.next_item(patient_id, datetime.now(UTC))

    def status_counts(self, patient_id: str, now: datetime) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for item in self.list_today(patient_id, now):
            counts[item.current_state.value] += 1
        return dict(counts)

    def adherence_summary(self, patient_id: str, day: date) -> dict[str, float]:
        now = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        items = self.list_today(patient_id, now)
        total = max(len(items), 1)
        complete = len([item for item in items if item.current_state == WinState.COMPLETED])
        high = [item for item in items if item.criticality == Criticality.HIGH]
        high_total = max(len(high), 1)
        high_done = len([item for item in high if item.current_state == WinState.COMPLETED])
        return {
            "score": round((complete / total) * 100, 1),
            "high_criticality_completion_rate": round((high_done / high_total) * 100, 1),
            "all_completion_rate": round((complete / total) * 100, 1),
        }

    def log_message_event(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        participant_id: str | None,
        direction: str,
        channel: str,
        message_type: str,
        body: str,
        correlation_id: str,
        idempotency_key: str,
        payload: dict,
    ) -> bool:
        sql = """
        INSERT INTO message_events
        (tenant_id, patient_id, participant_id, direction, channel, message_type, body, structured_payload, correlation_id, idempotency_key)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT (idempotency_key) DO NOTHING
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    tenant_id,
                    patient_id,
                    participant_id,
                    direction,
                    channel,
                    message_type,
                    body,
                    json.dumps(payload),
                    correlation_id,
                    idempotency_key,
                ),
            )
            return cur.rowcount > 0


def _normalize_phone(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("whatsapp:"):
        normalized = normalized[len("whatsapp:") :]
    return "".join(ch for ch in normalized if ch.isdigit() or ch == "+")


def _row_dict(cursor, row) -> dict:
    if row is None:
        return {}
    return {desc[0]: row[index] for index, desc in enumerate(cursor.description)}


def _ensure_dt(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _derived_state(current: WinState, start: datetime, end: datetime, now: datetime) -> WinState:
    if current in {WinState.COMPLETED, WinState.SKIPPED, WinState.ESCALATED, WinState.SUPERSEDED}:
        return current
    if now > end:
        return WinState.MISSED
    if start <= now <= end:
        return WinState.DUE
    return current
