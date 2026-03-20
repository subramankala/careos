# CareOS Sovereign Agent Architecture

Last updated: 2026-03-20 UTC

## Goal

Support personal sovereign agents as a first-class user-facing surface for CareOS, alongside native CareOS channels such as Twilio WhatsApp, voice, and future channels.

The design must support two kinds of users:

1. Users with a personal sovereign agent
- CareOS should use that agent as the primary personalization and interaction layer for that actor and role.

2. Users without a personal sovereign agent
- CareOS should still provide meaningful personalization through the existing OpenClaw plus CareOS stack.
- These users may need to add context manually through CareOS commands such as `remember`, `note`, `plan`, and future equivalents.

This document is an architecture proposal only. It does not assume implementation yet.

## Product Position

CareOS should not be designed as:

- Twilio-first with sovereign agents as an integration add-on

It should be designed as:

- CareOS Core plus multiple first-class user surfaces

Those surfaces include:

- `sovereign_agent`
- `twilio_whatsapp`
- later `voice`
- later `imessage`
- later dashboard-driven direct interaction

Twilio remains a valid default surface. Sovereign agents become a rich, first-class surface for users who have them.

## Key Design Principle

The sovereign agent should be the personalization layer.

CareOS should be:

- the care workflow layer
- the care policy layer
- the care operational state layer
- the audit layer

This means:

- CareOS decides what must happen and what the risk/policy posture is
- the sovereign agent decides how to engage the user personally when policy allows it
- if no sovereign agent exists, CareOS performs that interaction through its native OpenClaw plus channel stack

## User Experience Model

For a given user, CareOS should resolve a preferred interaction surface using:

- `person_id`
- `acting_role`
- `patient_context`

Suggested preference model:

- `person_id`
- `role`
- `patient_id` nullable
- `preferred_surface`
- `fallback_surface`
- `agent_endpoint_id` nullable
- `status`

This allows:

- one person as patient to prefer sovereign agent
- the same person as caregiver for another patient to prefer Twilio
- different preferences by role and patient context

## Core Architecture

### 1. CareOS Core

This remains the canonical home for:

- care plans
- schedule and adherence state
- care team and assignments
- care-relevant context
- audit trail
- risk and policy metadata

### 2. Surface Router

This is the surface-selection layer.

Responsibilities:

- resolve the acting person
- resolve the acting role for the current patient
- resolve the preferred interaction surface
- decide whether the request goes to:
  - sovereign agent
  - native CareOS interaction layer

The router should not contain care logic. It should only route according to preference and policy.

### 3. Sovereign Agent Gateway

This is the generic agent integration layer.

Requirements:

- generic protocol, not hardcoded to one implementation
- OpenClaw-compatible first
- supports:
  - structured action requests
  - structured event delivery
  - structured context exchange

This is where CareOS can speak to OpenClaw-backed sovereign agents without locking itself to OpenClaw forever.

### 4. Native CareOS Personalization Layer

This is the existing OpenClaw plus CareOS path used when:

- no sovereign agent exists
- the actor prefers native CareOS
- policy requires fallback to a native surface
- the sovereign agent is unavailable

This layer should continue to provide decent personalization by using:

- durable clinical facts
- short-lived observations
- day-scoped plans
- care team assignments
- medication and schedule grounding

Users without a sovereign agent should not get a worse clinical experience. They should only lose the richer personal context that their private agent may already know.

### 5. Context Reflection Layer

This is the bidirectional context boundary between sovereign agents and CareOS.

Purpose:

- reflect relevant personal context from the sovereign agent into CareOS
- expose care-relevant events from CareOS back to the sovereign agent

This should not become generic memory sync.

## Canonical Ownership Model

### CareOS canonical

CareOS should remain canonical for:

- care plans
- care schedule
- adherence state
- care team and responsibility assignments
- care workflow events
- care-specific audit history
- care-specific persistent context derived from external sources when it affects care operations

### Sovereign agent canonical

The sovereign agent should remain canonical for:

