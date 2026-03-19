from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from careos.settings import settings


class DashboardLinkError(RuntimeError):
    pass


class TaskEditError(RuntimeError):
    pass


class CareOSAdapter:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or getattr(settings, "gateway_careos_base_url", "") or "http://127.0.0.1:8115").rstrip("/")
        self.dashboard_base_url = (
            getattr(settings, "gateway_dashboard_base_url", "") or "http://127.0.0.1:8000"
        ).rstrip("/")

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(f"{self.base_url}{path}", data=body, method=method, headers=headers)
        with urlopen(req, timeout=20) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    def resolve_context(self, phone_number: str) -> dict[str, Any] | None:
        try:
            encoded = quote(str(phone_number), safe="")
            return self._request(f"/internal/resolve-context?phone_number={encoded}")
        except Exception:
            return None

    def get_today(self, patient_id: str) -> dict[str, Any]:
        return self._request(f"/patients/{patient_id}/today")

    def get_day(self, patient_id: str, day_value: date) -> dict[str, Any]:
        return self._request(f"/patients/{patient_id}/day?day={day_value.isoformat()}")

    def get_status(self, patient_id: str) -> dict[str, Any]:
        return self._request(f"/patients/{patient_id}/status")

    def get_active_care_plan(self, patient_id: str) -> dict[str, Any]:
        encoded = quote(str(patient_id), safe="")
        return self._request(f"/internal/care-plans/active?patient_id={encoded}")

    def get_win_binding(self, win_instance_id: str) -> dict[str, Any]:
        encoded = quote(str(win_instance_id), safe="")
        return self._request(f"/internal/wins/binding?win_instance_id={encoded}")

    def get_latest_scheduled_reminder_context(self, participant_id: str, patient_id: str) -> dict[str, Any] | None:
        try:
            encoded_participant = quote(str(participant_id), safe="")
            encoded_patient = quote(str(patient_id), safe="")
            return self._request(
                f"/internal/reminders/latest-context?participant_id={encoded_participant}&patient_id={encoded_patient}"
            )
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def get_pending_gateway_action(self, pending_key: str) -> dict[str, Any] | None:
        encoded = quote(str(pending_key), safe="")
        try:
            return self._request(f"/internal/gateway/pending-action?pending_key={encoded}")
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def save_pending_gateway_action(self, *, pending_key: str, plan: dict[str, Any], expires_at_iso: str) -> dict[str, Any]:
        return self._request(
            "/internal/gateway/pending-action",
            method="POST",
            payload={"pending_key": pending_key, "plan": plan, "expires_at": expires_at_iso},
        )

    def clear_pending_gateway_action(self, pending_key: str) -> dict[str, Any]:
        encoded = quote(str(pending_key), safe="")
        return self._request(f"/internal/gateway/pending-action?pending_key={encoded}", method="DELETE")

    def generate_dashboard_view(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        actor_id: str,
        role: str = "caregiver",
        view: str = "caregiver_dashboard",
    ) -> dict[str, Any]:
        body = json.dumps(
            {
                "tenant_id": tenant_id,
                "patient_id": patient_id,
                "actor_id": actor_id,
                "role": role,
                "view": view,
            }
        ).encode("utf-8")
        request = Request(
            f"{self.dashboard_base_url}/generate-view",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=20) as resp:  # noqa: S310
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise DashboardLinkError("dashboard_link_forbidden") from exc
            raise DashboardLinkError(f"dashboard_link_http_{exc.code}") from exc
        except (URLError, OSError, ValueError) as exc:
            raise DashboardLinkError("dashboard_link_unavailable") from exc

    def complete_win(self, instance_id: str, actor_id: str) -> dict[str, Any]:
        return self._request(
            f"/wins/{instance_id}/complete",
            method="POST",
            payload={"actor_participant_id": actor_id, "reason": "gateway_intent", "minutes": 0},
        )

    def supersede_win(self, instance_id: str, actor_id: str) -> dict[str, Any]:
        return self._request(
            f"/wins/{instance_id}/supersede",
            method="POST",
            payload={"actor_participant_id": actor_id, "reason": "gateway_intent", "minutes": 0},
        )

    def create_task(
        self,
        *,
        patient_id: str,
        actor_id: str,
        category: str,
        title: str,
        instructions: str,
        start_at_iso: str,
        end_at_iso: str,
        criticality: str,
        flexibility: str,
    ) -> dict[str, Any]:
        care_plan = self.get_active_care_plan(patient_id)
        care_plan_id = str(care_plan["id"])
        payload = {
            "actor_participant_id": actor_id,
            "reason": "confirmed_whatsapp_walk_request",
            "supersede_active_due": False,
            "patient_id": patient_id,
            "definition": {
                "category": category,
                "title": title,
                "instructions": instructions,
                "why_it_matters": "Created from confirmed caregiver request.",
                "criticality": criticality,
                "flexibility": flexibility,
                "recurrence_type": "one_off",
                "recurrence_interval": 1,
                "recurrence_days_of_week": [],
                "recurrence_until": None,
                "temporary_start": start_at_iso,
                "temporary_end": end_at_iso,
                "default_channel_policy": {},
                "escalation_policy": {},
            },
            "future_instances": [
                {
                    "scheduled_start": start_at_iso,
                    "scheduled_end": end_at_iso,
                }
            ],
        }
        return self._request(f"/care-plans/{care_plan_id}/wins/add", method="POST", payload=payload)

    def reschedule_task(
        self,
        *,
        win_instance_id: str,
        actor_id: str,
        start_at_iso: str,
        end_at_iso: str,
    ) -> dict[str, Any]:
        binding = self.get_win_binding(win_instance_id)
        recurrence_type = str(binding.get("recurrence_type", "one_off"))
        if recurrence_type != "one_off":
            raise TaskEditError("recurring_task_reschedule_not_supported")
        care_plan_id = str(binding["care_plan_id"])
        win_definition_id = str(binding["win_definition_id"])
        payload = {
            "actor_participant_id": actor_id,
            "reason": "confirmed_whatsapp_reschedule_request",
            "supersede_active_due": True,
            "temporary_start": start_at_iso,
            "temporary_end": end_at_iso,
            "future_instances": [
                {
                    "scheduled_start": start_at_iso,
                    "scheduled_end": end_at_iso,
                }
            ],
        }
        return self._request(
            f"/care-plans/{care_plan_id}/wins/{win_definition_id}",
            method="PATCH",
            payload=payload,
        )

    def override_recurring_task(
        self,
        *,
        win_instance_id: str,
        actor_id: str,
        start_at_iso: str,
        end_at_iso: str,
    ) -> dict[str, Any]:
        binding = self.get_win_binding(win_instance_id)
        recurrence_type = str(binding.get("recurrence_type", "one_off"))
        if recurrence_type == "one_off":
            raise TaskEditError("override_not_required_for_one_off")
        patient_id = str(binding["patient_id"])
        category = str(binding.get("category", "task"))
        title = str(binding.get("title", "Task"))
        instructions = str(binding.get("instructions", "")).strip() or f"One-time override for {title.lower()}."
        criticality = str(binding.get("criticality", "medium"))
        flexibility = str(binding.get("flexibility", "flexible"))
        created = self.create_task(
            patient_id=patient_id,
            actor_id=actor_id,
            category=category,
            title=title,
            instructions=instructions,
            start_at_iso=start_at_iso,
            end_at_iso=end_at_iso,
            criticality=criticality,
            flexibility=flexibility,
        )
        self.supersede_win(win_instance_id, actor_id)
        return created

    def remove_task(
        self,
        *,
        win_instance_id: str,
        actor_id: str,
        supersede_active_due: bool = False,
    ) -> dict[str, Any]:
        binding = self.get_win_binding(win_instance_id)
        care_plan_id = str(binding["care_plan_id"])
        win_definition_id = str(binding["win_definition_id"])
        payload = {
            "actor_participant_id": actor_id,
            "reason": "confirmed_whatsapp_remove_request",
            "supersede_active_due": supersede_active_due,
        }
        return self._request(
            f"/care-plans/{care_plan_id}/wins/{win_definition_id}",
            method="DELETE",
            payload=payload,
        )

    def update_task_recurrence(
        self,
        *,
        win_instance_id: str,
        actor_id: str,
        recurrence_type: str,
        recurrence_interval: int = 1,
        recurrence_days_of_week: list[int] | None = None,
        recurrence_until: str | None = None,
    ) -> dict[str, Any]:
        binding = self.get_win_binding(win_instance_id)
        care_plan_id = str(binding["care_plan_id"])
        win_definition_id = str(binding["win_definition_id"])
        payload = {
            "actor_participant_id": actor_id,
            "reason": "confirmed_whatsapp_recurrence_request",
            "supersede_active_due": False,
            "recurrence_type": recurrence_type,
            "recurrence_interval": max(int(recurrence_interval or 1), 1),
            "recurrence_days_of_week": list(recurrence_days_of_week or []),
            "recurrence_until": recurrence_until,
        }
        return self._request(
            f"/care-plans/{care_plan_id}/wins/{win_definition_id}",
            method="PATCH",
            payload=payload,
        )

    def skip_win(self, instance_id: str, actor_id: str) -> dict[str, Any]:
        return self._request(
            f"/wins/{instance_id}/skip",
            method="POST",
            payload={"actor_participant_id": actor_id, "reason": "gateway_intent", "minutes": 0},
        )

    def delay_win(self, instance_id: str, actor_id: str, minutes: int) -> dict[str, Any]:
        return self._request(
            f"/wins/{instance_id}/delay",
            method="POST",
            payload={"actor_participant_id": actor_id, "reason": "gateway_intent", "minutes": int(minutes)},
        )

    def create_personalization_rule(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        actor_participant_id: str,
        rule_type: str,
        rule_payload: dict[str, Any],
        expires_at_iso: str,
    ) -> dict[str, Any]:
        return self._request(
            "/internal/personalization/rules",
            method="POST",
            payload={
                "tenant_id": tenant_id,
                "patient_id": patient_id,
                "actor_participant_id": actor_participant_id,
                "rule_type": rule_type,
                "rule_payload": rule_payload,
                "expires_at": expires_at_iso,
            },
        )

    def list_active_personalization_rules(self, *, tenant_id: str, patient_id: str) -> dict[str, Any]:
        return self._request(
            f"/internal/personalization/rules/active?tenant_id={tenant_id}&patient_id={patient_id}",
            method="GET",
        )

    def upsert_patient_clinical_fact(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        actor_participant_id: str,
        fact_key: str,
        fact_value: dict[str, Any],
        summary: str,
        source: str = "caregiver_reported",
        effective_at_iso: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "actor_participant_id": actor_participant_id,
            "fact_key": fact_key,
            "fact_value": dict(fact_value or {}),
            "summary": summary,
            "source": source,
        }
        if effective_at_iso:
            payload["effective_at"] = effective_at_iso
        return self._request(
            "/internal/patient-context/clinical-facts",
            method="POST",
            payload=payload,
        )

    def list_active_patient_clinical_facts(self, *, tenant_id: str, patient_id: str) -> dict[str, Any]:
        return self._request(
            f"/internal/patient-context/clinical-facts/active?tenant_id={tenant_id}&patient_id={patient_id}",
            method="GET",
        )

    def log_mediation_decision(
        self,
        *,
        event_id: str,
        tenant_id: str,
        patient_id: str,
        participant_id: str | None,
        action: str,
        reason: str,
        policy_snapshot: dict,
        personalization_snapshot: dict,
        rendered_text: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "/internal/mediation/decisions",
            method="POST",
            payload={
                "event_id": event_id,
                "tenant_id": tenant_id,
                "patient_id": patient_id,
                "participant_id": participant_id,
                "action": action,
                "reason": reason,
                "policy_snapshot": policy_snapshot,
                "personalization_snapshot": personalization_snapshot,
                "rendered_text": rendered_text,
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key,
            },
        )
