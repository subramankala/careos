from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from careos.db.connection import get_connection
from careos.db.repositories.store import InMemoryStore, PostgresStore, Store
from careos.domain.enums.core import WinState
from careos.domain.models.api import (
    CarePlanChangeRecord,
    CarePlanDeltaResult,
    CarePlanVersionRecord,
    CarePlanWinAddRequest,
    CarePlanWinRemoveRequest,
    CarePlanWinUpdateRequest,
    WinInstanceCreate,
)


class CarePlanEditService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def list_versions(self, care_plan_id: str) -> list[CarePlanVersionRecord]:
        if isinstance(self.store, InMemoryStore):
            rows = _inmemory_versions(self.store, care_plan_id)
            return [CarePlanVersionRecord(**row) for row in rows]

        if isinstance(self.store, PostgresStore):
            sql = """
            SELECT care_plan_id, version, actor_participant_id, reason, created_at
            FROM care_plan_versions
            WHERE care_plan_id = %s
            ORDER BY version ASC
            """
            with get_connection(self.store.database_url) as conn, conn.cursor() as cur:
                cur.execute(sql, (care_plan_id,))
                return [
                    CarePlanVersionRecord(
                        care_plan_id=str(row[0]),
                        version=int(row[1]),
                        actor_participant_id=str(row[2]),
                        reason=str(row[3] or ""),
                        created_at=row[4].isoformat(),
                    )
                    for row in cur.fetchall()
                ]

        return []

    def list_changes(self, care_plan_id: str) -> list[CarePlanChangeRecord]:
        if isinstance(self.store, InMemoryStore):
            rows = _inmemory_changes(self.store, care_plan_id)
            return [CarePlanChangeRecord(**row) for row in rows]

        if isinstance(self.store, PostgresStore):
            sql = """
            SELECT change_id, care_plan_id, patient_id, version, actor_participant_id, action,
                   target_type, target_id, reason, old_value, new_value,
                   superseded_instance_ids, created_instance_ids, created_at
            FROM care_plan_change_events
            WHERE care_plan_id = %s
            ORDER BY created_at ASC
            """
            with get_connection(self.store.database_url) as conn, conn.cursor() as cur:
                cur.execute(sql, (care_plan_id,))
                out: list[CarePlanChangeRecord] = []
                for row in cur.fetchall():
                    out.append(
                        CarePlanChangeRecord(
                            change_id=str(row[0]),
                            care_plan_id=str(row[1]),
                            patient_id=str(row[2]),
                            version=int(row[3]),
                            actor_participant_id=str(row[4]),
                            action=str(row[5]),
                            target_type=str(row[6]),
                            target_id=str(row[7]),
                            reason=str(row[8] or ""),
                            old_value=dict(row[9] or {}),
                            new_value=dict(row[10] or {}),
                            superseded_instance_ids=[str(item) for item in (row[11] or [])],
                            created_instance_ids=[str(item) for item in (row[12] or [])],
                            created_at=row[13].isoformat(),
                        )
                    )
                return out

        return []

    def add_win(self, care_plan_id: str, payload: CarePlanWinAddRequest) -> CarePlanDeltaResult:
        now = datetime.now(UTC)
        self._assert_authorized(payload.actor_participant_id, payload.patient_id)
        _validate_future_instances(payload.future_instances, now)
        change_id = str(uuid4())

        if isinstance(self.store, InMemoryStore):
            care_plan = self.store.care_plans[care_plan_id]
            definition_id = str(uuid4())
            definition_row = {
                "id": definition_id,
                "care_plan_id": care_plan_id,
                **payload.definition.model_dump(mode="json"),
            }
            self.store.win_definitions[definition_id] = definition_row
            created_ids = _create_instances_inmemory(self.store, definition_row, payload.patient_id, payload.future_instances)
            version = _bump_version_inmemory(self.store, care_plan_id)
            _record_version_and_change_inmemory(
                self.store,
                care_plan_id=care_plan_id,
                patient_id=payload.patient_id,
                version=version,
                actor_participant_id=payload.actor_participant_id,
                reason=payload.reason,
                change={
                    "change_id": change_id,
                    "action": "add",
                    "target_type": "win_definition",
                    "target_id": definition_id,
                    "old_value": {},
                    "new_value": definition_row,
                    "superseded_instance_ids": [],
                    "created_instance_ids": created_ids,
                },
            )
            return CarePlanDeltaResult(
                care_plan_id=care_plan_id,
                patient_id=payload.patient_id,
                new_version=version,
                change_id=change_id,
                action="add",
                superseded_instance_ids=[],
                created_instance_ids=created_ids,
            )

        if isinstance(self.store, PostgresStore):
            return self._add_win_postgres(care_plan_id, payload, change_id)

        raise ValueError("unsupported store")

    def update_win(self, care_plan_id: str, win_definition_id: str, payload: CarePlanWinUpdateRequest) -> CarePlanDeltaResult:
        now = datetime.now(UTC)
        patient_id = self._patient_id_for_plan(care_plan_id)
        self._assert_authorized(payload.actor_participant_id, patient_id)
        _validate_future_instances(payload.future_instances, now)
        change_id = str(uuid4())

        if isinstance(self.store, InMemoryStore):
            definition = self.store.win_definitions[win_definition_id]
            old_value = dict(definition)
            updates = payload.model_dump(exclude_none=True, mode="json")
            for key in ["actor_participant_id", "reason", "supersede_active_due", "future_instances"]:
                updates.pop(key, None)
            recurrence_changed = any(
                key in updates
                for key in ("recurrence_type", "recurrence_interval", "recurrence_days_of_week", "recurrence_until")
            )
            if payload.future_instances:
                seed_start = _ensure_utc(payload.future_instances[0].scheduled_start)
                seed_end = _ensure_utc(payload.future_instances[0].scheduled_end)
                updates["seed_start"] = seed_start
                updates["seed_duration_minutes"] = max(int((seed_end - seed_start).total_seconds() // 60), 1)
            definition.update(updates)

            superseded, created = _regenerate_future_instances_inmemory(
                store=self.store,
                win_definition_id=win_definition_id,
                patient_id=patient_id,
                now=now,
                replacement_instances=payload.future_instances,
                reason=payload.reason,
                change_id=change_id,
                supersede_active_due=payload.supersede_active_due,
                force_supersede=bool(payload.future_instances) or recurrence_changed,
            )
            if recurrence_changed and not payload.future_instances:
                self.store.ensure_recurrence_instances(patient_id, now)
            _sync_definition_maps_inmemory(self.store, win_definition_id)
            version = _bump_version_inmemory(self.store, care_plan_id)
            _record_version_and_change_inmemory(
                self.store,
                care_plan_id=care_plan_id,
                patient_id=patient_id,
                version=version,
                actor_participant_id=payload.actor_participant_id,
                reason=payload.reason,
                change={
                    "change_id": change_id,
                    "action": "update",
                    "target_type": "win_definition",
                    "target_id": win_definition_id,
                    "old_value": old_value,
                    "new_value": dict(definition),
                    "superseded_instance_ids": superseded,
                    "created_instance_ids": created,
                },
            )
            return CarePlanDeltaResult(
                care_plan_id=care_plan_id,
                patient_id=patient_id,
                new_version=version,
                change_id=change_id,
                action="update",
                superseded_instance_ids=superseded,
                created_instance_ids=created,
            )

        if isinstance(self.store, PostgresStore):
            return self._update_win_postgres(care_plan_id, win_definition_id, payload, change_id)

        raise ValueError("unsupported store")

    def remove_win(self, care_plan_id: str, win_definition_id: str, payload: CarePlanWinRemoveRequest) -> CarePlanDeltaResult:
        now = datetime.now(UTC)
        patient_id = self._patient_id_for_plan(care_plan_id)
        self._assert_authorized(payload.actor_participant_id, patient_id)
        change_id = str(uuid4())

        if isinstance(self.store, InMemoryStore):
            definition = self.store.win_definitions[win_definition_id]
            old_value = dict(definition)
            definition["temporary_end"] = now
            definition["recurrence_until"] = now
            superseded, _ = _regenerate_future_instances_inmemory(
                store=self.store,
                win_definition_id=win_definition_id,
                patient_id=patient_id,
                now=now,
                replacement_instances=[],
                reason=payload.reason,
                change_id=change_id,
                supersede_active_due=payload.supersede_active_due,
                force_supersede=True,
            )
            version = _bump_version_inmemory(self.store, care_plan_id)
            _record_version_and_change_inmemory(
                self.store,
                care_plan_id=care_plan_id,
                patient_id=patient_id,
                version=version,
                actor_participant_id=payload.actor_participant_id,
                reason=payload.reason,
                change={
                    "change_id": change_id,
                    "action": "remove",
                    "target_type": "win_definition",
                    "target_id": win_definition_id,
                    "old_value": old_value,
                    "new_value": {"removed": True},
                    "superseded_instance_ids": superseded,
                    "created_instance_ids": [],
                },
            )
            return CarePlanDeltaResult(
                care_plan_id=care_plan_id,
                patient_id=patient_id,
                new_version=version,
                change_id=change_id,
                action="remove",
                superseded_instance_ids=superseded,
                created_instance_ids=[],
            )

        if isinstance(self.store, PostgresStore):
            return self._remove_win_postgres(care_plan_id, win_definition_id, payload, change_id)

        raise ValueError("unsupported store")

    def _assert_authorized(self, actor_participant_id: str, patient_id: str) -> None:
        if isinstance(self.store, InMemoryStore):
            participant = self.store.participants.get(actor_participant_id)
            if participant is None or not participant.get("active", False):
                raise PermissionError("actor not found or inactive")
            allowed = any(
                str(link["caregiver_participant_id"]) == actor_participant_id and str(link["patient_id"]) == patient_id
                for link in self.store.links
            )
            if not allowed:
                raise PermissionError("actor is not authorized for this patient")
            return

        if isinstance(self.store, PostgresStore):
            with get_connection(self.store.database_url) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM participants p
                    JOIN caregiver_patient_links cpl ON cpl.caregiver_participant_id = p.id
                    WHERE p.id = %s
                      AND p.active = true
                      AND cpl.patient_id = %s
                    LIMIT 1
                    """,
                    (actor_participant_id, patient_id),
                )
                if cur.fetchone() is None:
                    raise PermissionError("actor is not authorized for this patient")
            return

        raise PermissionError("unsupported store")

    def _patient_id_for_plan(self, care_plan_id: str) -> str:
        if isinstance(self.store, InMemoryStore):
            return str(self.store.care_plans[care_plan_id]["patient_id"])
        if isinstance(self.store, PostgresStore):
            with get_connection(self.store.database_url) as conn, conn.cursor() as cur:
                cur.execute("SELECT patient_id FROM care_plans WHERE id = %s", (care_plan_id,))
                row = cur.fetchone()
                if row is None:
                    raise ValueError("care plan not found")
                return str(row[0])
        raise ValueError("unsupported store")

    def _bump_version_postgres(self, care_plan_id: str) -> int:
        with get_connection(self.store.database_url) as conn, conn.cursor() as cur:  # type: ignore[attr-defined]
            cur.execute(
                """
                UPDATE care_plans
                SET version = version + 1, updated_at = now()
                WHERE id = %s
                RETURNING version
                """,
                (care_plan_id,),
            )
            return int(cur.fetchone()[0])

    def _add_win_postgres(self, care_plan_id: str, payload: CarePlanWinAddRequest, change_id: str) -> CarePlanDeltaResult:
        assert isinstance(self.store, PostgresStore)
        with get_connection(self.store.database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT patient_id FROM care_plans WHERE id = %s", (care_plan_id,))
            patient_id = str(cur.fetchone()[0])
            seed_start = _ensure_utc(payload.future_instances[0].scheduled_start) if payload.future_instances else None
            seed_duration_minutes = None
            if payload.future_instances:
                seed_end = _ensure_utc(payload.future_instances[0].scheduled_end)
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
                    payload.definition.category,
                    payload.definition.title,
                    payload.definition.instructions,
                    payload.definition.why_it_matters,
                    payload.definition.criticality.value,
                    payload.definition.flexibility.value,
                    payload.definition.recurrence_type.value,
                    payload.definition.recurrence_interval,
                    payload.definition.recurrence_days_of_week,
                    payload.definition.recurrence_until,
                    seed_start,
                    seed_duration_minutes,
                    payload.definition.temporary_start,
                    payload.definition.temporary_end,
                    json.dumps(payload.definition.default_channel_policy),
                    json.dumps(payload.definition.escalation_policy),
                ),
            )
            win_definition_id = str(cur.fetchone()[0])
            created_ids: list[str] = []
            for instance in payload.future_instances:
                cur.execute(
                    """
                    INSERT INTO win_instances (win_definition_id, patient_id, scheduled_start, scheduled_end, current_state)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (win_definition_id, patient_id, instance.scheduled_start, instance.scheduled_end, WinState.PENDING.value),
                )
                created_ids.append(str(cur.fetchone()[0]))

            version = self._bump_version_postgres(care_plan_id)
            _record_version_and_change_postgres(
                cur=cur,
                care_plan_id=care_plan_id,
                patient_id=patient_id,
                version=version,
                actor_participant_id=payload.actor_participant_id,
                reason=payload.reason,
                change_id=change_id,
                action="add",
                target_id=win_definition_id,
                old_value={},
                new_value={"win_definition_id": win_definition_id},
                superseded_ids=[],
                created_ids=created_ids,
            )
            return CarePlanDeltaResult(
                care_plan_id=care_plan_id,
                patient_id=patient_id,
                new_version=version,
                change_id=change_id,
                action="add",
                superseded_instance_ids=[],
                created_instance_ids=created_ids,
            )

    def _update_win_postgres(
        self,
        care_plan_id: str,
        win_definition_id: str,
        payload: CarePlanWinUpdateRequest,
        change_id: str,
    ) -> CarePlanDeltaResult:
        assert isinstance(self.store, PostgresStore)
        now = datetime.now(UTC)
        recurrence_changed = False
        effective_recurrence_type = "one_off"
        result: CarePlanDeltaResult | None = None
        with get_connection(self.store.database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT patient_id FROM care_plans WHERE id = %s", (care_plan_id,))
            patient_id = str(cur.fetchone()[0])

            cur.execute(
                """
                SELECT category, title, instructions, why_it_matters, criticality, flexibility,
                       recurrence_type, recurrence_interval, recurrence_days_of_week, recurrence_until,
                       temporary_start, temporary_end, default_channel_policy, escalation_policy,
                       seed_start, seed_duration_minutes
                FROM win_definitions WHERE id = %s AND care_plan_id = %s
                """,
                (win_definition_id, care_plan_id),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("win definition not found")
            old_value = {
                "category": row[0],
                "title": row[1],
                "instructions": row[2],
                "why_it_matters": row[3],
                "criticality": row[4],
                "flexibility": row[5],
                "recurrence_type": row[6],
                "recurrence_interval": row[7],
                "recurrence_days_of_week": list(row[8] or []),
                "recurrence_until": row[9].isoformat() if row[9] else None,
                "temporary_start": row[10].isoformat() if row[10] else None,
                "temporary_end": row[11].isoformat() if row[11] else None,
                "seed_start": row[14].isoformat() if row[14] else None,
                "seed_duration_minutes": row[15],
            }

            updates = payload.model_dump(exclude_none=True, mode="json")
            for key in ["actor_participant_id", "reason", "supersede_active_due", "future_instances"]:
                updates.pop(key, None)
            recurrence_changed = any(
                key in updates
                for key in ("recurrence_type", "recurrence_interval", "recurrence_days_of_week", "recurrence_until")
            )
            effective_recurrence_type = str(updates.get("recurrence_type", old_value["recurrence_type"]))
            if payload.future_instances:
                seed_start = _ensure_utc(payload.future_instances[0].scheduled_start)
                seed_end = _ensure_utc(payload.future_instances[0].scheduled_end)
                updates["seed_start"] = seed_start
                updates["seed_duration_minutes"] = max(int((seed_end - seed_start).total_seconds() // 60), 1)

            if updates:
                set_parts = [f"{field} = %({field})s" for field in updates.keys()]
                sql = f"UPDATE win_definitions SET {', '.join(set_parts)} WHERE id = %(id)s"
                params = dict(updates)
                params["id"] = win_definition_id
                cur.execute(sql, params)

            superseded_ids, created_ids = _regenerate_future_instances_postgres(
                cur=cur,
                win_definition_id=win_definition_id,
                patient_id=patient_id,
                now=now,
                replacement_instances=payload.future_instances,
                supersede_active_due=payload.supersede_active_due,
                reason=payload.reason,
                change_id=change_id,
                force_supersede=bool(payload.future_instances) or recurrence_changed,
            )

            version = self._bump_version_postgres(care_plan_id)
            _record_version_and_change_postgres(
                cur=cur,
                care_plan_id=care_plan_id,
                patient_id=patient_id,
                version=version,
                actor_participant_id=payload.actor_participant_id,
                reason=payload.reason,
                change_id=change_id,
                action="update",
                target_id=win_definition_id,
                old_value=old_value,
                new_value=updates,
                superseded_ids=superseded_ids,
                created_ids=created_ids,
            )

            result = CarePlanDeltaResult(
                care_plan_id=care_plan_id,
                patient_id=patient_id,
                new_version=version,
                change_id=change_id,
                action="update",
                superseded_instance_ids=superseded_ids,
                created_instance_ids=created_ids,
            )
        if recurrence_changed and effective_recurrence_type != "one_off":
            self.store.ensure_recurrence_instances(patient_id, now)
        if result is None:
            raise ValueError("failed to update win")
        return result

    def _remove_win_postgres(
        self,
        care_plan_id: str,
        win_definition_id: str,
        payload: CarePlanWinRemoveRequest,
        change_id: str,
    ) -> CarePlanDeltaResult:
        assert isinstance(self.store, PostgresStore)
        now = datetime.now(UTC)
        with get_connection(self.store.database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT patient_id FROM care_plans WHERE id = %s", (care_plan_id,))
            patient_id = str(cur.fetchone()[0])
            cur.execute(
                """
                UPDATE win_definitions
                SET temporary_end = %s,
                    recurrence_until = %s
                WHERE id = %s
                """,
                (now, now, win_definition_id),
            )
            superseded_ids, _ = _regenerate_future_instances_postgres(
                cur=cur,
                win_definition_id=win_definition_id,
                patient_id=patient_id,
                now=now,
                replacement_instances=[],
                supersede_active_due=payload.supersede_active_due,
                reason=payload.reason,
                change_id=change_id,
                force_supersede=True,
            )
            version = self._bump_version_postgres(care_plan_id)
            _record_version_and_change_postgres(
                cur=cur,
                care_plan_id=care_plan_id,
                patient_id=patient_id,
                version=version,
                actor_participant_id=payload.actor_participant_id,
                reason=payload.reason,
                change_id=change_id,
                action="remove",
                target_id=win_definition_id,
                old_value={"removed": False},
                new_value={"removed": True},
                superseded_ids=superseded_ids,
                created_ids=[],
            )

            return CarePlanDeltaResult(
                care_plan_id=care_plan_id,
                patient_id=patient_id,
                new_version=version,
                change_id=change_id,
                action="remove",
                superseded_instance_ids=superseded_ids,
                created_instance_ids=[],
            )


def _validate_future_instances(instances: list[WinInstanceCreate], now: datetime) -> None:
    now_utc = now.astimezone(UTC)
    for instance in instances:
        if instance.scheduled_start.astimezone(UTC) < now_utc:
            raise ValueError("future_instances must not include past times")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _inmemory_versions(store: InMemoryStore, care_plan_id: str) -> list[dict[str, Any]]:
    entries = getattr(store, "_care_plan_versions", [])
    return [item for item in entries if item["care_plan_id"] == care_plan_id]


def _inmemory_changes(store: InMemoryStore, care_plan_id: str) -> list[dict[str, Any]]:
    entries = getattr(store, "_care_plan_changes", [])
    return [item for item in entries if item["care_plan_id"] == care_plan_id]


def _bump_version_inmemory(store: InMemoryStore, care_plan_id: str) -> int:
    care_plan = store.care_plans[care_plan_id]
    care_plan["version"] = int(care_plan.get("version", 1)) + 1
    return int(care_plan["version"])


def _record_version_and_change_inmemory(
    store: InMemoryStore,
    *,
    care_plan_id: str,
    patient_id: str,
    version: int,
    actor_participant_id: str,
    reason: str,
    change: dict[str, Any],
) -> None:
    versions = getattr(store, "_care_plan_versions", None)
    if versions is None:
        versions = []
        setattr(store, "_care_plan_versions", versions)
    changes = getattr(store, "_care_plan_changes", None)
    if changes is None:
        changes = []
        setattr(store, "_care_plan_changes", changes)

    now_iso = datetime.now(UTC).isoformat()
    versions.append(
        {
            "care_plan_id": care_plan_id,
            "version": version,
            "actor_participant_id": actor_participant_id,
            "reason": reason,
            "created_at": now_iso,
        }
    )
    changes.append(
        {
            "change_id": change["change_id"],
            "care_plan_id": care_plan_id,
            "patient_id": patient_id,
            "version": version,
            "actor_participant_id": actor_participant_id,
            "action": change["action"],
            "target_type": change["target_type"],
            "target_id": change["target_id"],
            "reason": reason,
            "old_value": change.get("old_value", {}),
            "new_value": change.get("new_value", {}),
            "superseded_instance_ids": change.get("superseded_instance_ids", []),
            "created_instance_ids": change.get("created_instance_ids", []),
            "created_at": now_iso,
        }
    )


def _create_instances_inmemory(
    store: InMemoryStore,
    definition_row: dict[str, Any],
    patient_id: str,
    instances: list[WinInstanceCreate],
) -> list[str]:
    created_ids: list[str] = []
    for instance in instances:
        win_id = str(uuid4())
        store.win_instances[win_id] = {
            "id": win_id,
            "patient_id": patient_id,
            "win_definition_id": definition_row["id"],
            "scheduled_start": instance.scheduled_start,
            "scheduled_end": instance.scheduled_end,
            "current_state": WinState.PENDING,
            "superseded_by_change_id": None,
            "superseded_at": None,
            "superseded_reason": "",
        }
        store.win_to_title[win_id] = definition_row["title"]
        store.win_to_category[win_id] = definition_row["category"]
        store.win_to_criticality[win_id] = definition_row["criticality"]
        store.win_to_flexibility[win_id] = definition_row["flexibility"]
        store.win_to_temporary_start[win_id] = definition_row.get("temporary_start")
        store.win_to_temporary_end[win_id] = definition_row.get("temporary_end")
        created_ids.append(win_id)
    return created_ids


def _sync_definition_maps_inmemory(store: InMemoryStore, win_definition_id: str) -> None:
    definition = store.win_definitions[win_definition_id]
    for instance in store.win_instances.values():
        if str(instance["win_definition_id"]) != str(win_definition_id):
            continue
        win_id = str(instance["id"])
        store.win_to_title[win_id] = definition["title"]
        store.win_to_category[win_id] = definition["category"]
        store.win_to_criticality[win_id] = definition["criticality"]
        store.win_to_flexibility[win_id] = definition["flexibility"]
        store.win_to_temporary_start[win_id] = definition.get("temporary_start")
        store.win_to_temporary_end[win_id] = definition.get("temporary_end")


def _regenerate_future_instances_inmemory(
    *,
    store: InMemoryStore,
    win_definition_id: str,
    patient_id: str,
    now: datetime,
    replacement_instances: list[WinInstanceCreate],
    reason: str,
    change_id: str,
    supersede_active_due: bool,
    force_supersede: bool,
) -> tuple[list[str], list[str]]:
    now_utc = now.astimezone(UTC)
    superseded: list[str] = []

    for instance in store.win_instances.values():
        if str(instance["win_definition_id"]) != str(win_definition_id):
            continue
        current_state = instance["current_state"]
        if current_state in {WinState.COMPLETED, WinState.SKIPPED, WinState.SUPERSEDED}:
            continue
        start = instance["scheduled_start"].astimezone(UTC)
        end = instance["scheduled_end"].astimezone(UTC)
        is_active_due = start <= now_utc <= end
        is_future = start > now_utc
        if not force_supersede:
            continue
        if is_active_due and not supersede_active_due:
            continue
        if is_active_due or is_future:
            instance["current_state"] = WinState.SUPERSEDED
            instance["superseded_by_change_id"] = change_id
            instance["superseded_at"] = now_utc
            instance["superseded_reason"] = reason
            superseded.append(str(instance["id"]))

    definition = store.win_definitions[win_definition_id]
    created = _create_instances_inmemory(store, definition, patient_id, replacement_instances)
    return superseded, created


def _record_version_and_change_postgres(
    *,
    cur,
    care_plan_id: str,
    patient_id: str,
    version: int,
    actor_participant_id: str,
    reason: str,
    change_id: str,
    action: str,
    target_id: str,
    old_value: dict[str, Any],
    new_value: dict[str, Any],
    superseded_ids: list[str],
    created_ids: list[str],
) -> None:
    def _json_safe(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_json_safe(item) for item in value]
        return value

    cur.execute(
        """
        INSERT INTO care_plan_versions (care_plan_id, version, actor_participant_id, reason)
        VALUES (%s, %s, %s, %s)
        """,
        (care_plan_id, version, actor_participant_id, reason),
    )
    cur.execute(
        """
        INSERT INTO care_plan_change_events
        (change_id, care_plan_id, patient_id, version, actor_participant_id, action, target_type, target_id, reason,
         old_value, new_value, superseded_instance_ids, created_instance_ids)
        VALUES (%s, %s, %s, %s, %s, %s, 'win_definition', %s, %s, %s::jsonb, %s::jsonb, %s::uuid[], %s::uuid[])
        """,
        (
            change_id,
            care_plan_id,
            patient_id,
            version,
            actor_participant_id,
            action,
            target_id,
            reason,
            json.dumps(_json_safe(old_value)),
            json.dumps(_json_safe(new_value)),
            superseded_ids,
            created_ids,
        ),
    )


def _regenerate_future_instances_postgres(
    *,
    cur,
    win_definition_id: str,
    patient_id: str,
    now: datetime,
    replacement_instances: list[WinInstanceCreate],
    supersede_active_due: bool,
    reason: str,
    change_id: str,
    force_supersede: bool,
) -> tuple[list[str], list[str]]:
    now_utc = now.astimezone(UTC)
    cur.execute(
        """
        SELECT id, scheduled_start, scheduled_end, current_state
        FROM win_instances
        WHERE win_definition_id = %s
          AND patient_id = %s
        """,
        (win_definition_id, patient_id),
    )
    rows = cur.fetchall()
    superseded_ids: list[str] = []
    for row in rows:
        instance_id = str(row[0])
        start = row[1].astimezone(UTC)
        end = row[2].astimezone(UTC)
        state = str(row[3])
        if state in {WinState.COMPLETED.value, WinState.SKIPPED.value, WinState.SUPERSEDED.value}:
            continue
        is_active_due = start <= now_utc <= end
        is_future = start > now_utc
        if not force_supersede:
            continue
        if is_active_due and not supersede_active_due:
            continue
        if is_active_due or is_future:
            cur.execute(
                """
                UPDATE win_instances
                SET current_state = %s,
                    superseded_by_change_id = %s,
                    superseded_at = now(),
                    superseded_reason = %s
                WHERE id = %s
                """,
                (WinState.SUPERSEDED.value, change_id, reason, instance_id),
            )
            superseded_ids.append(instance_id)

    created_ids: list[str] = []
    for instance in replacement_instances:
        cur.execute(
            """
            INSERT INTO win_instances
            (win_definition_id, patient_id, scheduled_start, scheduled_end, current_state)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (win_definition_id, patient_id, instance.scheduled_start, instance.scheduled_end, WinState.PENDING.value),
        )
        created_ids.append(str(cur.fetchone()[0]))
    return superseded_ids, created_ids
