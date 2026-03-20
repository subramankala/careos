from __future__ import annotations

from careos.db.repositories.store import Store


class CareTeamService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def create_membership(
        self,
        *,
        tenant_id: str,
        patient_id: str,
        participant_id: str,
        membership_type: str,
        relationship: str = "family",
        display_label: str = "",
        authority_policy: dict | None = None,
        notification_policy: dict | None = None,
        source: str = "manual",
    ) -> dict:
        self._validate_membership_scope(tenant_id=tenant_id, patient_id=patient_id, participant_id=participant_id)
        created = self.store.create_care_team_membership(
            tenant_id=tenant_id,
            patient_id=patient_id,
            participant_id=participant_id,
            membership_type=self._normalize_membership_type(membership_type),
            relationship=str(relationship).strip() or "family",
            display_label=str(display_label).strip(),
            authority_policy=self._normalize_authority_policy(authority_policy),
            notification_policy=self._normalize_notification_policy(notification_policy),
            source=str(source).strip() or "manual",
        )
        return self.store.get_care_team_membership(str(created.get("id", ""))) or created

    def list_team_for_patient(self, *, patient_id: str) -> list[dict]:
        return self.store.list_care_team_memberships_for_patient(patient_id)

    def list_memberships_for_participant(self, *, participant_id: str) -> list[dict]:
        return self.store.list_care_team_memberships_for_participant(participant_id)

    def update_membership(
        self,
        membership_id: str,
        *,
        membership_type: str | None = None,
        relationship: str | None = None,
        display_label: str | None = None,
        authority_policy: dict | None = None,
        notification_policy: dict | None = None,
        source: str | None = None,
    ) -> dict | None:
        existing = self.store.get_care_team_membership(membership_id)
        if existing is None:
            return None
        return self.store.update_care_team_membership(
            membership_id,
            membership_type=(self._normalize_membership_type(membership_type) if membership_type is not None else None),
            relationship=(str(relationship).strip() or "family") if relationship is not None else None,
            display_label=str(display_label).strip() if display_label is not None else None,
            authority_policy=self._normalize_authority_policy(authority_policy) if authority_policy is not None else None,
            notification_policy=(
                self._normalize_notification_policy(notification_policy) if notification_policy is not None else None
            ),
            source=(str(source).strip() or "manual") if source is not None else None,
        )

    def deactivate_membership(self, membership_id: str) -> dict | None:
        return self.store.deactivate_care_team_membership(membership_id)

    def sync_membership_from_caregiver_link(self, *, caregiver_participant_id: str, patient_id: str) -> dict | None:
        return self.store.upsert_care_team_membership_from_caregiver_link(caregiver_participant_id, patient_id)

    def sync_team_from_caregiver_links(self, *, patient_id: str) -> list[dict]:
        memberships: list[dict] = []
        for link in self.store.list_caregiver_links_for_patient(patient_id):
            row = self.store.upsert_care_team_membership_from_caregiver_link(
                str(link.get("caregiver_participant_id", "")),
                patient_id,
            )
            if row is not None:
                memberships.append(row)
        return memberships

    def _validate_membership_scope(self, *, tenant_id: str, patient_id: str, participant_id: str) -> None:
        patient = self.store.get_patient_profile(patient_id)
        if patient is None:
            raise ValueError("patient not found")
        if str(patient.get("tenant_id")) != str(tenant_id):
            raise ValueError("tenant-patient mismatch")
        participant = self.store.get_participant_record(participant_id)
        if participant is None:
            raise ValueError("participant not found")
        if str(participant.get("tenant_id")) != str(tenant_id):
            raise ValueError("tenant-participant mismatch")

    @staticmethod
    def _normalize_membership_type(value: str | None) -> str:
        normalized = str(value or "").strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("membership_type is required")
        return normalized

    @staticmethod
    def _normalize_authority_policy(value: dict | None) -> dict:
        raw = dict(value or {})
        return {
            "can_view_dashboard": bool(raw.get("can_view_dashboard", True)),
            "can_edit_plan": bool(raw.get("can_edit_plan", False)),
            "can_manage_team": bool(raw.get("can_manage_team", False)),
        }

    @staticmethod
    def _normalize_notification_policy(value: dict | None) -> dict:
        raw = dict(value or {})
        return {
            "preset": str(raw.get("preset", "primary_caregiver") or "primary_caregiver"),
            "notification_preferences": dict(raw.get("notification_preferences") or {}),
        }
