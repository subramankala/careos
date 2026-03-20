# CareOS Personal Agent Experience Manual

Last updated: 2026-03-20 UTC

Related architecture:

- [SOVEREIGN_AGENT_ARCHITECTURE.md](/home/kumarmankala/careos/SOVEREIGN_AGENT_ARCHITECTURE.md)
- [SOVEREIGN_AGENT_PHASED_PLAN.md](/home/kumarmankala/careos/SOVEREIGN_AGENT_PHASED_PLAN.md)

## Purpose

This document defines the intended user experience model for CareOS once personal-agent support is available.

It is not a technical implementation guide. It is a product and UX reference for:

- product strategy and scope decisions
- user journey design
- onboarding and support documentation
- validating whether the architecture produces the intended experience
- aligning engineering, design, clinical, and operations teams on what the user experience must guarantee

## Product Thesis

Every CareOS user should receive a personalized care experience.

What changes is not whether personalization exists, but where it is mediated:

- directly in native CareOS
- through a connected personal agent

CareOS always remains the system of record for:

- care state
- workflow state
- policy enforcement
- escalation rules
- responsibility and assignment state
- auditability of clinically relevant actions

A connected personal agent may personalize how care is delivered, but it does not replace CareOS as the source of care truth.

## Core Experience Principle

CareOS should support a personalized care experience for every user, whether or not they use a personal agent.

There are two primary personalization paths:

### 1. Personal-agent-mediated personalization

The personal agent is the user’s preferred interaction surface and personalization layer.

### 2. Native CareOS personalization

CareOS, supported by OpenClaw, provides personalization directly for users who:

- do not have a connected personal agent
- prefer native CareOS for a given role or context
- need fallback because the personal agent is unavailable
- are in a workflow where policy requires a native CareOS surface

The native path must be a complete and trustworthy care experience, not a degraded backup.

## Non-Negotiable UX Guarantees

A good CareOS experience must guarantee the following:

1. CareOS remains the source of care truth.
   Regardless of which surface the user interacts through, care status, assignments, escalation state, and clinically relevant outcomes remain grounded in CareOS.

2. Users always know who they are acting as and for.
   The current role and active patient context must always be clear.

3. Fallback never feels random.
   If CareOS changes surfaces because a personal agent is unavailable or disallowed for a workflow, the user should understand why.

4. Native CareOS remains first-class.
   Users without a personal agent must still receive a strong, personalized, context-aware care experience.

5. Urgent care rules remain consistent across surfaces.
   Personalization may change communication style and timing within policy limits, but not the underlying enforcement of urgent clinical rules.

6. Actions with clinical impact are attributable and auditable.
   The system must be able to explain what happened, through which surface, for which person, in which role, and with what resulting care state.

7. Mixed-role use should feel natural, not fragmented.
   The same person may prefer different surfaces for different roles or patient contexts without feeling like they are switching between unrelated products.

## System Responsibility Model

To avoid confusion, CareOS and connected personal agents must have clearly separated responsibilities.

### CareOS always owns

- care plan state
- care schedule and task state
- policy enforcement
- escalation policy and execution
- assignment and responsibility model
- patient and role context resolution
- clinically meaningful status updates
- audit trail and support visibility

### A connected personal agent may own or mediate

- phrasing and communication style
- convenience-oriented planning help
- prioritization support within policy limits
- timing optimization for flexible actions
- bundling care tasks with broader personal context
- user-specific explanation and coaching

### Native CareOS owns when the personal agent is absent, unavailable, or disallowed

- direct interaction with the user
- direct care-context capture
- fallback communication
- task completion confirmation and updates
- clear explanation of why fallback occurred

## Surface Model

CareOS may support multiple user-facing surfaces over time, including:

- connected personal agent
- Twilio WhatsApp
- voice later
- iMessage later
- direct dashboard interactions later

For any interaction, CareOS should resolve the appropriate surface based on:

- the person
- the acting role
- the active patient context
- the preferred surface for that tuple
- the fallback surface for that tuple
- the policy permissions for that workflow

This means the same human may have different preferred experiences in different contexts.

## Actor and Context Model

The same person may interact with CareOS in multiple ways.

### Person

The human being interacting with the system.

### Role

The role the person is currently acting in, such as:

- patient
- caregiver

### Patient context

The patient whose care state is currently active.

### Surface preference

The preferred interaction surface for a given person plus role plus patient context.

### Fallback surface

The backup interaction surface if the preferred one is unavailable or disallowed.

This model allows one person to have different interaction preferences across different roles and patient contexts.

## What Changes for Users

### Before personal-agent support

Users primarily interact through native CareOS channels such as WhatsApp. Personalization is based on context managed inside CareOS, including:

- care schedule
- care-specific durable facts
- observations
- day plans
- care-team ownership context
- OpenClaw grounding inside CareOS

