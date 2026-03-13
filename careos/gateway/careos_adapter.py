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
