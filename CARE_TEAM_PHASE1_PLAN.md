# CareOS Care Team Phase 1 Plan

Last updated: 2026-03-20 UTC

Related design: [CARE_TEAM_DESIGN.md](/home/kumarmankala/careos/CARE_TEAM_DESIGN.md)

## Phase 1 Goal

Make the current implicit patient care team explicit in the data model and APIs without changing live scheduler routing or task-assignment behavior yet.

This phase should answer:

- who is on the team for this patient?
- what broad authority and notification defaults does each member have?

It should not yet answer:

- who is operationally responsible for this due item right now?
- who covers this category during this time window?
- who should the scheduler choose instead of broad caregiver fan-out?

That separation is deliberate. Phase 1 is a foundation slice.

## Scope

Phase 1 includes:

- explicit `care_team_memberships` storage
- backfill/compatibility mapping from current `caregiver_patient_links`
- store and service APIs for create/list/update/deactivate
- internal API endpoints for read/write operations
- basic dashboard-ready team listing payload
- focused tests

Phase 1 does not include:

- `care_responsibility_assignments`
- coverage windows
- scheduler recipient selection changes
- scoped task/category edit enforcement
- OpenClaw grounding for care-team responsibility
- rotation logic

## Product Outcome

After phase 1:

- a patient can have an explicit care team record set
- each team member can have a `membership_type`
- each team member can carry authority and notification defaults
- current caregiver links still work
- existing reminders and permissions continue working the old way

This gives the product a stable base for later responsibility-aware behavior.

## Why This Slice First

This is the lowest-risk slice that still creates real product value.

Benefits:

- eliminates ambiguity around who is on the care team
- gives a proper read model for dashboard/team views
- decouples team membership from later operational assignment logic
- keeps scheduler risk out of the first release

## Proposed Data Model

### New table: `care_team_memberships`

Suggested columns:

- `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `tenant_id UUID NOT NULL REFERENCES tenants(id)`
- `patient_id UUID NOT NULL REFERENCES patients(id)`
- `participant_id UUID NOT NULL REFERENCES participants(id)`
- `membership_type TEXT NOT NULL`
- `relationship TEXT NOT NULL DEFAULT 'family'`
- `display_label TEXT NOT NULL DEFAULT ''`
- `authority_policy JSONB NOT NULL DEFAULT '{}'::jsonb`
- `notification_policy JSONB NOT NULL DEFAULT '{}'::jsonb`
- `status TEXT NOT NULL DEFAULT 'active'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Suggested uniqueness:

- unique `(patient_id, participant_id)`

Suggested indexes:

- `(patient_id, status, created_at)`
- `(participant_id, status, created_at)`
- `(tenant_id, patient_id, status)`

### Suggested initial `membership_type` values

- `patient_self`
- `family_caregiver`
- `professional_caregiver`
- `observer`

### Suggested policy semantics

`authority_policy` should start simple:

```json
{
  "can_view_dashboard": true,
  "can_edit_plan": true,
  "can_manage_team": false
}
```

`notification_policy` can mirror current caregiver-link behavior:

```json
{
  "preset": "primary_caregiver",
  "notification_preferences": {
    "due_reminders": true,
    "critical_alerts": true,
    "daily_summary": true,
    "low_adherence_alerts": true
  }
}
```

## Compatibility Strategy

Phase 1 must coexist with the current caregiver-link model.

### Current source of truth

For phase 1 rollout:

- `caregiver_patient_links` remains the runtime source of truth for scheduler and broad access behavior
- `care_team_memberships` becomes the explicit team read/write model for new product surfaces

### Compatibility mapping

Backfill and compatibility rules:

- each active `caregiver_patient_link` becomes one `care_team_membership`
- `preset` maps to `membership_type` as follows:
  - `primary_caregiver` -> `family_caregiver`
  - `observer` -> `observer`
- `relationship` is preserved
- `notification_policy` is copied
- `can_edit_plan` becomes part of `authority_policy`

### Important rule

Phase 1 should not try to replace `caregiver_patient_links` yet.

Reason:

- too many current flows depend on it directly
- scheduler behavior is already live
- this phase is about explicit membership, not runtime reassignment

## Store Layer Plan

Add abstract store methods:

- `create_care_team_membership(...)`
- `get_care_team_membership(membership_id)`
- `list_care_team_memberships_for_patient(patient_id)`
- `list_care_team_memberships_for_participant(participant_id)`
- `update_care_team_membership(...)`
- `deactivate_care_team_membership(membership_id)`
- `upsert_care_team_membership_from_caregiver_link(...)`

Implement in:

- `InMemoryStore`
- `PostgresStore`

### In-memory behavior

- maintain uniqueness by `(patient_id, participant_id)`
- preserve insertion/update timestamps
- allow compatibility upsert from caregiver-link sync

### Postgres behavior

- use `INSERT ... ON CONFLICT` for compatibility upserts
- always return normalized team membership rows

## Service Layer Plan

Add a new service:

- `CareTeamService`

Recommended responsibilities:

- validate participant and patient belong to the same tenant
- normalize `membership_type`
- normalize `authority_policy`
- normalize `notification_policy`
- expose compatibility sync from caregiver links

Suggested methods:

- `create_membership(...)`
- `list_team_for_patient(...)`
- `list_patient_memberships_for_participant(...)`
- `update_membership(...)`
- `deactivate_membership(...)`
- `sync_membership_from_caregiver_link(...)`

## Internal API Plan

Add endpoints under `/internal/care-team`.

### Create