### After personal-agent support

Users may experience CareOS in one of two broad modes.

#### Personal-agent-first

CareOS sends care events, tasks, and policy-bounded instructions to the user’s connected personal agent. The personal agent personalizes how the interaction happens. CareOS remains responsible for care workflow, policy, and escalation.

#### Native-CareOS-first

The user continues to interact directly through native CareOS surfaces such as WhatsApp. CareOS plus OpenClaw provides personalization directly using care-specific context.

These two modes should feel like alternate interaction paths for one coherent product, not two disconnected products.

## What Personalization Looks Like

### With a connected personal agent

Personalization may incorporate broader life context such as:

- calendar busyness
- recent workload
- transport or travel constraints
- caregiver load and stress
- financial friction
- broader personal memory and preferences

### Without a connected personal agent

Personalization may still incorporate strong care-relevant context such as:

- care plan
- medications
- durable care facts
- observations
- day plans
- care-team responsibilities
- user-entered notes and updates

The experience should still feel thoughtful, relevant, and supportive, even if the context available is narrower.

## Permission, Consent, and Trust Model

A connected personal agent increases personalization power, but must not blur the user’s understanding of responsibility or boundaries.

The experience should make the following clear:

- what CareOS is sharing with the connected personal agent
- what the personal agent may send back to CareOS
- what actions the personal agent can help coordinate
- what actions require explicit confirmation
- which actions are only allowed in native CareOS
- when a user is acting for themselves versus acting for another patient

### UX principle

Users should understand that a connected personal agent may help mediate and personalize care interactions, but CareOS still governs the care workflow.

### Policy principle

Clinical rigidity, urgency, escalation, and auditability are not optional and do not move out of CareOS.

### Consent expectations

The setup and settings experience should let the user understand and control:

- whether a personal agent is connected
- which role uses that agent
- what the fallback surface is
- what categories of context may be reflected into CareOS
- what categories of actions the personal agent may coordinate or execute
- how to revoke the connection or change the preference later

## Decision Categories for Personalization

Not all care interactions should be equally flexible.

### Category A: Fixed clinical actions

Examples:

- time-rigid medication tasks
- urgent escalation steps
- policy-mandated check-ins

User experience implication:

- personalization can change phrasing, explanation, and compliant reminder style
- personalization should not silently reinterpret the underlying action

### Category B: Flexible operational actions

Examples:

- scheduling a non-urgent follow-up
- rearranging a flexible care task window
- coordinating a caregiver handoff

User experience implication:

- timing optimization, delegation support, and calendar-aware planning are appropriate

### Category C: Contextual coaching and support

Examples:

- helping the user understand priorities
- adapting tone based on stress or workload
- planning the day around care tasks

User experience implication:

- broad personalization is appropriate as long as it does not silently alter care state

### Category D: Escalation-required events

Examples:

- repeated missed critical medication
- unsafe symptom state
- emergency rules

User experience implication:

- the system may personalize explanation and support, but it should not hide the fact that escalation is happening

## Canonical Experience Modes

## 1. Patient with a connected personal agent

### Example

Ravi is a 72-year-old patient who already uses an OpenClaw-backed personal agent for calendar, planning, reminders, and day-to-day coordination.

### Preferred setup

- role: patient
- preferred surface: connected personal agent
- fallback: CareOS WhatsApp or voice

### Expected experience

Ravi does not need to interact with CareOS directly most of the time.

Instead:

- CareOS sends care events to his connected personal agent
- the personal agent uses his existing schedule and preferences to personalize engagement
- CareOS still determines what matters clinically and which escalation rules apply

### Example interaction

CareOS determines that a medication is due and policy says it is important and time-rigid.

The personal agent may say:

> You are between meetings and this medication matters today. Take it now if you can. If you need, I can help you adjust the rest of your afternoon.

If unresolved:

- CareOS may escalate according to policy
- CareOS may fall back to WhatsApp or voice if required

### What Ravi should not need to do

- duplicate his calendar in CareOS
- manually restate every personal preference that his connected personal agent already knows

## 2. Patient without a connected personal agent

### Example

Lakshmi is a patient who uses WhatsApp but does not have a connected personal agent.

### Preferred setup

- role: patient
- preferred surface: native CareOS

### Expected experience

Lakshmi still receives a personalized care experience through native CareOS plus OpenClaw.

That personalization comes from care-relevant context available inside CareOS, such as:

- care schedule
- medications
- durable facts
- observations
- day plans
- care-team context

### How she provides context

She may say things like:

- `remember I had a stent placed in February`
- `note slept only 4 hours last night`
- `plan doctor visit at 4 pm today`

### Example interaction

Lakshmi asks:

- `Which medicines are most important for me not to miss?`
- `Given my sleep last night, should I take it easy today?`

