# CareOS Sovereign Agent Phased Plan

Last updated: 2026-03-20 UTC

Related architecture: [SOVEREIGN_AGENT_ARCHITECTURE.md](/home/kumarmankala/careos/SOVEREIGN_AGENT_ARCHITECTURE.md)

## Goal

Introduce sovereign agents as a first-class user-facing surface in CareOS while preserving:

- native CareOS plus OpenClaw personalization for users without a sovereign agent
- safe operational policy boundaries
- clean fallback behavior

This plan assumes:

- the sovereign agent is person-based
- preference should be resolved per person and role, optionally per patient context
- OpenClaw is the first supported sovereign-agent implementation
- the protocol should still be generic

## Design Constraints

The implementation must preserve these truths:

1. CareOS remains canonical for care workflow and care state.
2. Sovereign agents remain canonical for broader personal context.
3. Native CareOS plus OpenClaw remains a real personalization path for non-sovereign users.
4. Cedar is the governing layer for access, autonomy, operational effect, and fallback.

## Phase 0: Preserve The Native Path

Status: must remain true throughout every phase

Users without sovereign agents should still get:

- OpenClaw-grounded answers
- use of durable clinical facts
- use of observations and day plans
- care-team ownership context
- native channel fallback such as Twilio WhatsApp

This is not an implementation phase. It is a non-regression rule.

## Phase 1: Surface Preference And Agent Registration

### Objective

Add the minimum routing model needed to choose:

- `sovereign_agent`
- `twilio_whatsapp`
- future surfaces

for a given person and role.

### Scope

Add:

- `agent_endpoints`
- `surface_preferences`

Suggested `agent_endpoints` fields:

- `id`
- `person_identity_id`
- `agent_type`
- `endpoint_url`
- `auth_mode`
- `auth_metadata`
- `status`
- `created_at`
- `updated_at`

Suggested `surface_preferences` fields:

- `id`
- `person_identity_id`
- `role`
- `patient_id` nullable
- `preferred_surface`
- `fallback_surface`
- `agent_endpoint_id` nullable
- `status`
- `created_at`
- `updated_at`

### Deliverables

- schema
- store/service support
- internal API endpoints
- routing read helper that resolves preferred surface

### Not in this phase

- no outbound event push yet
- no context reflection yet
- no scheduler behavior change yet

## Phase 2: Generic Sovereign-Agent Gateway

### Objective

Expose a generic action/event boundary for sovereign agents.

### Scope

Add a generic gateway layer with:

- action execution requests
- event delivery requests
- capability discovery
- auth/authz integration points

OpenClaw should be the first adapter, not the only design assumption.

### Initial capabilities

- `resolve_context`
- `get_today`
- `get_status`
- `get_team`
- `get_assignments`
- `complete_task`
- `update_task`
- `create_task`
- `get_context`

### Deliverables

- protocol spec
- OpenClaw-compatible adapter
- internal action dispatch service
- audit source tagging with `surface=sovereign_agent`

### Not in this phase

- no broad reflected-context write path yet
- no scheduler routing changes yet

## Phase 3: Reflected Context Foundation

### Objective

Allow sovereign agents to reflect care-relevant personal context into CareOS without turning CareOS into a generic memory store.

### Scope

Add a first-class reflected context model.

Suggested table:

- `external_context_items`

Suggested fields:

- `id`
- `subject_person_identity_id`
- `subject_patient_id` nullable
- `source_agent_endpoint_id`
- `context_type`
- `context_scope`
- `summary`
- `value_json`
- `effective_at`
- `expires_at`
- `confidence`
- `verification_state`
- `operational_effect`
- `status`
- `created_at`
- `updated_at`

### Initial supported context types

- `calendar_context`
- `availability_context`
- `sdoh_context`
- `engagement_context`
- `preference_context`

### Initial policy boundary

Only allow:

- `advice_only`
- `planning`

in the first reflection slice.

Do not allow reflected context to affect scheduler routing yet.

### Deliverables

- schema
- store/service support
- ingestion API
- TTL and expiry handling
- source and verification metadata

## Phase 4: Sovereign-Agent Event Delivery

### Objective

Let CareOS push care events to sovereign agents when the user’s preferred surface is `sovereign_agent`.

### Scope

Publish events like:

- due reminder
- missed task
- critical event
- daily summary
- low adherence alert
- team assignment change