`POST /internal/care-team/memberships`

Payload:

- `tenant_id`
- `patient_id`
- `participant_id`
- `membership_type`
- `relationship`
- `display_label`
- `authority_policy`
- `notification_policy`

### List by patient

`GET /internal/care-team/memberships?patient_id=...`

Return:

- patient-scoped team list with participant display info and policies

### Update

`POST /internal/care-team/memberships/update`

Payload:

- `membership_id`
- optional updated fields

### Deactivate

`DELETE /internal/care-team/memberships?membership_id=...`

### Sync from current caregiver links

Recommended internal-only helper route or startup utility:

- `POST /internal/care-team/sync-from-caregiver-links?patient_id=...`

This can support controlled rollout and backfill.

## Dashboard/API Read Model

Phase 1 should expose a simple team list, not assignment logic.

Suggested response shape:

```json
{
  "patient_id": "patient-1",
  "team": [
    {
      "membership_id": "tm-1",
      "participant_id": "participant-1",
      "display_name": "Kumar",
      "phone_number": "whatsapp:+15550001111",
      "membership_type": "family_caregiver",
      "relationship": "son",
      "display_label": "Primary family caregiver",
      "authority_policy": {
        "can_view_dashboard": true,
        "can_edit_plan": true,
        "can_manage_team": false
      },
      "notification_policy": {
        "preset": "primary_caregiver",
        "notification_preferences": {
          "due_reminders": true,
          "critical_alerts": true
        }
      },
      "status": "active"
    }
  ]
}
```

## Migration Plan

### Step 1: Schema migration

Create a new migration:

- `0012_care_team_memberships.sql`

Contents:

- create table
- create indexes
- optional uniqueness constraint

### Step 2: Store/service support

Implement store and service support behind tests first.

### Step 3: Compatibility sync utility

Implement a controlled sync path:

- one-off backfill command or script
- optional API endpoint for per-patient sync

### Step 4: Internal API exposure

Expose read/write endpoints once store and service are stable.

### Step 5: Limited product read integration

Start by using the new read model only for:

- internal debugging
- dashboard/team listing

Do not switch scheduler or gateway authorization in this phase.

## Rollout Strategy

### Rollout mode

Use dual-model rollout:

- old caregiver-link model stays active
- new care-team membership model is added alongside it

### Backfill strategy

Recommended first pass:

- backfill all existing caregiver links into `care_team_memberships`
- rerunnable sync should be idempotent

### Safety rule

If a synced membership conflicts with a manually edited one:

- prefer the explicit care-team membership row once manual editing is enabled
- log that the compatibility sync skipped overwrite

That requires a simple source marker.

Suggested optional column:

- `source TEXT NOT NULL DEFAULT 'manual'`

Possible values:

- `manual`
- `caregiver_link_sync`

## Testing Plan

Phase 1 should add focused tests in these areas.

### Store tests

- create membership
- uniqueness by `(patient_id, participant_id)`
- list by patient
- list by participant
- deactivate membership
- compatibility upsert from caregiver link

### Service tests

- reject tenant mismatch
- normalize membership type
- preserve authority and notification policies
- sync membership from caregiver link correctly

### API tests

- create endpoint returns normalized membership
- list endpoint includes participant display info
- update endpoint changes allowed fields only
- deactivate endpoint hides inactive rows

### Compatibility tests

- caregiver link sync produces expected membership type and policies
- rerunning sync is idempotent
- observer caregiver link becomes observer team member

## Additional Complexity In Phase 1

Phase 1 is moderate complexity.

### What makes it manageable

- no scheduler behavior change
- no responsibility assignment yet
- no coverage windows yet
- no runtime routing changes yet

### What still adds complexity

- dual-model compatibility
- backfill and idempotent sync
- deciding which model becomes canonical later
- avoiding policy drift between caregiver links and team memberships

The biggest phase-1 risk is not schema. It is policy duplication.

That is why compatibility rules need to be explicit and narrow.

## Open Questions To Resolve Before Coding

1. Should patient self-membership be created in phase 1 or deferred?
2. Should `care_team_memberships` include clinicians/professionals now, or only family-style caregivers?
3. Should manual edits to team membership be allowed immediately, or should phase 1 be read-only plus sync?
4. Should `authority_policy` remain broad in phase 1, or only mirror `can_edit_plan`?
5. Should the dashboard read from the new table immediately, or only after backfill is complete?

## Recommended Answers

Recommended decisions for phase 1:

1. Include patient self-membership only if it is easy to backfill cleanly. Otherwise defer.
2. Allow generic `membership_type` values from day one, but only use family caregiver and observer initially.
3. Allow manual creation and update in internal APIs, but keep user-facing UI changes out of phase 1.
4. Keep `authority_policy` broad and simple in phase 1.
5. Use the new table for internal/debug reads first, then dashboard reads after backfill validation.

## Definition Of Done

Phase 1 is done when:

- `care_team_memberships` exists in schema
- existing caregiver links can be synced into memberships
- internal APIs can create/list/update/deactivate memberships
- focused tests pass
- current scheduler and caregiver behavior remain unchanged
- a patient team can be listed explicitly from the new model

## Immediate Next Step After Approval

Implement these files first:

- migration `0012_care_team_memberships.sql`
- store abstractions and implementations in [store.py](/home/kumarmankala/careos/careos/db/repositories/store.py)
- new service `care_team_service.py`
- internal routes in [internal.py](/home/kumarmankala/careos/careos/api/routes/internal.py)
- focused tests for store, service, and internal API