CareOS plus OpenClaw answers using the care-specific context available inside CareOS.

### Product requirement

Lakshmi should not feel like she is using a second-class product. Native CareOS must remain a complete and trustworthy care experience.

## 3. Caregiver with a connected personal agent

### Example

Anita is a daughter caring for her father. She uses a connected personal agent for her own work calendar, family planning, and day-to-day coordination.

### Preferred setup

- role: caregiver
- patient context: father
- preferred surface: connected personal agent

### Expected experience

When Anita is acting as caregiver:

- CareOS routes patient-care interactions to her connected personal agent when allowed
- the personal agent factors in Anita’s availability, workload, and travel constraints
- CareOS pushes due, missed, and assignment-related events to that surface when appropriate

### Example interaction

Anita’s personal agent receives:

- a missed appointment alert
- a medication reminder for her father
- a care-team assignment change

The personal agent may help her triage:

- what is critical
- what can wait
- what should be delegated

### Important UX detail

The personal agent belongs to Anita as a person, not to her father as a patient.

The experience should therefore feel like:

**You are now acting for your father**

rather than:

**You are entering a different app identity**

## 4. Caregiver without a connected personal agent

### Example

Suresh helps his mother with medications and appointments but only uses WhatsApp.

### Preferred setup

- role: caregiver
- preferred surface: native CareOS WhatsApp

### Expected experience

Suresh still gets:

- schedule access
- care-team visibility
- category ownership visibility
- assignment commands
- OpenClaw-grounded answers inside CareOS

### Example interactions

He can ask:

- `team`
- `who handles medications`
- `assign medications to 1 as responsible`

He can also provide care context manually:

- `note mother is tired today`
- `plan we will be out this afternoon`

## 5. Mixed-role user

### Example

Meera is both:

- a patient for her own diabetes care
- a caregiver for her husband’s post-surgery recovery

### Preferred setup

- as patient for self: connected personal agent
- as caregiver for husband: WhatsApp

### Expected experience

CareOS allows different surfaces for different roles and patient contexts.

When Meera is managing her own care:

- her connected personal agent is primary

When she is managing her husband’s care:

- native CareOS WhatsApp is primary

This must feel like a natural context shift, not account fragmentation.

## Experience Matrix

### Patient plus connected personal agent

Expected characteristics:

- richest personalization
- less manual context entry
- care events routed to personal agent first
- native fallback if needed

### Patient plus no connected personal agent

Expected characteristics:

- strong native CareOS personalization
- care-specific manual context entry when helpful
- WhatsApp remains a viable primary surface

### Caregiver plus connected personal agent

Expected characteristics:

- richer triage and scheduling help
- care events mediated through caregiver context when allowed
- strong native fallback for urgent or disallowed cases

### Caregiver plus no connected personal agent

Expected characteristics:

- native CareOS remains fully usable
- care-team and assignment flows remain strong
- manual care-context entry remains possible

## Moments of Truth

These are the key moments where trust is won or lost. The product must handle them deliberately.

### 1. First-time setup

The user should understand:

- what a connected personal agent is
- that it is optional
- what CareOS still owns
- what the preferred surface means
- what fallback means

### 2. First care event through the connected personal agent

The user should understand:

- that the message originated from CareOS
- that the personal agent is helping personalize the interaction
- what action is being requested

### 3. First fallback event

If CareOS falls back to WhatsApp or voice, the user should understand:

- why the preferred surface was not used
- that the care task is still active
- what the next step is

### 4. Role switch

When the same person changes role or active patient context, the experience should make that shift explicit.

### 5. Urgent escalation

The experience should remain calm and understandable, but should not hide or soften the fact that the event is urgent.

### 6. Wrong-context prevention

If the system suspects the user is acting in the wrong patient context, it should slow down and make the context explicit before allowing clinically meaningful actions.

## Typical User Journeys

## Journey 1: Personal-agent-first medication support

1. CareOS identifies a due care task.
2. Policy says personal-agent routing is allowed and preferred.
3. CareOS sends the event and policy-bounded envelope to the connected personal agent.
4. The personal agent personalizes the interaction.
5. If the user acts, CareOS receives the outcome.
6. If the user does not act and policy requires escalation, CareOS falls back or escalates directly.

## Journey 2: Native WhatsApp care management

1. User sends a question or status update.
2. CareOS resolves native CareOS as the active surface.
3. Native CareOS plus OpenClaw handles personalization.
4. User can add care context manually with commands such as `remember`, `note`, or `plan`.
5. CareOS updates care context and continues the interaction.

## Journey 3: Mixed-role context switch

1. The same person interacts with CareOS.
2. CareOS resolves the current role and active patient context.
3. Surface preference is applied for that combination.
4. Interaction flows through the connected personal agent or native CareOS accordingly.
5. The user can clearly see whom they are acting for.