- personal memory
- broader life context
- personal calendar
- non-care preferences
- workload and attention state
- contextual signals outside CareOS

### Shared runtime context

Some context should be exchangeable but not duplicated permanently.

Examples:

- availability
- calendar busy windows
- travel
- transport barriers
- financial stress
- food access constraints
- caregiver workload
- household support context
- SDOH signals

## Context Reflection Model

CareOS should support three context modes.

### 1. Referenced context

- fetched from sovereign agent on demand
- not stored permanently in CareOS

Examples:

- current calendar busyness
- short-term availability

### 2. Mirrored ephemeral context

- reflected into CareOS with TTL
- used for planning and personalization

Examples:

- busy until 5 PM
- traveling today
- poor sleep last night
- high stress today

### 3. Persisted care-relevant derived context

- stored in CareOS because it materially affects care
- remains auditable

Examples:

- transport barrier affecting adherence
- medication affordability concern
- limited caregiver coverage today
- food insecurity affecting meal-dependent medications

## External Context Requirements

Any reflected context item should carry:

- `subject_person_id`
- `subject_patient_id` nullable
- `source_agent_id`
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

### Suggested `context_scope`

- `personal`
- `caregiving`
- `patient_specific`

### Suggested `verification_state`

- `agent_reported`
- `user_confirmed`
- `caregiver_confirmed`
- `system_verified`

### Suggested `operational_effect`

- `advice_only`
- `planning`
- `scheduling`
- `routing`

This is critical because you want personal context, including SDOH, to potentially affect schedule behavior. That cannot be allowed by default for every context type.

## Bidirectional Interaction Types

There are three distinct interaction types between sovereign agents and CareOS.

### 1. Sovereign agent to CareOS action execution

Examples:

- get schedule
- mark task done
- delay or reschedule a task
- update care team responsibility
- create a care task
- add or update care context

### 2. Sovereign agent to CareOS context reflection

Examples:

- calendar slots
- busyness
- transport access
- affordability concerns
- caregiver availability
- personal observations relevant to care

### 3. CareOS to sovereign agent event delivery

Examples:

- due reminder
- missed task
- critical alert
- low adherence event
- care team change
- planner clarification need

These should be modeled separately in protocol and policy.

## Generic Sovereign Agent Protocol

Even if OpenClaw is the first implementation, CareOS should define a generic protocol.

### Agent to CareOS commands

- `resolve_context`
- `get_today`
- `get_status`
- `get_team`
- `get_assignments`
- `create_task`
- `complete_task`
- `update_task`
- `update_care_context`
- `propose_care_change`
- `ack_event`

### CareOS to agent events

- `due_event`
- `missed_event`
- `critical_event`
- `summary_event`
- `assignment_change_event`
- `context_request_event`
- `policy_escalation_event`

### Agent context push types

- `calendar_context`
- `availability_context`
- `sdoh_context`
- `preference_context`
- `engagement_context`

OpenClaw compatibility should be first-class, but the contract should not be OpenClaw-specific.

## Native Personalization Without Sovereign Agent

This is a critical requirement.

Users without a sovereign agent should still get personalization through CareOS itself.

That means the native OpenClaw plus CareOS path should remain capable of:

- using care-context grounding
- reasoning from durable facts
- reasoning from observations
- reasoning from day plans
- using care-team ownership context
- adapting message content and suggestions

The difference is:

- sovereign-agent users get richer reflected personal context automatically
- non-sovereign users may need to provide more context manually inside CareOS

The clinical care engine should remain the same.

## Policy Architecture

Use Cedar as the governing layer.

This is a good fit because you want one policy layer to govern:

- access
- action permissions
- autonomy level
- operational effect of reflected context
- fallback behavior

### Policy domains for Cedar

#### 1. Access policy

Examples:

- can this person read this patient’s care data?
- can this sovereign agent act for this person in this role?

#### 2. Action policy

Examples:

- can this agent mark this task done?
- can this actor edit care-team assignments?
- can this source create care context items?

