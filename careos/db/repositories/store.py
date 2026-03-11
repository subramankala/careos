from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from careos.db.connection import get_connection
from careos.domain.enums.core import Criticality, Flexibility, PersonaType, RecurrenceType, Role, WinState
from careos.domain.models.api import (
    AddWinsRequest,
    CarePlanCreate,
    CaregiverVerificationRequest,
    LinkedPatientSummary,
    OnboardingSession,
    ParticipantIdentity,
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
    def find_participant_record_by_phone(self, phone_number: str) -> dict | None:
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
    def get_active_care_plan_for_patient(self, patient_id: str) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    def resolve_participant_by_phone(self, phone_number: str) -> ParticipantIdentity | None:
        raise NotImplementedError

    @abstractmethod
    def list_linked_patients(self, participant_id: str) -> list[LinkedPatientSummary]:
        raise NotImplementedError

    @abstractmethod
    def get_active_patient_context(self, participant_id: str) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def set_active_patient_context(self, participant_id: str, patient_id: str, selection_source: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear_active_patient_context(self, participant_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_onboarding_session(self, phone_number: str) -> OnboardingSession | None:
        raise NotImplementedError

    @abstractmethod
    def save_onboarding_session(
        self,
        *,
        phone_number: str,
        state: str,
        status: str,
        data: dict,
        expires_at: datetime,
        completion_note: str = "",
    ) -> OnboardingSession:
        raise NotImplementedError

    @abstractmethod
    def create_caregiver_verification_request(
        self,
        *,
        tenant_id: str,
        caregiver_participant_id: str,
        patient_id: str,
        patient_participant_id: str,
        caregiver_name: str,
        caregiver_phone_number: str,
        patient_name: str,
        patient_phone_number: str,
        relationship: str,
        approval_code: str,
        expires_at: datetime,
    ) -> CaregiverVerificationRequest:
        raise NotImplementedError

    @abstractmethod
    def get_verification_request(self, request_id: str) -> CaregiverVerificationRequest | None:
        raise NotImplementedError

    @abstractmethod
    def get_pending_verification_for_caregiver(
        self, caregiver_participant_id: str
    ) -> CaregiverVerificationRequest | None:
        raise NotImplementedError

    @abstractmethod
    def list_pending_verifications_for_patient_phone(self, phone_number: str) -> list[CaregiverVerificationRequest]:
        raise NotImplementedError

    @abstractmethod
    def update_verification_request(
        self,
        request_id: str,
        *,
        status: str | None = None,
        send_attempt_count: int | None = None,
        last_sent_at: datetime | None = None,
        resolved_at: datetime | None = None,
        resolution_note: str | None = None,
    ) -> CaregiverVerificationRequest:
        raise NotImplementedError

    @abstractmethod
    def resolve_participant_context(self, phone_number: str) -> ParticipantContext | None:
        raise NotImplementedError

    @abstractmethod
    def get_patient_profile(self, patient_id: str) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    def ensure_recurrence_instances(self, patient_id: str, now: datetime, horizon_days: int = 30) -> int:
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
        self.active_patient_context: dict[str, dict] = {}
        self.onboarding_sessions: dict[str, dict] = {}
        self.caregiver_verification_requests: dict[str, dict] = {}

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

    def find_participant_record_by_phone(self, phone_number: str) -> dict | None:
        normalized = _normalize_phone(phone_number)
        participant = next(
            (p for p in self.participants.values() if _normalize_phone(str(p["phone_number"])) == normalized),
            None,
        )
        if participant is None:
            return None
        return {
            "id": str(participant["id"]),
            "tenant_id": str(participant["tenant_id"]),
            "role": str(participant["role"]),
            "display_name": str(participant["display_name"]),
            "phone_number": str(participant["phone_number"]),
            "active": bool(participant["active"]),
        }

    def link_caregiver(self, caregiver_participant_id: str, patient_id: str) -> dict:
        for existing in self.links:
            if (
                str(existing["caregiver_participant_id"]) == str(caregiver_participant_id)
                and str(existing["patient_id"]) == str(patient_id)
            ):
                return existing
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
            definition_row = {
                "id": definition_id,
                "care_plan_id": care_plan_id,
                **definition.model_dump(mode="json"),
            }
            if payload.instances:
                seed_start = _ensure_dt(payload.instances[0].scheduled_start)
                seed_end = _ensure_dt(payload.instances[0].scheduled_end)
                duration_minutes = int((seed_end - seed_start).total_seconds() // 60)
                definition_row["seed_start"] = seed_start
                definition_row["seed_duration_minutes"] = max(duration_minutes, 1)
            self.win_definitions[definition_id] = definition_row
            for instance in payload.instances:
                start = _ensure_dt(instance.scheduled_start)
                if self._instance_exists(definition_id, start):
                    continue
                self._create_instance(
                    patient_id=payload.patient_id,
                    definition_id=definition_id,
                    scheduled_start=start,
                    scheduled_end=_ensure_dt(instance.scheduled_end),
                )
                created += 1
        created += self.ensure_recurrence_instances(payload.patient_id, datetime.now(UTC))
        return {"created": created}

    def get_active_care_plan_for_patient(self, patient_id: str) -> dict | None:
        sql = """
        SELECT id, patient_id, created_by_participant_id, status, version, effective_start, effective_end, source_type
        FROM care_plans
        WHERE patient_id = %s
          AND status = 'active'
        ORDER BY version DESC, created_at DESC
        LIMIT 1
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (patient_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return _row_dict(cur, row)

    def get_active_care_plan_for_patient(self, patient_id: str) -> dict | None:
        candidates = [
            plan
            for plan in self.care_plans.values()
            if str(plan.get("patient_id")) == str(patient_id) and str(plan.get("status", "")) == "active"
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: int(item.get("version", 0)), reverse=True)
        return dict(candidates[0])

    def resolve_participant_by_phone(self, phone_number: str) -> ParticipantIdentity | None:
        normalized = _normalize_phone(phone_number)
        participant = next(
            (p for p in self.participants.values() if _normalize_phone(p["phone_number"]) == normalized and p["active"]),
            None,
        )
        if participant is None:
            return None
        return ParticipantIdentity(
            tenant_id=str(participant["tenant_id"]),
            participant_id=str(participant["id"]),
            participant_role=Role(str(participant["role"])),
        )

    def list_linked_patients(self, participant_id: str) -> list[LinkedPatientSummary]:
        linked_patient_ids: list[str] = []
        seen: set[str] = set()
        for link in self.links:
            if str(link["caregiver_participant_id"]) != str(participant_id):
                continue
            patient_id = str(link["patient_id"])
            if patient_id in seen:
                continue
            seen.add(patient_id)
            linked_patient_ids.append(patient_id)
        out: list[LinkedPatientSummary] = []
        for patient_id in linked_patient_ids:
            patient = self.patients.get(patient_id)
            if patient is None:
                continue
            out.append(
                LinkedPatientSummary(
                    patient_id=patient_id,
                    display_name=str(patient.get("display_name", patient_id)),
                    timezone=str(patient.get("timezone", "UTC") or "UTC"),
                    tenant_id=str(patient.get("tenant_id")),
                )
            )
        out.sort(key=lambda item: item.display_name.casefold())
        return out

    def get_active_patient_context(self, participant_id: str) -> str | None:
        row = self.active_patient_context.get(str(participant_id))
        if not row:
            return None
        patient_id = str(row["patient_id"])
        linked = {item.patient_id for item in self.list_linked_patients(str(participant_id))}
        if patient_id not in linked:
            self.clear_active_patient_context(str(participant_id))
            return None
        return patient_id

    def set_active_patient_context(self, participant_id: str, patient_id: str, selection_source: str) -> None:
        participant = self.participants.get(str(participant_id))
        patient = self.patients.get(str(patient_id))
        if participant is None or patient is None:
            raise ValueError("participant or patient not found")
        if str(participant.get("tenant_id")) != str(patient.get("tenant_id")):
            raise ValueError("participant and patient tenant mismatch")
        linked = {item.patient_id for item in self.list_linked_patients(str(participant_id))}
        if str(patient_id) not in linked:
            raise ValueError("participant is not linked to patient")
        now = datetime.now(UTC)
        if str(participant_id) in self.active_patient_context:
            selected_at = self.active_patient_context[str(participant_id)]["selected_at"]
        else:
            selected_at = now
        self.active_patient_context[str(participant_id)] = {
            "patient_id": str(patient_id),
            "selected_at": selected_at,
            "updated_at": now,
            "selection_source": selection_source,
        }

    def clear_active_patient_context(self, participant_id: str) -> None:
        self.active_patient_context.pop(str(participant_id), None)

    def get_onboarding_session(self, phone_number: str) -> OnboardingSession | None:
        normalized = _normalize_phone(phone_number)
        row = self.onboarding_sessions.get(normalized)
        if row is None:
            return None
        return OnboardingSession.model_validate(row)

    def save_onboarding_session(
        self,
        *,
        phone_number: str,
        state: str,
        status: str,
        data: dict,
        expires_at: datetime,
        completion_note: str = "",
    ) -> OnboardingSession:
        normalized = _normalize_phone(phone_number)
        existing = self.onboarding_sessions.get(normalized)
        session_id = str(existing["id"]) if existing else str(uuid4())
        now = datetime.now(UTC)
        row = {
            "id": session_id,
            "phone_number": normalized,
            "state": state,
            "status": status,
            "data": data,
            "expires_at": _ensure_utc(expires_at),
            "completion_note": completion_note,
            "updated_at": now,
        }
        self.onboarding_sessions[normalized] = row
        return OnboardingSession.model_validate(row)

    def create_caregiver_verification_request(
        self,
        *,
        tenant_id: str,
        caregiver_participant_id: str,
        patient_id: str,
        patient_participant_id: str,
        caregiver_name: str,
        caregiver_phone_number: str,
        patient_name: str,
        patient_phone_number: str,
        relationship: str,
        approval_code: str,
        expires_at: datetime,
    ) -> CaregiverVerificationRequest:
        request_id = str(uuid4())
        row = {
            "id": request_id,
            "tenant_id": str(tenant_id),
            "caregiver_participant_id": str(caregiver_participant_id),
            "patient_id": str(patient_id),
            "patient_participant_id": str(patient_participant_id),
            "caregiver_name": caregiver_name,
            "caregiver_phone_number": caregiver_phone_number,
            "patient_name": patient_name,
            "patient_phone_number": patient_phone_number,
            "relationship": relationship,
            "approval_code": approval_code,
            "status": "pending",
            "expires_at": _ensure_utc(expires_at),
            "send_attempt_count": 0,
            "last_sent_at": None,
            "resolved_at": None,
            "resolution_note": "",
        }
        self.caregiver_verification_requests[request_id] = row
        return CaregiverVerificationRequest.model_validate(row)

    def get_verification_request(self, request_id: str) -> CaregiverVerificationRequest | None:
        row = self.caregiver_verification_requests.get(str(request_id))
        if row is None:
            return None
        return CaregiverVerificationRequest.model_validate(row)

    def get_pending_verification_for_caregiver(
        self, caregiver_participant_id: str
    ) -> CaregiverVerificationRequest | None:
        now = datetime.now(UTC)
        latest: dict | None = None
        for row in self.caregiver_verification_requests.values():
            if str(row["caregiver_participant_id"]) != str(caregiver_participant_id):
                continue
            if str(row["status"]) != "pending":
                continue
            if _ensure_dt(row["expires_at"]) <= now:
                row["status"] = "expired"
                row["resolved_at"] = now
                row["resolution_note"] = "expired"
                continue
            if latest is None or str(row["id"]) > str(latest["id"]):
                latest = row
        return CaregiverVerificationRequest.model_validate(latest) if latest else None

    def list_pending_verifications_for_patient_phone(self, phone_number: str) -> list[CaregiverVerificationRequest]:
        normalized = _normalize_phone(phone_number)
        now = datetime.now(UTC)
        rows: list[CaregiverVerificationRequest] = []
        for row in self.caregiver_verification_requests.values():
            if _normalize_phone(str(row["patient_phone_number"])) != normalized:
                continue
            if str(row["status"]) != "pending":
                continue
            if _ensure_dt(row["expires_at"]) <= now:
                row["status"] = "expired"
                row["resolved_at"] = now
                row["resolution_note"] = "expired"
                continue
            rows.append(CaregiverVerificationRequest.model_validate(row))
        rows.sort(key=lambda item: item.id)
        return rows

    def update_verification_request(
        self,
        request_id: str,
        *,
        status: str | None = None,
        send_attempt_count: int | None = None,
        last_sent_at: datetime | None = None,
        resolved_at: datetime | None = None,
        resolution_note: str | None = None,
    ) -> CaregiverVerificationRequest:
        row = self.caregiver_verification_requests[str(request_id)]
        if status is not None:
            row["status"] = status
        if send_attempt_count is not None:
            row["send_attempt_count"] = int(send_attempt_count)
        if last_sent_at is not None:
            row["last_sent_at"] = _ensure_utc(last_sent_at)
        if resolved_at is not None:
            row["resolved_at"] = _ensure_utc(resolved_at)
        if resolution_note is not None:
            row["resolution_note"] = resolution_note
        self.caregiver_verification_requests[str(request_id)] = row
        return CaregiverVerificationRequest.model_validate(row)

    def resolve_participant_context(self, phone_number: str) -> ParticipantContext | None:
        identity = self.resolve_participant_by_phone(phone_number)
        if identity is None:
            return None

        linked_patient_ids = [item.patient_id for item in self.list_linked_patients(identity.participant_id)]
        if len(linked_patient_ids) != 1:
            active_patient_id = self.get_active_patient_context(identity.participant_id)
            if active_patient_id is None:
                return None
            patient_id = active_patient_id
        else:
            patient_id = linked_patient_ids[0]
            if self.get_active_patient_context(identity.participant_id) != patient_id:
                self.set_active_patient_context(identity.participant_id, patient_id, "auto_single_link")

        patient = self.patients[patient_id]
        return ParticipantContext(
            tenant_id=str(identity.tenant_id),
            participant_id=str(identity.participant_id),
            participant_role=identity.participant_role,
            patient_id=patient_id,
            patient_timezone=str(patient["timezone"]),
            patient_persona=PersonaType(str(patient["persona_type"])),
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

    def ensure_recurrence_instances(self, patient_id: str, now: datetime, horizon_days: int = 30) -> int:
        profile = self.get_patient_profile(patient_id)
        timezone = ZoneInfo(profile["timezone"]) if profile else ZoneInfo("UTC")
        now_utc = _ensure_utc(now)
        start_day = now_utc.astimezone(timezone).date()
        end_day = start_day + timedelta(days=horizon_days)
        created = 0

        for definition_id, definition in self.win_definitions.items():
            care_plan = self.care_plans.get(str(definition.get("care_plan_id")))
            if care_plan is None or str(care_plan.get("patient_id")) != str(patient_id):
                continue
            recurrence_type = RecurrenceType(str(definition.get("recurrence_type", RecurrenceType.ONE_OFF.value)))
            if recurrence_type is RecurrenceType.ONE_OFF:
                continue

            seed_start_raw = definition.get("seed_start")
            seed_duration_minutes = int(definition.get("seed_duration_minutes", 0) or 0)
            if seed_start_raw is None or seed_duration_minutes <= 0:
                continue
            seed_start_utc = _ensure_dt(seed_start_raw)
            seed_local = seed_start_utc.astimezone(timezone)

            interval = max(int(definition.get("recurrence_interval", 1) or 1), 1)
            days_raw = definition.get("recurrence_days_of_week") or []
            allowed_days = {int(v) for v in days_raw} if days_raw else {seed_local.weekday()}
            recurrence_until_raw = definition.get("recurrence_until")
            recurrence_until = _ensure_dt(recurrence_until_raw) if recurrence_until_raw else None

            cursor = start_day
            while cursor <= end_day:
                if not _matches_recurrence(
                    recurrence_type=recurrence_type,
                    seed_date=seed_local.date(),
                    candidate_date=cursor,
                    interval=interval,
                    allowed_weekdays=allowed_days,
                ):
                    cursor += timedelta(days=1)
                    continue

                local_start = datetime.combine(cursor, seed_local.timetz()).replace(tzinfo=timezone)
                start_utc = local_start.astimezone(UTC)
                if recurrence_until is not None and start_utc > recurrence_until:
                    cursor += timedelta(days=1)
                    continue
                if self._instance_exists(str(definition_id), start_utc):
                    cursor += timedelta(days=1)
                    continue

                self._create_instance(
                    patient_id=str(patient_id),
                    definition_id=str(definition_id),
                    scheduled_start=start_utc,
                    scheduled_end=start_utc + timedelta(minutes=seed_duration_minutes),
                )
                created += 1
                cursor += timedelta(days=1)
        return created

    def _instance_exists(self, definition_id: str, scheduled_start: datetime) -> bool:
        for instance in self.win_instances.values():
            if str(instance["win_definition_id"]) != str(definition_id):
                continue
            if _ensure_dt(instance["scheduled_start"]) == _ensure_dt(scheduled_start):
                return True
        return False

    def _create_instance(
        self,
        *,
        patient_id: str,
        definition_id: str,
        scheduled_start: datetime,
        scheduled_end: datetime,
    ) -> str:
        definition = self.win_definitions[definition_id]
        win_id = str(uuid4())
        self.win_instances[win_id] = {
            "id": win_id,
            "patient_id": patient_id,
            "win_definition_id": definition_id,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "current_state": WinState.PENDING,
        }
        self.win_to_title[win_id] = str(definition["title"])
        self.win_to_category[win_id] = str(definition["category"])
        self.win_to_criticality[win_id] = Criticality(str(definition["criticality"]))
        self.win_to_flexibility[win_id] = Flexibility(str(definition["flexibility"]))
        temporary_start = definition.get("temporary_start")
        temporary_end = definition.get("temporary_end")
        self.win_to_temporary_start[win_id] = _ensure_dt(temporary_start) if temporary_start else None
        self.win_to_temporary_end[win_id] = _ensure_dt(temporary_end) if temporary_end else None
        return win_id

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

    def find_participant_record_by_phone(self, phone_number: str) -> dict | None:
        normalized = _normalize_phone(phone_number)
        sql = """
        SELECT id, tenant_id, role, display_name, phone_number, active
        FROM participants
        WHERE regexp_replace(replace(phone_number, 'whatsapp:', ''), '[^0-9+]', '', 'g')
              = regexp_replace(%(phone)s, '[^0-9+]', '', 'g')
        ORDER BY active DESC, created_at DESC
        LIMIT 1
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, {"phone": normalized})
            row = cur.fetchone()
            if row is None:
                return None
            data = _row_dict(cur, row)
            return {
                "id": str(data["id"]),
                "tenant_id": str(data["tenant_id"]),
                "role": str(data["role"]),
                "display_name": str(data["display_name"]),
                "phone_number": str(data["phone_number"]),
                "active": bool(data["active"]),
            }

    def link_caregiver(self, caregiver_participant_id: str, patient_id: str) -> dict:
        find_sql = """
        SELECT id, caregiver_participant_id, patient_id
        FROM caregiver_patient_links
        WHERE caregiver_participant_id = %(caregiver_participant_id)s
          AND patient_id = %(patient_id)s
        LIMIT 1
        """
        sql = """
        INSERT INTO caregiver_patient_links (caregiver_participant_id, patient_id)
        VALUES (%(caregiver_participant_id)s, %(patient_id)s)
        RETURNING id, caregiver_participant_id, patient_id
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            params = {"caregiver_participant_id": caregiver_participant_id, "patient_id": patient_id}
            cur.execute(find_sql, params)
            existing = cur.fetchone()
            if existing is not None:
                return _row_dict(cur, existing)
            cur.execute(sql, params)
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
                seed_start = _ensure_dt(payload.instances[0].scheduled_start) if payload.instances else None
                seed_duration_minutes = None
                if payload.instances:
                    seed_end = _ensure_dt(payload.instances[0].scheduled_end)
                    seed_duration_minutes = max(int((seed_end - seed_start).total_seconds() // 60), 1) if seed_start else 1
                cur.execute(
                    """
                    INSERT INTO win_definitions
                    (care_plan_id, category, title, instructions, why_it_matters, criticality, flexibility,
                     recurrence_type, recurrence_interval, recurrence_days_of_week, recurrence_until,
                     seed_start, seed_duration_minutes,
                     temporary_start, temporary_end, default_channel_policy, escalation_policy)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::int[], %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
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
                        definition.recurrence_type.value,
                        definition.recurrence_interval,
                        definition.recurrence_days_of_week,
                        definition.recurrence_until,
                        seed_start,
                        seed_duration_minutes,
                        definition.temporary_start,
                        definition.temporary_end,
                        json.dumps(definition.default_channel_policy),
                        json.dumps(definition.escalation_policy),
                    ),
                )
                definition_id = cur.fetchone()[0]
                for instance in payload.instances:
                    start = _ensure_dt(instance.scheduled_start)
                    cur.execute(
                        """
                        INSERT INTO win_instances (win_definition_id, patient_id, scheduled_start, scheduled_end, current_state)
                        SELECT %s, %s, %s, %s, %s
                        WHERE NOT EXISTS (
                          SELECT 1 FROM win_instances
                          WHERE win_definition_id = %s AND scheduled_start = %s
                        )
                        """,
                        (
                            definition_id,
                            payload.patient_id,
                            start,
                            _ensure_dt(instance.scheduled_end),
                            WinState.PENDING.value,
                            definition_id,
                            start,
                        ),
                    )
                    if cur.rowcount > 0:
                        created += 1
        created += self.ensure_recurrence_instances(payload.patient_id, datetime.now(UTC))
        return {"created": created}

    def resolve_participant_by_phone(self, phone_number: str) -> ParticipantIdentity | None:
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
            return ParticipantIdentity(
                tenant_id=str(participant["tenant_id"]),
                participant_id=str(participant["id"]),
                participant_role=Role(str(participant["role"])),
            )

    def list_linked_patients(self, participant_id: str) -> list[LinkedPatientSummary]:
        sql = """
        SELECT DISTINCT pa.id AS patient_id, pa.display_name, pa.timezone, pa.tenant_id
        FROM caregiver_patient_links cpl
        JOIN patients pa ON pa.id = cpl.patient_id
        WHERE cpl.caregiver_participant_id = %s
        ORDER BY pa.display_name ASC
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (participant_id,))
            rows: list[LinkedPatientSummary] = []
            for row in cur.fetchall():
                rows.append(
                    LinkedPatientSummary(
                        patient_id=str(row[0]),
                        display_name=str(row[1]),
                        timezone=str(row[2] or "UTC"),
                        tenant_id=str(row[3]),
                    )
                )
            return rows

    def get_active_patient_context(self, participant_id: str) -> str | None:
        sql = """
        SELECT pac.patient_id
        FROM participant_active_context pac
        JOIN caregiver_patient_links cpl
          ON cpl.caregiver_participant_id = pac.participant_id
         AND cpl.patient_id = pac.patient_id
        WHERE pac.participant_id = %s
        LIMIT 1
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (participant_id,))
            row = cur.fetchone()
            return str(row[0]) if row else None

    def set_active_patient_context(self, participant_id: str, patient_id: str, selection_source: str) -> None:
        validate_sql = """
        SELECT 1
        FROM participants p
        JOIN caregiver_patient_links cpl ON cpl.caregiver_participant_id = p.id
        JOIN patients pa ON pa.id = cpl.patient_id
        WHERE p.id = %s
          AND pa.id = %s
          AND p.active = true
          AND p.tenant_id = pa.tenant_id
        LIMIT 1
        """
        upsert_sql = """
        INSERT INTO participant_active_context (participant_id, patient_id, selection_source)
        VALUES (%s, %s, %s)
        ON CONFLICT (participant_id)
        DO UPDATE SET
          patient_id = EXCLUDED.patient_id,
          updated_at = now(),
          selection_source = EXCLUDED.selection_source
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(validate_sql, (participant_id, patient_id))
            if cur.fetchone() is None:
                raise ValueError("participant is not authorized for patient context")
            cur.execute(upsert_sql, (participant_id, patient_id, selection_source))

    def clear_active_patient_context(self, participant_id: str) -> None:
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM participant_active_context WHERE participant_id = %s", (participant_id,))

    def get_onboarding_session(self, phone_number: str) -> OnboardingSession | None:
        normalized = _normalize_phone(phone_number)
        sql = """
        SELECT id, phone_number, state, status, data, expires_at, completion_note
        FROM onboarding_sessions
        WHERE regexp_replace(replace(phone_number, 'whatsapp:', ''), '[^0-9+]', '', 'g')
              = regexp_replace(%(phone)s, '[^0-9+]', '', 'g')
        LIMIT 1
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, {"phone": normalized})
            row = cur.fetchone()
            if row is None:
                return None
            data = _row_dict(cur, row)
            return OnboardingSession(
                id=str(data["id"]),
                phone_number=str(data["phone_number"]),
                state=str(data["state"]),
                status=str(data["status"]),
                data=dict(data["data"] or {}),
                expires_at=_ensure_dt(data["expires_at"]),
                completion_note=str(data.get("completion_note") or ""),
            )

    def save_onboarding_session(
        self,
        *,
        phone_number: str,
        state: str,
        status: str,
        data: dict,
        expires_at: datetime,
        completion_note: str = "",
    ) -> OnboardingSession:
        normalized = _normalize_phone(phone_number)
        sql = """
        INSERT INTO onboarding_sessions (phone_number, state, status, data, expires_at, completion_note)
        VALUES (%s, %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT (phone_number)
        DO UPDATE SET
          state = EXCLUDED.state,
          status = EXCLUDED.status,
          data = EXCLUDED.data,
          expires_at = EXCLUDED.expires_at,
          completion_note = EXCLUDED.completion_note,
          updated_at = now(),
          completed_at = CASE
            WHEN EXCLUDED.status IN ('completed', 'handoff_pending') THEN now()
            ELSE onboarding_sessions.completed_at
          END
        RETURNING id, phone_number, state, status, data, expires_at, completion_note
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    normalized,
                    state,
                    status,
                    json.dumps(data or {}),
                    _ensure_utc(expires_at),
                    completion_note,
                ),
            )
            row = cur.fetchone()
            data_row = _row_dict(cur, row)
            return OnboardingSession(
                id=str(data_row["id"]),
                phone_number=str(data_row["phone_number"]),
                state=str(data_row["state"]),
                status=str(data_row["status"]),
                data=dict(data_row["data"] or {}),
                expires_at=_ensure_dt(data_row["expires_at"]),
                completion_note=str(data_row.get("completion_note") or ""),
            )

    def create_caregiver_verification_request(
        self,
        *,
        tenant_id: str,
        caregiver_participant_id: str,
        patient_id: str,
        patient_participant_id: str,
        caregiver_name: str,
        caregiver_phone_number: str,
        patient_name: str,
        patient_phone_number: str,
        relationship: str,
        approval_code: str,
        expires_at: datetime,
    ) -> CaregiverVerificationRequest:
        sql = """
        INSERT INTO caregiver_verification_requests
        (tenant_id, caregiver_participant_id, patient_id, patient_participant_id,
         caregiver_name, caregiver_phone_number, patient_name, patient_phone_number, relationship, approval_code, status, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)
        RETURNING id, tenant_id, caregiver_participant_id, patient_id, patient_participant_id,
                  caregiver_name, caregiver_phone_number, patient_name, patient_phone_number, relationship, approval_code,
                  status, expires_at, send_attempt_count, last_sent_at, resolved_at, resolution_note
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    tenant_id,
                    caregiver_participant_id,
                    patient_id,
                    patient_participant_id,
                    caregiver_name,
                    caregiver_phone_number,
                    patient_name,
                    patient_phone_number,
                    relationship,
                    approval_code,
                    _ensure_utc(expires_at),
                ),
            )
            return self._verification_row(cur, cur.fetchone())

    def _expire_verification_requests(self) -> None:
        sql = """
        UPDATE caregiver_verification_requests
        SET status = 'expired',
            resolved_at = now(),
            resolution_note = CASE
              WHEN resolution_note = '' THEN 'expired'
              ELSE resolution_note
            END,
            updated_at = now()
        WHERE status = 'pending'
          AND expires_at <= now()
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql)

    def _verification_row(self, cursor, row) -> CaregiverVerificationRequest:
        data = _row_dict(cursor, row)
        return CaregiverVerificationRequest(
            id=str(data["id"]),
            tenant_id=str(data["tenant_id"]),
            caregiver_participant_id=str(data["caregiver_participant_id"]),
            patient_id=str(data["patient_id"]),
            patient_participant_id=str(data["patient_participant_id"]),
            caregiver_name=str(data["caregiver_name"]),
            caregiver_phone_number=str(data["caregiver_phone_number"]),
            patient_name=str(data["patient_name"]),
            patient_phone_number=str(data["patient_phone_number"]),
            relationship=str(data["relationship"]),
            approval_code=str(data["approval_code"]),
            status=str(data["status"]),
            expires_at=_ensure_dt(data["expires_at"]),
            send_attempt_count=int(data.get("send_attempt_count") or 0),
            last_sent_at=_ensure_dt(data["last_sent_at"]) if data.get("last_sent_at") else None,
            resolved_at=_ensure_dt(data["resolved_at"]) if data.get("resolved_at") else None,
            resolution_note=str(data.get("resolution_note") or ""),
        )

    def get_verification_request(self, request_id: str) -> CaregiverVerificationRequest | None:
        sql = """
        SELECT id, tenant_id, caregiver_participant_id, patient_id, patient_participant_id,
               caregiver_name, caregiver_phone_number, patient_name, patient_phone_number, relationship, approval_code,
               status, expires_at, send_attempt_count, last_sent_at, resolved_at, resolution_note
        FROM caregiver_verification_requests
        WHERE id = %s
        LIMIT 1
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (request_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._verification_row(cur, row)

    def get_pending_verification_for_caregiver(
        self, caregiver_participant_id: str
    ) -> CaregiverVerificationRequest | None:
        self._expire_verification_requests()
        sql = """
        SELECT id, tenant_id, caregiver_participant_id, patient_id, patient_participant_id,
               caregiver_name, caregiver_phone_number, patient_name, patient_phone_number, relationship, approval_code,
               status, expires_at, send_attempt_count, last_sent_at, resolved_at, resolution_note
        FROM caregiver_verification_requests
        WHERE caregiver_participant_id = %s
          AND status = 'pending'
        ORDER BY created_at DESC
        LIMIT 1
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, (caregiver_participant_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._verification_row(cur, row)

    def list_pending_verifications_for_patient_phone(self, phone_number: str) -> list[CaregiverVerificationRequest]:
        self._expire_verification_requests()
        normalized = _normalize_phone(phone_number)
        sql = """
        SELECT id, tenant_id, caregiver_participant_id, patient_id, patient_participant_id,
               caregiver_name, caregiver_phone_number, patient_name, patient_phone_number, relationship, approval_code,
               status, expires_at, send_attempt_count, last_sent_at, resolved_at, resolution_note
        FROM caregiver_verification_requests
        WHERE status = 'pending'
          AND regexp_replace(replace(patient_phone_number, 'whatsapp:', ''), '[^0-9+]', '', 'g')
              = regexp_replace(%(phone)s, '[^0-9+]', '', 'g')
        ORDER BY created_at ASC
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(sql, {"phone": normalized})
            return [self._verification_row(cur, row) for row in cur.fetchall()]

    def update_verification_request(
        self,
        request_id: str,
        *,
        status: str | None = None,
        send_attempt_count: int | None = None,
        last_sent_at: datetime | None = None,
        resolved_at: datetime | None = None,
        resolution_note: str | None = None,
    ) -> CaregiverVerificationRequest:
        sql = """
        UPDATE caregiver_verification_requests
        SET status = COALESCE(%(status)s, status),
            send_attempt_count = COALESCE(%(send_attempt_count)s, send_attempt_count),
            last_sent_at = COALESCE(%(last_sent_at)s, last_sent_at),
            resolved_at = COALESCE(%(resolved_at)s, resolved_at),
            resolution_note = COALESCE(%(resolution_note)s, resolution_note),
            updated_at = now()
        WHERE id = %(request_id)s
        RETURNING id, tenant_id, caregiver_participant_id, patient_id, patient_participant_id,
                  caregiver_name, caregiver_phone_number, patient_name, patient_phone_number, relationship, approval_code,
                  status, expires_at, send_attempt_count, last_sent_at, resolved_at, resolution_note
        """
        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                sql,
                {
                    "request_id": request_id,
                    "status": status,
                    "send_attempt_count": send_attempt_count,
                    "last_sent_at": _ensure_utc(last_sent_at) if last_sent_at else None,
                    "resolved_at": _ensure_utc(resolved_at) if resolved_at else None,
                    "resolution_note": resolution_note,
                },
            )
            return self._verification_row(cur, cur.fetchone())

    def resolve_participant_context(self, phone_number: str) -> ParticipantContext | None:
        identity = self.resolve_participant_by_phone(phone_number)
        if identity is None:
            return None

        linked = self.list_linked_patients(identity.participant_id)
        if len(linked) != 1:
            active_patient_id = self.get_active_patient_context(identity.participant_id)
            if active_patient_id is None:
                return None
            candidate_ids = {item.patient_id for item in linked}
            if active_patient_id not in candidate_ids:
                self.clear_active_patient_context(identity.participant_id)
                return None
            patient_id = active_patient_id
        else:
            patient_id = linked[0].patient_id
            if self.get_active_patient_context(identity.participant_id) != patient_id:
                self.set_active_patient_context(identity.participant_id, patient_id, "auto_single_link")

        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT timezone, persona_type FROM patients WHERE id = %s",
                (patient_id,),
            )
            patient = cur.fetchone()
            if patient is None:
                return None
            patient_timezone, patient_persona = patient
            return ParticipantContext(
                tenant_id=str(identity.tenant_id),
                participant_id=str(identity.participant_id),
                participant_role=identity.participant_role,
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

    def ensure_recurrence_instances(self, patient_id: str, now: datetime, horizon_days: int = 30) -> int:
        profile = self.get_patient_profile(patient_id)
        timezone = ZoneInfo((profile or {}).get("timezone", "UTC"))
        now_utc = _ensure_utc(now)
        start_day = now_utc.astimezone(timezone).date()
        end_day = start_day + timedelta(days=horizon_days)
        created = 0

        with get_connection(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT wd.id, wd.recurrence_type, wd.recurrence_interval, wd.recurrence_days_of_week,
                       wd.recurrence_until, wd.seed_start, wd.seed_duration_minutes
                FROM win_definitions wd
                JOIN care_plans cp ON cp.id = wd.care_plan_id
                WHERE cp.patient_id = %s
                  AND wd.recurrence_type IN ('daily', 'weekly')
                """,
                (patient_id,),
            )
            definitions = cur.fetchall()
            for definition in definitions:
                definition_id = str(definition[0])
                recurrence_type = RecurrenceType(str(definition[1]))
                interval = max(int(definition[2] or 1), 1)
                days_raw = definition[3] or []
                recurrence_until = _ensure_dt(definition[4]) if definition[4] else None
                seed_start_raw = definition[5]
                duration_minutes = int(definition[6] or 0)
                if seed_start_raw is None or duration_minutes <= 0:
                    continue

                seed_start = _ensure_dt(seed_start_raw)
                seed_local = seed_start.astimezone(timezone)
                allowed_days = {int(v) for v in days_raw} if days_raw else {seed_local.weekday()}

                cursor_day = start_day
                while cursor_day <= end_day:
                    if not _matches_recurrence(
                        recurrence_type=recurrence_type,
                        seed_date=seed_local.date(),
                        candidate_date=cursor_day,
                        interval=interval,
                        allowed_weekdays=allowed_days,
                    ):
                        cursor_day += timedelta(days=1)
                        continue
                    local_start = datetime.combine(cursor_day, seed_local.timetz()).replace(tzinfo=timezone)
                    start_utc = local_start.astimezone(UTC)
                    if recurrence_until is not None and start_utc > recurrence_until:
                        cursor_day += timedelta(days=1)
                        continue
                    cur.execute(
                        """
                        INSERT INTO win_instances (win_definition_id, patient_id, scheduled_start, scheduled_end, current_state)
                        SELECT %s, %s, %s, %s, %s
                        WHERE NOT EXISTS (
                          SELECT 1 FROM win_instances
                          WHERE win_definition_id = %s AND scheduled_start = %s
                        )
                        """,
                        (
                            definition_id,
                            patient_id,
                            start_utc,
                            start_utc + timedelta(minutes=duration_minutes),
                            WinState.PENDING.value,
                            definition_id,
                            start_utc,
                        ),
                    )
                    if cur.rowcount > 0:
                        created += 1
                    cursor_day += timedelta(days=1)
        return created

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


def _matches_recurrence(
    *,
    recurrence_type: RecurrenceType,
    seed_date: date,
    candidate_date: date,
    interval: int,
    allowed_weekdays: set[int],
) -> bool:
    if candidate_date < seed_date:
        return False
    day_delta = (candidate_date - seed_date).days
    if recurrence_type is RecurrenceType.DAILY:
        return day_delta % interval == 0
    if recurrence_type is RecurrenceType.WEEKLY:
        if candidate_date.weekday() not in allowed_weekdays:
            return False
        week_delta = day_delta // 7
        return week_delta % interval == 0
    return False