## Journey 4: Personal agent unavailable

1. CareOS determines that the preferred surface is unavailable.
2. CareOS routes to fallback according to policy and user settings.
3. The user receives a message that explains the change in surface.
4. CareOS preserves the task context and requested action.
5. The user continues without needing to reconstruct context manually.

## Role Clarity and Safeguards

Mixed-role support requires more than passive clarity. It requires active safeguards.

The experience should include patterns such as:

- persistent indication of the active role
- persistent indication of the active patient context
- explicit framing such as **acting for Ravi**
- confirmation for clinically meaningful actions in caregiver mode when appropriate
- context-switch flows that make the patient transition obvious
- visible recent actions tied to the active patient

The goal is to prevent silent mistakes, especially when the same human is moving quickly between self-care and caregiving tasks.

## Setup and Preference Experience

The setup flow should eventually let the user:

1. connect or decline a personal agent
2. choose preferred surface by role
3. choose fallback surface by role
4. review what information may be shared
5. review what actions the personal agent may coordinate
6. confirm that CareOS remains the care source of truth

The settings experience should later let the user update:

- preferred surface
- fallback surface
- permissions and consent
- reflected-context categories
- revocation of the personal-agent connection

## Failure and Recovery Modes

The experience should explicitly account for failure modes, not just ideal paths.

### Personal agent unavailable

CareOS should explain:

- that the preferred surface could not be used
- which fallback surface is being used
- what care action is still active

### Stale or conflicting reflected context

CareOS should be able to:

- ignore expired context
- ask for clarification when reflected context conflicts with active care reality
- avoid silently changing care state based on stale signals

### Policy override by CareOS

If the personal agent or preferred surface cannot be used because policy requires native escalation, the experience should say so clearly.

### Wrong role or wrong patient context

The experience should slow down, clarify context, and avoid silent clinically meaningful actions.

## What Users May Need to Configure

### Users with connected personal agents

They may need to configure:

- preferred surface by role
- fallback surface by role
- whether some categories of actions may be coordinated through the personal agent
- agent connection or registration
- basic notification preferences

### Users without connected personal agents

They may need to configure:

- preferred native channel
- reminder preferences
- care-specific context through native commands or setup flows

## Example Commands and Interactions

## Native CareOS examples

Patients or caregivers may say:

- `remember recent procedure: stent placed on 2026-02-26`
- `note slept 4 hours last night`
- `plan doctor visit at 4 pm today`
- `team`
- `assign medications to 1 as responsible`
- `who handles medications`

These commands remain important even in a world with connected personal agents, because not every user will use one.

## Connected personal agent examples

The user may never type a CareOS command directly. Instead, the connected personal agent may say:

- CareOS says your 8 PM medication is due.
- You are busy at 4 PM and also have a care task then. Want me to help reschedule the flexible item?
- For your father, CareOS says medications are assigned to you and appointments are assigned to your brother.

## Support and Observability Requirements

Support and operations teams need visibility into what the user actually experienced.

Support tooling should make it possible to understand:

- which surface was preferred
- which surface was actually used
- whether a connected personal agent was active
- whether fallback occurred
- why fallback occurred
- what context came from native CareOS entry versus personal-agent mediation
- what actions were taken and how they changed care state

This is essential for debugging trust, adoption, and patient-safety issues.

## Recommended Product Language

Preferred user-facing language:

- personal agent
- preferred interaction surface
- fallback surface
- care personalization
- acting for [patient name]

Avoid user-facing language that sounds infrastructural, such as:

- endpoint
- adapter
- routing tuple
- transport boundary

Internally, the term `sovereign agent` may still be useful in architecture and strategy documents. User-facing experiences should generally prefer `personal agent` unless there is a specific reason to emphasize sovereignty or user control explicitly.

## Definition of a Good Experience

The experience is good if:

- users with a connected personal agent feel that CareOS works through their preferred personal layer
- users without a connected personal agent still feel understood and supported
- the same human can use different surfaces in different roles without confusion
- urgent care requirements remain consistently enforced
- fallback behavior feels safe and understandable
- clinically meaningful actions remain attributable and auditable
- users know who they are acting as and for at all times

## Immediate Product and UX Next Steps

The next step is not just to wait for implementation. This model should now be turned into testable product artifacts.

Priority next artifacts:

1. setup flow for connecting a personal agent
2. role and surface preference model
3. fallback explanation patterns
4. context-switch UX for mixed-role users
5. permission and consent UX
6. canonical conversation transcripts for each major mode
7. support and audit-view requirements
8. success metrics for comprehension, completion, fallback recovery, and role-switch accuracy

Once phase 1 is implemented, this document should be updated with:

- concrete setup screens or commands
- exact role preference choices
- fallback message examples
- screenshots or sample conversations
- observed UX learnings from real users