### Required behavior

- policy envelope attached to each event
- fallback if sovereign agent is unavailable
- audit log for delivery attempt and fallback result

### Deliverables

- event publisher
- retry/fallback behavior
- OpenClaw-compatible event format

## Phase 5: Cedar Decision Layer

### Objective

Centralize policy decisions in Cedar.

### Scope

Use Cedar for:

- access policy
- action permissions
- autonomy policy
- reflected-context effect policy
- fallback/escalation policy

### Example Cedar questions

- can this sovereign agent act for this person in this role?
- can this request be executed automatically?
- can this reflected context affect planning?
- can this reflected context affect scheduling?
- should unresolved high-risk rigid items fall back to native channels?

### Deliverables

- Cedar schema/entities
- decision points in routing
- decision points in context ingestion
- decision points in action execution

## Phase 6: Operational Influence

### Objective

Allow reflected context to influence CareOS operations when policy allows it.

### Scope

Apply reflected context to:

- planner behavior
- scheduling suggestions
- delivery/routing decisions
- escalation behavior

### Important rule

Start with generic effects, not example-specific ones.

For example:

- availability constraints
- transport constraints
- affordability constraints
- caregiver load constraints

should be modeled generically and only then used by planners or schedulers.

### Deliverables

- planner integration
- scheduler integration
- source-aware explanation paths

## Routing Model

At runtime, CareOS should resolve:

1. `person_identity`
2. `role`
3. `patient_context`
4. `preferred_surface`
5. Cedar policy decision

Then route to:

- sovereign-agent path
- native CareOS plus OpenClaw path
- native Twilio path

### Fallback rules

Fallback should happen when:

- no sovereign agent exists
- preferred surface is native
- sovereign agent is unavailable
- Cedar requires native escalation

## Native Non-Sovereign Personalization Plan

This must be preserved as a first-class path.

### Native personalization inputs

- durable clinical facts
- observations
- day plans
- care-team assignments
- medication grounding
- care schedule and adherence state

### User experience assumption

Users without a sovereign agent may provide more context manually, for example:

- `remember ...`
- `note ...`
- `plan ...`
- future structured commands for availability, finances, transport, and caregiver burden

### Requirement

Do not let sovereign-agent support degrade the native personalization path.

The two paths differ in where context comes from, not in whether personalization exists at all.

## Suggested Early Schema Order

Recommended migration order:

1. `0014_agent_endpoints.sql`
2. `0015_surface_preferences.sql`
3. `0016_external_context_items.sql`
4. Cedar policy tables/config support if needed locally

The exact numbering can change, but the order matters.

## Testing Plan

### Phase 1 tests

- preference resolution by person and role
- fallback surface behavior
- no-agent default path

### Phase 2 tests

- OpenClaw-compatible sovereign-agent adapter
- action dispatch
- audit tagging

### Phase 3 tests

- reflected context TTL
- effect classification
- source metadata
- expiry behavior

### Phase 4 tests

- due-event delivery to sovereign agent
- fallback to Twilio when agent unavailable
- audit of both attempts

### Phase 5 tests

- Cedar allow/deny outcomes
- autonomy thresholds
- context-effect decisions

### Phase 6 tests

- planner behavior changes only when policy allows
- scheduler behavior changes only when policy allows
- native path remains stable without a sovereign agent

## Complexity Assessment

### Highest complexity

- Cedar decision integration
- reflected-context operational effect rules
- safe scheduler fallback behavior

### Medium complexity

- surface preference routing
- generic agent gateway
- event delivery model

### Lower complexity

- registration and preference storage
- native path preservation if kept explicit in tests

## Recommended Next Implementation Step

Implement Phase 1 first.

That means:

- agent registration
- surface preferences
- routing resolution service
- no change to planner/scheduler behavior yet

This is the right first step because it lets CareOS know:

- who has a sovereign agent
- which role should use it
- when to use the native path instead

without taking on context reflection or Cedar wiring too early.

## Definition Of Done For Phase 1

Phase 1 is done when:

- a person can have a sovereign-agent endpoint registered
- a preferred surface can be set per role, optionally per patient
- CareOS can resolve whether to use `sovereign_agent` or native routing
- users without sovereign agents still use the native OpenClaw plus CareOS path
- no existing Twilio behavior regresses