#### 3. Autonomy policy

Examples:

- can this action be executed automatically?
- must it be proposed and confirmed?
- can the sovereign agent act autonomously for low-risk items?

#### 4. Operational-effect policy

Examples:

- can this reflected context affect only conversation?
- can it affect planner decisions?
- can it affect scheduler timing?
- can it affect routing or escalation?

This matters because not every imported context item should be allowed to alter care operations.

## Risk And Policy Envelope

CareOS should pass a policy envelope with any event or action handed to a sovereign agent.

Suggested fields:

- `clinical_risk`
- `time_rigidity`
- `criticality_class`
- `escalation_required`
- `delegation_allowed`
- `autonomy_allowed`
- `fallback_required_if_unresolved`

This lets CareOS stay generic while allowing the sovereign agent to personalize the delivery.

Example:

- CareOS declares an item high risk and rigid
- sovereign agent decides how to engage the user personally
- if unresolved within policy limits, CareOS falls back or escalates through native channels

This is the right separation between governance and personalization.

## Fallback Model

Fallback must always exist.

If preferred surface is `sovereign_agent` but:

- the agent is unavailable
- the agent times out
- policy requires native escalation
- the actor has no sovereign agent configured

then CareOS should route to the fallback surface, typically:

- `twilio_whatsapp`
- later `voice`

This keeps care operations resilient.

## Identity Model Implications

Because sovereign agents are person-based, not patient-based, the integration should align with the person identity direction, not patient-bound channel identities.

That means:

- a sovereign agent belongs to a person identity
- the person may act as patient for self
- the same person may act as caregiver for another patient
- the preferred surface can vary by role and patient context

This fits the existing multi-tenant/person-identity direction.

## Recommended Implementation Order

### Phase 1: Surface preference and agent registration

- add sovereign-agent registration
- add per-person and per-role surface preference
- keep native routing as fallback

### Phase 2: Generic agent gateway

- define generic sovereign-agent protocol
- implement OpenClaw-compatible adapter first
- expose structured CareOS actions

### Phase 3: Context reflection

- add reflected external context model
- add TTL, confidence, verification state, and effect classification
- begin with advisory and planning context only

### Phase 4: Event delivery

- push due, missed, critical, and summary events to sovereign agents
- add fallback if unavailable

### Phase 5: Cedar policy enforcement

- use Cedar to govern access, actions, autonomy, and context effect
- make policy central before operational influence expands

### Phase 6: Operational influence

- allow reflected context to affect planner, scheduler, and routing where policy permits
- preserve fallback to native CareOS surfaces

## Complexity Assessment

This is a high-leverage but high-complexity platform move.

### Data model complexity: Medium-High

Why:

- new preference, agent registration, and reflected-context models are needed
- person identity and patient context boundaries must stay clean

### Surface routing complexity: Medium

Why:

- the routing concept itself is simple
- but it must be done per person, role, and patient context

### Cedar/policy complexity: High

Why:

- policy now governs more than access control
- autonomy, fallback, and context effect become part of policy

### Scheduler/planner impact: High

Why:

- reflected context may eventually alter operational behavior
- that must be done in a controlled and auditable way

### Native fallback complexity: Medium

Why:

- users without sovereign agents still need a personalized experience
- the native OpenClaw plus CareOS path must remain a serious product path, not a degraded fallback

## Recommendation

Treat sovereign agents as the primary rich interaction layer for users who have them.

Treat native CareOS plus OpenClaw as the primary rich interaction layer for users who do not.

Use one care core, one governing policy layer, and multiple surfaces.

Do not:

- sync arbitrary memory
- make Twilio the hidden canonical UX
- overfit routing or context behavior to one example
- allow reflected context to alter operations without policy and audit controls

## Immediate Next Step

If this architecture is accepted, the next artifact should be a phased implementation plan covering:

- surface preference model
- sovereign-agent registration
- generic protocol
- context reflection schema
- Cedar decision points
- native fallback behavior
