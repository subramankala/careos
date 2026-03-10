from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field

from careos.domain.enums.core import Criticality, Flexibility, PersonaType, Role, WinState


class TenantCreate(BaseModel):
    name: str
    type: str = "family"
    timezone: str = "UTC"
    status: str = "active"


class PatientCreate(BaseModel):
    tenant_id: str
    display_name: str
    timezone: str = "UTC"
    primary_language: str = "en"
    persona_type: PersonaType = PersonaType.CAREGIVER_MANAGED_ELDER
    risk_level: str = "medium"
    status: str = "active"


class ParticipantCreate(BaseModel):
    tenant_id: str
    role: Role
    display_name: str
    phone_number: str
    preferred_channel: str = "whatsapp"
    preferred_language: str = "en"
    active: bool = True


class CaregiverLinkCreate(BaseModel):
    caregiver_participant_id: str
    patient_id: str
    relationship: str = "family"
    notification_policy: dict[str, str] = Field(default_factory=dict)
    can_edit_plan: bool = True


class CarePlanCreate(BaseModel):
    patient_id: str
    created_by_participant_id: str
    status: str = "active"
    version: int = 1
    effective_start: datetime | None = None
    effective_end: datetime | None = None
    source_type: str = "manual"


class WinDefinitionCreate(BaseModel):
    category: str
    title: str
    instructions: str
    why_it_matters: str = ""
    criticality: Criticality
    flexibility: Flexibility
    temporary_start: datetime | None = None
    temporary_end: datetime | None = None
    default_channel_policy: dict[str, str] = Field(default_factory=dict)
    escalation_policy: dict[str, str] = Field(default_factory=dict)


class WinInstanceCreate(BaseModel):
    scheduled_start: datetime
    scheduled_end: datetime


class AddWinsRequest(BaseModel):
    patient_id: str
    definitions: list[WinDefinitionCreate]
    instances: list[WinInstanceCreate]


class WinActionRequest(BaseModel):
    actor_participant_id: str
    reason: str = ""
    minutes: int = 0


class TimelineItem(BaseModel):
    win_instance_id: str
    title: str
    category: str
    criticality: Criticality
    flexibility: Flexibility
    scheduled_start: datetime
    scheduled_end: datetime
    current_state: WinState


class PatientTodayResponse(BaseModel):
    patient_id: str
    date: str
    timezone: str
    timeline: list[TimelineItem] = Field(default_factory=list)


class PatientStatusResponse(BaseModel):
    patient_id: str
    completed_count: int
    due_count: int
    missed_count: int
    skipped_count: int
    adherence_score: float


class AdherenceSummaryResponse(BaseModel):
    patient_id: str
    date: str
    score: float
    high_criticality_completion_rate: float
    all_completion_rate: float
    notes: str = ""


class TwilioInboundPayload(BaseModel):
    From: str
    To: str | None = None
    Body: str = ""
    MessageSid: str | None = None


class ParticipantContext(BaseModel):
    tenant_id: str
    participant_id: str
    participant_role: Role
    patient_id: str
    patient_timezone: str
    patient_persona: PersonaType


class CommandResult(BaseModel):
    text: str
    action: str


class CarePlanDeltaMeta(BaseModel):
    actor_participant_id: str
    reason: str = ""
    supersede_active_due: bool = False


class CarePlanWinAddRequest(CarePlanDeltaMeta):
    patient_id: str
    definition: WinDefinitionCreate
    future_instances: list[WinInstanceCreate] = Field(default_factory=list)


class CarePlanWinUpdateRequest(CarePlanDeltaMeta):
    title: str | None = None
    category: str | None = None
    instructions: str | None = None
    why_it_matters: str | None = None
    criticality: Criticality | None = None
    flexibility: Flexibility | None = None
    temporary_start: datetime | None = None
    temporary_end: datetime | None = None
    default_channel_policy: dict[str, str] | None = None
    escalation_policy: dict[str, str] | None = None
    future_instances: list[WinInstanceCreate] = Field(default_factory=list)


class CarePlanWinRemoveRequest(CarePlanDeltaMeta):
    pass


class CarePlanDeltaResult(BaseModel):
    care_plan_id: str
    patient_id: str
    new_version: int
    change_id: str
    action: str
    superseded_instance_ids: list[str] = Field(default_factory=list)
    created_instance_ids: list[str] = Field(default_factory=list)


class CarePlanVersionRecord(BaseModel):
    care_plan_id: str
    version: int
    actor_participant_id: str
    reason: str = ""
    created_at: str


class CarePlanChangeRecord(BaseModel):
    change_id: str
    care_plan_id: str
    patient_id: str
    version: int
    actor_participant_id: str
    action: str
    target_type: str
    target_id: str
    reason: str = ""
    old_value: dict
    new_value: dict
    superseded_instance_ids: list[str] = Field(default_factory=list)
    created_instance_ids: list[str] = Field(default_factory=list)
    created_at: str
