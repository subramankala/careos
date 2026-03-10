from enum import StrEnum


class Role(StrEnum):
    PATIENT = "patient"
    CAREGIVER = "caregiver"
    CLINICIAN = "clinician"
    ADMIN = "admin"


class Criticality(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Flexibility(StrEnum):
    RIGID = "rigid"
    WINDOWED = "windowed"
    FLEXIBLE = "flexible"


class PersonaType(StrEnum):
    SKEPTICAL_RESISTANT = "skeptical_resistant"
    DISCIPLINED_ROUTINE_ORIENTED = "disciplined_routine_oriented"
    BUSY_PROFESSIONAL = "busy_professional"
    CAREGIVER_MANAGED_ELDER = "caregiver_managed_elder"
    DATA_DRIVEN_SELF_MANAGER = "data_driven_self_manager"


class WinState(StrEnum):
    PENDING = "pending"
    DUE = "due"
    COMPLETED = "completed"
    MISSED = "missed"
    SKIPPED = "skipped"
    DELAYED = "delayed"
    ESCALATED = "escalated"
    SUPERSEDED = "superseded"


class ResponseMode(StrEnum):
    PATIENT = "patient"
    CAREGIVER = "caregiver"
    SYSTEM = "system"
