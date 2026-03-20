# CareOS Care Team Design

Last updated: 2026-03-20 UTC

## Goal

Support a real care team around one patient, where multiple people can:

- share responsibility for care
- divide responsibility by category or task
- take turns across time windows
- receive different notifications based on responsibility
- have different authority levels for viewing, editing, and confirming care actions

This document is a design artifact only. It does not assume implementation yet.

## Problem Statement

The current product can link multiple caregivers to one patient, but that is not yet the same as a care team.

Today the system can answer:

- who is linked to the patient?
- who can receive reminders?
- who can edit the care plan?

It cannot reliably answer:

- who is responsible for medications versus appointments?
- who is accountable if a critical medication is missed?
- who covers mornings versus evenings?
- who should receive a due reminder versus only a summary?
- who is allowed to complete, reschedule, or override a specific task?

That gap matters because issue `#11` is fundamentally about responsibility allocation, not just contact linking.

## Current Model

The current product already has a partial team model:

- multiple `caregiver_patient_links` can exist for one patient
- each link has coarse metadata in `notification_policy`
- link metadata is normalized into:
  - `preset`
  - `scopes`
  - `notification_preferences`
  - `authorization_version`
  - `can_edit_plan`

Current supported effective roles are mostly:

- `primary_caregiver`
- `observer`

This is enough for:

- dashboard access
- broad notification fan-out
- broad plan edit permissions

This is not enough for:

- category ownership
- time-based coverage
- turn-taking
- task-specific assignment
- patient-specific RASCI-style responsibility modeling

## Design Decision

Do not reuse `tenant` for care team semantics.

Reason:

- `tenant` is the workspace and isolation boundary
- a care team is a patient-scoped collaboration and responsibility model inside a workspace
- overloading tenant would mix identity/container concerns with operational responsibility concerns
- that would make multi-patient and multi-family participation harder, not simpler

The right design is to keep:

- `tenant` for workspace isolation
- patient links for identity/access association
- new care-team structures for responsibility and coverage

## Target Model

The target model should have three layers:

1. Membership
- who is on the team for this patient?

2. Authority
- what is each team member allowed to see or change?

3. Responsibility
- who is responsible, accountable, supporting, or informed for a given class of care, specific task, or time window?

The current caregiver link model partially covers membership and authority, but not responsibility.

## Recommended Data Model

### 1. Care Team Memberships

Add a patient-scoped membership table.

Suggested table: `care_team_memberships`

Suggested columns:

- `id UUID PRIMARY KEY`
- `tenant_id UUID NOT NULL REFERENCES tenants(id)`
- `patient_id UUID NOT NULL REFERENCES patients(id)`
- `participant_id UUID NOT NULL REFERENCES participants(id)`
- `membership_type TEXT NOT NULL`
- `relationship TEXT NOT NULL DEFAULT 'family'`
- `display_label TEXT NOT NULL DEFAULT ''`
- `status TEXT NOT NULL DEFAULT 'active'`
- `availability_policy JSONB NOT NULL DEFAULT '{}'::jsonb`
- `notification_policy JSONB NOT NULL DEFAULT '{}'::jsonb`
- `authority_policy JSONB NOT NULL DEFAULT '{}'::jsonb`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Suggested uniqueness:

- unique `(patient_id, participant_id)`

Notes:

- this can be backfilled from `caregiver_patient_links`
- `membership_type` can start with:
  - `patient_self`
  - `family_caregiver`
  - `professional_caregiver`
  - `observer`
  - `clinician_proxy`
- `authority_policy` should gradually replace `can_edit_plan`

### 2. Care Responsibility Assignments

Add a separate table for operational responsibility.

Suggested table: `care_responsibility_assignments`

Suggested columns:

- `id UUID PRIMARY KEY`
- `tenant_id UUID NOT NULL REFERENCES tenants(id)`
- `patient_id UUID NOT NULL REFERENCES patients(id)`
- `team_member_id UUID NOT NULL REFERENCES care_team_memberships(id)`
- `assignment_type TEXT NOT NULL`
- `responsibility_role TEXT NOT NULL`
- `target_category TEXT NULL`
- `target_win_definition_id UUID NULL REFERENCES win_definitions(id)`
- `target_tag TEXT NULL`
- `coverage_policy JSONB NOT NULL DEFAULT '{}'::jsonb`
- `escalation_rank INT NOT NULL DEFAULT 100`
- `status TEXT NOT NULL DEFAULT 'active'`
- `effective_start TIMESTAMPTZ NULL`
- `effective_end TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Suggested `assignment_type` values:

- `category`
- `specific_definition`
- `tag`
- later: `specific_instance_override`

Suggested `responsibility_role` values:

- `responsible`
- `accountable`
- `supporting`
- `informed`

Why this separation matters:

- membership changes less often
- assignments change more often
- turn-taking belongs in assignment coverage, not team membership

### 3. Optional Coverage Windows

Coverage should be generic, not hardcoded to examples like morning versus evening.

Suggested `coverage_policy` shape:

```json
{
  "timezone": "Asia/Kolkata",
  "days_of_week": [0, 1, 2, 3, 4, 5, 6],
  "time_windows": [
    {"start": "06:00", "end": "14:00"},
    {"start": "14:00", "end": "22:00"}
  ],
  "effective_mode": "active_only_in_window"
}
```

This should allow:

- shift-style coverage
- weekday versus weekend ownership
- temporary responsibility rotation
- planned hand-offs

### 4. Optional Assignment Resolution Snapshots

Do not add this in v1, but expect to need it later.

Possible future table: `care_assignment_resolutions`

Purpose:

- snapshot who was resolved as responsible/accountable for a reminder or escalation at the moment the system acted
- preserve explainability and auditability even if team configuration changes later

This becomes important for:

- compliance
- debugging
- “why did this reminder go to this person?”

## Runtime Behavior

### 1. Identity Resolution

No major conceptual change.

Inbound resolution still answers:

- who sent this message?
- which patient context is active?

What changes is what happens after patient context is resolved:

- team membership
- authority
- responsibility assignments

must also be available to downstream logic.

### 2. Scheduler Recipient Selection

This is the biggest runtime change.

Today the scheduler:

- finds due items
- lists linked caregivers
- filters by notification preferences
- sends reminders broadly

Target behavior:

- resolve care team memberships for the patient
- resolve responsibility assignments relevant to the due item
- identify:
  - responsible member(s)
  - accountable member(s)
  - supporting member(s)
  - informed member(s)
- apply coverage window rules
- select notification recipients based on both assignment and notification preferences

Examples:

- medication due reminder goes to the current `responsible` member
- critical miss escalates to `accountable` if `responsible` does not act
- `informed` members receive summary-level notifications only

### 3. Authorization And Edit Scope

Today edit control is essentially `can_edit_plan`.

That is too broad for a care team.

Target behavior:

- authority is policy-based
- actions can be checked against:
  - patient scope
  - category scope
  - assignment relevance
  - temporary delegated authority

Examples:

- one member can reschedule appointments but not medications
- one member can complete routine tasks during their shift but not override recurring meds
- observers can view but not act

### 4. Dashboard Representation

The caregiver dashboard should eventually show:

- team members
- their role labels
- category ownership
- current coverage window
- escalation order

This is necessary because otherwise the runtime behavior becomes opaque.

### 5. Planner And Gateway Behavior

The gateway and planner should not hardcode team-specific rules.

They should consume resolved responsibility context generically.

Examples:

- if a caregiver tries to edit a task outside their authority, explain why
- if a user asks “who is handling medications today?”, answer from assignments
- if a task is due, route completion acknowledgement to the resolved current owner when relevant

### 6. OpenClaw Grounding

OpenClaw should eventually receive:

- active care team memberships
- current resolved responsibility context for the patient
- optionally the current coverage window and escalation order

This will allow grounded answers to questions like:

- who on the team is handling mornings?
- who should I contact about medications?
- why did this reminder go to me?

## Why Not Just Extend Caregiver Presets

This is the tempting shortcut, but it will not hold.

If the design only adds more presets like:

- `medication_caregiver`
- `appointment_caregiver`
- `night_shift_caregiver`

then the system will become brittle because:

- one member may own multiple categories
- categories can overlap
- coverage changes over time
- specific recurring tasks may differ from category defaults
- escalation order is orthogonal to category ownership
- team roles are combinatorial, not enum-like

Presets are good defaults. They are not a robust operational model.

## Migration Strategy

### Phase 0: Design Only

- approve the target data model
- align terminology
- decide if `caregiver_patient_links` remains as compatibility layer or is superseded by `care_team_memberships`

### Phase 1: Membership Foundation

Implement:

- `care_team_memberships`
- backfill from `caregiver_patient_links`
- read APIs for team listing

Goal:

- make the current implicit team explicit without changing scheduler behavior yet

### Phase 2: Responsibility Assignments

Implement:

- `care_responsibility_assignments`
- internal APIs to create, list, update, and deactivate assignments
- assignment resolution service

Goal:

- express responsibility without yet changing all downstream flows

### Phase 3: Scheduler Integration

Implement:

- responsibility-aware recipient resolution
- escalation routing based on assignment roles
- coverage window handling

Goal:

- move outbound behavior from broad caregiver fan-out to responsibility-aware delivery

### Phase 4: Authorization Integration

Implement:

- scoped task/category authority checks
- gateway and API enforcement

Goal:

- stop using only broad `can_edit_plan`

### Phase 5: Dashboard And LLM Integration

Implement:

- care team display
- assignment explanations
- OpenClaw grounding

Goal:

- make the model understandable and usable

## Complexity Assessment

This is a medium-high complexity feature, not a small extension.

### Complexity by subsystem

#### Data model complexity: Medium

Why:

- two new first-class concepts are needed
- existing caregiver-link compatibility must be preserved for a while
- migrations are straightforward, but the data model must avoid duplicating authority versus responsibility semantics

#### Scheduler complexity: High

Why:

- the scheduler currently reasons in terms of recipients and notification preferences only
- it will need a resolution step for relevant team members and their current coverage
- escalation flow becomes more stateful and more explainable requirements emerge

This is the highest-risk part.

#### Authorization complexity: High

Why:

- the current permission model is coarse
- responsibility and authority are related but not identical
- scoped edit rights will affect gateway, internal APIs, dashboard actions, and possibly MCP tools

This is the second highest-risk part.

#### Gateway and WhatsApp complexity: Medium

Why:

- inbound identity resolution already exists
- but responses and action confirmations will need team-aware explanations
- active patient context alone is not enough; current team role may also matter

#### Dashboard complexity: Medium

Why:

- UI work is not conceptually hard
- but the model will need to be exposed clearly enough to explain ownership and escalation
- otherwise support/debugging cost will stay high

#### OpenClaw / grounding complexity: Medium

Why:

- it is mostly additional grounded context
- the harder part is designing the resolved, current responsibility view that the model should consume

#### Migration / rollout complexity: Medium-High

Why:

- current links and presets are already live
- the new model must coexist with them during rollout
- scheduler behavior changes can have direct operational effects

## Additional Product Complexity

Beyond engineering, this introduces product complexity that should be acknowledged early.

Questions that need explicit answers:

- can more than one person be `responsible` at the same time?
- is `accountable` required, or optional?
- if no active assignment matches a due item, what is the fallback?
- can a patient self-manage one category while a caregiver owns another?
- should responsibility be by category, by exact task, or both?
- do support roles receive due reminders or only escalation summaries?
- how should temporary delegation be represented?

If these are not decided up front, implementation will drift into ad hoc exceptions.

## Recommended MVP Scope

Keep the first shipped slice intentionally narrow.

Recommended MVP:

- explicit care team memberships
- responsibility assignments by category only
- roles limited to:
  - `responsible`
  - `informed`
- no rotating shifts yet
- no specific-instance overrides yet
- scheduler uses category responsibility for due reminders
- dashboard can list team members and category ownership

Why:

- it provides real product value quickly
- it avoids premature complexity around rotations and nested fallbacks
- it gives a stable base for later time-window and escalation features

## Recommended Non-MVP Items

Do not put these in the first slice:

- complex rotation calendars
- full RASCI modeling if product semantics are not stable yet
- per-instance assignment overrides
- automatic reassignment inference
- deeply customized escalation graphs

These should come only after the base assignment model proves out.

## Recommendation

Implement issue `#11` as a new patient-scoped care team and assignment model.

Do:

- treat current caregiver links as a compatibility/input layer
- add explicit team membership
- add explicit responsibility assignments
- make scheduler and authorization consume resolved assignment context

Do not:

- overload `tenant`
- rely only on more caregiver presets
- collapse authority and responsibility into one boolean or one enum

## Immediate Next Step

If this design is accepted, the next concrete artifact should be a phase-1 implementation plan for:

- schema
- store/service APIs
- internal API read/write endpoints
- compatibility mapping from `caregiver_patient_links`
- focused tests
