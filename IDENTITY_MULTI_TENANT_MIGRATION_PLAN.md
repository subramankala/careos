# CareOS Identity And Multi-Tenant Membership Migration Plan

Last updated: 2026-03-16 UTC

## Goal

Support one real person with one WhatsApp number participating in multiple CareOS family workspaces and patient relationships at the same time.

Examples:

- the same phone is `primary caregiver` for one patient
- the same phone is `observer` for another patient
- the two patients may belong to different family tenants
- the same human may also be a patient in their own family workspace

This is not reliably possible in the current model because phone number resolution is tenant-bound through `participants`.

## Current Model

Current schema and behavior:

- `participants.phone_number` is globally unique in [`0001_initial.sql`](/home/kumarmankala/careos/careos/db/migrations/0001_initial.sql)
- `participants` belongs directly to one `tenant`
- inbound phone resolution returns one tenant-scoped `ParticipantIdentity`
- `participant_active_context` is keyed by `participant_id`
- caregiver verification requests reference tenant-scoped participant IDs
- many tables reference `participants(id)` as the actor identity

Current consequence:

- one phone can only belong to one tenant
- inviting a caregiver already known in another tenant fails
- role mixing for one human is fragile
- cross-family caregiver participation is blocked at the identity layer, not the product layer

## Target Model

Split global identity from tenant membership.

### New conceptual layers

1. `person_identity`
- global identity for a human/contact point
- one row per WhatsApp number
- not tenant-scoped

2. `tenant_memberships`
- membership of a global identity in a tenant
- membership status and tenant-local display preferences live here

3. `patient_links`
- relationship between a tenant membership and a patient
- can represent:
  - patient self link
  - caregiver link
  - observer link
- per-patient permissions and notification presets live here

### Design rule

Global identity answers:
- who is this phone number?

Tenant membership answers:
- which family workspace(s) is this person part of?

Patient link answers:
- what can this person do for this patient?

## Proposed Schema Direction

### 1. Add `person_identities`

Suggested columns:

- `id UUID PRIMARY KEY`
- `primary_phone_number TEXT NOT NULL UNIQUE`
- `normalized_phone_number TEXT NOT NULL UNIQUE`
- `display_name TEXT NOT NULL DEFAULT ''`
- `preferred_channel TEXT NOT NULL DEFAULT 'whatsapp'`
- `preferred_language TEXT NOT NULL DEFAULT 'en'`
- `active BOOLEAN NOT NULL DEFAULT true`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Notes:

- use normalized phone as the true lookup key
- keep raw phone only for display if desired

### 2. Add `tenant_memberships`

Suggested columns:

- `id UUID PRIMARY KEY`
- `tenant_id UUID NOT NULL REFERENCES tenants(id)`
- `person_identity_id UUID NOT NULL REFERENCES person_identities(id)`
- `membership_type TEXT NOT NULL`
- `display_name TEXT NOT NULL`
- `membership_status TEXT NOT NULL DEFAULT 'active'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Suggested uniqueness:

- unique `(tenant_id, person_identity_id)`

`membership_type` can start simple:

- `patient_member`
- `caregiver_member`
- `mixed_member`

This does not need to drive permissions by itself. It is mostly an enrollment/container concept.

### 3. Add `patient_participant_links`

Suggested columns:

- `id UUID PRIMARY KEY`
- `tenant_membership_id UUID NOT NULL REFERENCES tenant_memberships(id)`
- `patient_id UUID NOT NULL REFERENCES patients(id)`
- `link_type TEXT NOT NULL`
- `relationship TEXT NOT NULL DEFAULT 'family'`
- `notification_policy JSONB NOT NULL DEFAULT '{}'::jsonb`
- `can_edit_plan BOOLEAN NOT NULL DEFAULT false`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Suggested uniqueness:

- unique `(tenant_membership_id, patient_id, link_type)`

`link_type` examples:

- `self`
- `caregiver`
- `observer`

This table should eventually replace `caregiver_patient_links` and the current implicit patient self-link behavior.

### 4. Add membership-scoped active context

Replace or supersede `participant_active_context`.

Suggested table:

- `membership_active_context`
- key by `tenant_membership_id`
- select active `patient_id`

Why:

- active context is tenant-relative
- one person can have different active patient choices in different family workspaces

## Compatibility Strategy

Do not hard-cut away from `participants` immediately.

### Transitional rule

- keep `participants` as the legacy actor table during migration
- backfill each `participants` row to:
  - one `person_identity`
  - one `tenant_membership`
- add foreign keys from `participants` to the new structures:
  - `person_identity_id`
  - optional `tenant_membership_id`

During transition:

- phone resolution should prefer `person_identities`
- existing action/audit tables may continue to reference `participants(id)`
- webhook and onboarding flows can be progressively moved to membership-aware logic

This is safer than rewriting every actor foreign key in one release.

## Runtime Behavior After Migration

### Inbound phone resolution

Current:

- phone -> one `participant`

Target:

- phone -> one `person_identity`
- then load active memberships
- then resolve tenant/patient context from:
  - one membership + one patient link: auto select
  - one membership + multiple linked patients: require `use`
  - multiple memberships: show workspace selection first, then patient selection if needed

### Suggested command model

Add two explicit context layers:

- `families` or `workspaces`
- `patients`

Suggested examples:

- `families`
- `use family 2`
- `patients`
- `use patient 1`

For the first implementation, preserve the existing `patients` and `use` commands when there is only one tenant membership.

### Invite flow

Patient invites caregiver:

1. patient sends `invite caregiver`
2. CareOS resolves patient’s tenant membership
3. CareOS resolves caregiver phone to `person_identity`
4. if none exists, create one
5. ensure a `tenant_membership` exists for that identity in this tenant
6. create pending invite against that membership, not against a tenant-scoped participant phone lock
7. caregiver approves
8. create `patient_participant_link` with preset for this patient only

This allows the same phone to join another tenant safely.

### Preset updates

Commands like `set caregiver <phone> as observer` should continue resolving from the active patient’s linked memberships, not from a global participant lookup.

## Data Migration Plan

### Phase 0: preparation

- freeze new schema work touching `participants`
- add a design flag in docs: identity migration in progress
- add targeted metrics around phone resolution and tenant mismatch failures

### Phase 1: additive schema

Add new tables only:

- `person_identities`
- `tenant_memberships`
- `membership_active_context` or equivalent

Add nullable columns to `participants`:

- `person_identity_id`
- `tenant_membership_id`

No runtime behavior change yet.

### Phase 2: backfill

For each existing participant:

1. normalize phone
2. create or reuse `person_identity`
3. create `tenant_membership` for `(tenant_id, person_identity_id)`
4. update `participants.person_identity_id`
5. update `participants.tenant_membership_id`

Backfill caregiver links:

- existing `caregiver_patient_links.caregiver_participant_id`
- map through `participants.tenant_membership_id`
- create corresponding rows in `patient_participant_links`

Backfill self-patient links:

- detect patient participant rows created during self onboarding
- create `patient_participant_links(link_type='self')`

### Phase 3: dual-read runtime

Change services to read new structures first while still writing legacy structures where needed.

Priority order:

1. identity resolution
2. onboarding
3. caregiver invites
4. active patient context
5. scheduler recipient resolution
6. gateway permission checks

At this phase:

- write both legacy and new link records
- log diffs if resolution disagrees

### Phase 4: membership-aware commands

Add membership/workspace selection behavior:

- if one person has multiple tenant memberships, require workspace selection
- preserve existing UX for single-membership users

### Phase 5: foreign key migration

Move event/audit actor references from legacy `participants` to either:

- `tenant_membership_id`, or
- both `person_identity_id` and `tenant_membership_id`

Recommended rule:

- operational actions use `tenant_membership_id`
- global contact lookups use `person_identity_id`

Tables to revisit:

- `care_plans.created_by_participant_id`
- `win_instances.completed_by`
- `message_events.participant_id`
- `escalation_events.recipient_participant_id`
- `care_plan_versions.actor_participant_id`
- `care_plan_change_events.actor_participant_id`
- `caregiver_verification_requests.caregiver_participant_id`
- `caregiver_verification_requests.patient_participant_id`

### Phase 6: retire legacy assumptions

- remove unique phone ownership from `participants`
- stop resolving inbound identity from `participants.phone_number`
- eventually deprecate `participant_active_context`
- retain `participants` only if needed as a compatibility view/table, otherwise collapse it

## Code Areas That Must Change

### Highest impact

- [`careos/db/repositories/store.py`](/home/kumarmankala/careos/careos/db/repositories/store.py)
- [`careos/services/onboarding_service.py`](/home/kumarmankala/careos/careos/services/onboarding_service.py)
- [`careos/services/identity_service.py`](/home/kumarmankala/careos/careos/services/identity_service.py)
- [`careos/gateway/routes/twilio_gateway.py`](/home/kumarmankala/careos/careos/gateway/routes/twilio_gateway.py)

### Also impacted

- scheduler recipient discovery and push routing
- internal API routes that expose caregiver links
- any route that currently expects `participant_id` to imply one tenant and one phone owner

## Verification Plan

### Must-pass behavioral cases

1. Same phone is patient in tenant A and caregiver in tenant B
2. Same phone is observer for patient A and primary caregiver for patient B
3. Same phone is caregiver for two patients in one tenant
4. Inbound message from a phone with:
- one membership and one patient: auto resolve
- one membership and multiple patients: require patient selection
- multiple memberships and one patient each: require workspace selection
5. Invite flow can reuse existing phone from another tenant without data collision
6. Scheduler sends reminders to the correct membership-linked recipients only
7. Audit tables still preserve who acted and in which tenant context

### Recommended test slices

- store-layer migration/backfill tests
- identity resolution matrix tests
- onboarding invite tests across tenants
- gateway command tests for membership selection
- scheduler recipient resolution tests

## Risks

### 1. Silent context confusion

If workspace selection is implicit when it should be explicit, a user may act on the wrong patient.

Mitigation:

- fail closed when multiple memberships are plausible
- force explicit selection

### 2. Audit ambiguity

If actor references move carelessly, old events may lose tenant context.

Mitigation:

- prefer additive actor columns during migration
- do not overwrite old participant IDs in historical rows

### 3. Notification leakage across tenants

If recipient resolution uses global identity without tenant membership checks, reminders could cross family boundaries.

Mitigation:

- all recipient resolution must be patient-link driven
- never send from phone-only identity lookup

## Recommended Implementation Order

1. Add schema and backfill machinery
2. Add dual-read identity resolution
3. Migrate invite flow to global identity + tenant membership
4. Migrate active context to membership scope
5. Add multi-workspace selection UX
6. Migrate actor/audit references
7. Remove legacy phone uniqueness assumptions

## Immediate Next Slice

The next practical engineering slice is:

1. add `person_identities` and `tenant_memberships`
2. backfill existing `participants`
3. teach onboarding invite flow to reuse an existing phone across tenants by creating a new tenant membership instead of hard-failing

That gives you the first real product unlock without yet rewriting every audit table.
