# CareOS Sovereign Agent User Experience Manual

Last updated: 2026-03-20 UTC

Related architecture:

- [SOVEREIGN_AGENT_ARCHITECTURE.md](/home/kumarmankala/careos/SOVEREIGN_AGENT_ARCHITECTURE.md)
- [SOVEREIGN_AGENT_PHASED_PLAN.md](/home/kumarmankala/careos/SOVEREIGN_AGENT_PHASED_PLAN.md)

## Purpose

This document describes the intended user experience once sovereign-agent support is implemented in CareOS.

It is not a technical implementation guide. It is a future-state manual for:

- product thinking
- user journey design
- support and onboarding documentation
- validating whether the architecture produces the desired experience

## Core User Experience Principle

CareOS should provide a personalized care experience for everyone.

There are two primary ways that personalization can happen:

1. Through a personal sovereign agent
- the sovereign agent is the user’s preferred interaction and personalization surface

2. Through native CareOS plus OpenClaw
- for users without a sovereign agent
- for users who prefer native CareOS for a given role
- for fallback when the sovereign agent is unavailable or policy requires a native surface

The difference is not whether personalization exists.
The difference is where the personalization layer lives.

## Surface Model

CareOS should support multiple user-facing surfaces:

- sovereign agent
- Twilio WhatsApp
- later voice
- later iMessage
- later direct dashboard interactions

For a given user interaction, CareOS should resolve the preferred surface using:

- the person
- the acting role
- the patient context

This means the same human can have different experiences in different roles.

## What Changes For Users

### Before sovereign-agent support

The user primarily interacts through native CareOS channels such as WhatsApp.
Personalization is based on:

- care schedule
- care context manually entered into CareOS
- durable facts
- observations
- day plans
- OpenClaw grounding inside CareOS

### After sovereign-agent support

The user may interact in one of two broad ways:

1. Sovereign-agent-first
- CareOS sends care tasks, events, and policy envelope to the sovereign agent
- the sovereign agent personalizes how it engages the user
- CareOS remains the care workflow and policy engine

2. Native-CareOS-first
- the user continues to use WhatsApp or another native surface
- CareOS plus OpenClaw provides personalization directly

This model should feel continuous to the user, not like two disconnected products.

## User Types

The intended experience is different for different user types.

### Patient

The patient is the person receiving the care plan and scheduled care tasks.

### Caregiver

The caregiver is acting on behalf of a patient and may:

- check schedule
- mark tasks done
- adjust tasks
- manage care team responsibilities
- provide care context

### Mixed-role user

The same human may:

- use a sovereign agent for their own self-care as a patient
- use native CareOS for someone else as a caregiver

This is a key scenario and the system should support it naturally.

## Persona 1: Patient With A Sovereign Agent

### Example

Ravi is a 72-year-old patient who already uses an OpenClaw-backed personal agent for his calendar, daily planning, reminders, and general life organization.

### Preferred setup

- role: patient
- preferred surface: sovereign agent
- fallback: CareOS WhatsApp or voice

### Expected experience

Ravi does not need to interact with CareOS directly most of the time.
Instead:

- CareOS sends care events to his sovereign agent
- the sovereign agent knows his calendar, busyness, and preferred style
- the sovereign agent personalizes reminders, explanations, and planning help
- CareOS still decides what is clinically important and what escalation policy applies

### Example experience

CareOS determines that a medication is due and policy says it is important and time-rigid.

The sovereign agent may say:

“You are between meetings and this medication matters today. Take it now if you can. If you need, I can help you adjust the rest of your afternoon.”

If unresolved:

- CareOS may escalate according to policy
- fallback may be WhatsApp or voice

### What Ravi does not need to do

- he does not need to duplicate his calendar in CareOS
- he does not need to manually restate every personal context item if the sovereign agent can reflect it

## Persona 2: Patient Without A Sovereign Agent

### Example

Lakshmi is a patient who uses WhatsApp but does not have a personal sovereign agent.

### Preferred setup

- role: patient
- preferred surface: native CareOS

### Expected experience

Lakshmi still gets a personalized experience through CareOS plus OpenClaw.

The personalization comes from:

- her schedule
- her current medications
- durable facts she or her caregiver added
- short-lived observations
- day plans
- care-team ownership context

### How she provides context

She may say things like:

- `remember I had a stent placed in February`
- `note slept only 4 hours last night`
- `plan doctor visit at 4 pm today`

### Example experience

Lakshmi asks:

- `Which medicines are most important for me not to miss?`
- `Given my sleep last night, should I take it easy today?`

CareOS plus OpenClaw answers based on the care-specific context available inside CareOS.

### What is different from the sovereign-agent path

- the personalization may be less broad because CareOS does not automatically know her full calendar or life context
- she may need to add care-relevant context manually

But:

- the clinical care experience should still be strong
- she should not feel like she has a second-class product

## Persona 3: Caregiver With A Sovereign Agent

### Example

Anita is a daughter caring for her father. She uses a sovereign agent for her own work calendar, family planning, and daily coordination.

### Preferred setup

- role: caregiver
- patient context: father
- preferred surface: sovereign agent

### Expected experience

When Anita is acting as caregiver:

- CareOS should route patient-care interactions to her sovereign agent
- the sovereign agent can factor in her availability, workload, and travel
- CareOS can push due, missed, and assignment-related events to the sovereign agent

### Example experience

Anita’s sovereign agent receives:

- a missed appointment alert
- a medication reminder for her father
- a team assignment change

The sovereign agent may help her triage:

- what is critical
- what can wait
- what should be delegated

### Important detail

The sovereign agent belongs to Anita as a person, not to her father as a patient.
So the experience should feel like:

- “you are now acting for your father”

rather than:

- “you are entering a different app identity”

## Persona 4: Caregiver Without A Sovereign Agent

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

### Example experience

He can ask:

- `team`
- `who handles medications`
- `assign medications to 1 as responsible`

He can also provide care context manually:

- `note mother is tired today`
- `plan we will be out this afternoon`

## Persona 5: Mixed-role User

### Example

Meera is both:

- a patient for her own diabetes care
- a caregiver for her husband’s post-surgery recovery

### Preferred setup

- as patient for self: sovereign agent
- as caregiver for husband: WhatsApp

### Expected experience

CareOS should allow different surfaces for different roles and contexts.

When Meera is managing her own care:

- her sovereign agent is primary

When she is managing her husband’s care:

- WhatsApp is primary

This should feel like a natural context shift, not account fragmentation.

## Experience Matrix

### Patient + sovereign agent

Expected characteristics:

- richest personalization
- less manual context entry
- care events routed to sovereign agent first
- native fallback if needed

### Patient + no sovereign agent

Expected characteristics:

- native CareOS plus OpenClaw personalization
- manual context entry may be needed
- WhatsApp remains a viable main surface

### Caregiver + sovereign agent

Expected characteristics:

- richer triage and scheduling help
- care events can be mediated through the caregiver’s personal context
- strong fallback to native CareOS for high-urgency cases

### Caregiver + no sovereign agent

Expected characteristics:

- native CareOS remains fully usable
- care-team and assignment flows still available
- manual context entry remains possible

## Typical User Journeys

### Journey 1: Sovereign-agent-first medication support

1. CareOS identifies a due care task.
2. Policy says sovereign-agent routing is allowed and preferred.
3. CareOS sends the event and policy envelope to the sovereign agent.
4. The sovereign agent personalizes the interaction.
5. If the user acts, CareOS receives the outcome.
6. If the user does not act and policy requires escalation, CareOS falls back.

### Journey 2: Native WhatsApp care management

1. User sends `schedule` or `status`.
2. CareOS resolves native preferred surface.
3. Native OpenClaw plus CareOS handles personalization.
4. User can add context manually with commands like:
   - `remember`
   - `note`
   - `plan`
5. The same care engine remains active underneath.

### Journey 3: Mixed-role context switch

1. Same person interacts with CareOS.
2. CareOS resolves active patient context and role.
3. Surface router resolves preferred experience for that tuple.
4. Interaction flows through sovereign agent or native path accordingly.

## What Personalization Looks Like

### With a sovereign agent

Personalization can incorporate:

- calendar busyness
- recent workload
- transport situation
- financial friction
- caregiver stress/load
- broader personal memory

### Without a sovereign agent

Personalization can still incorporate:

- care plan
- medications
- durable clinical facts
- observations
- day plans
- care-team responsibilities

The experience should still feel thoughtful and context-aware, even if it is narrower.

## What Users May Need To Configure

### Users with sovereign agents

They may need to configure:

- preferred surface by role
- fallback surface
- whether certain care actions can be autonomous
- agent connection/registration

### Users without sovereign agents

They may need to configure:

- preferred native channel
- reminder preferences
- care-specific context through native commands

## Example Commands And Interactions

### Native CareOS examples

Patient or caregiver may say:

- `remember recent procedure: stent placed on 2026-02-26`
- `note slept 4 hours last night`
- `plan doctor visit at 4 pm today`
- `team`
- `assign medications to 1 as responsible`
- `who handles medications`

These commands remain important even in a sovereign-agent world, because not every user will have an agent.

### Sovereign-agent examples

The user may never type a CareOS command directly.
Instead, the sovereign agent may say:

- “CareOS says your 8 PM medication is due.”
- “You are busy at 4 PM and also have a care task then. Want me to help reschedule the flexible item?”
- “For your father, CareOS says medications are assigned to you and appointments are assigned to your brother.”

## What Changes For Support And Onboarding

### Onboarding needs to explain

- what a sovereign agent is
- that it is optional
- that native CareOS remains fully usable without it
- how preferences can differ by role
- what fallback means

### Support needs to understand

- which surface was preferred
- whether a sovereign agent was active
- whether fallback occurred
- whether context came from sovereign reflection or native CareOS entry

## Possibilities This Enables

If implemented well, this model enables:

- richer personal engagement without weakening care governance
- role-specific experience selection
- person-based agents acting across multiple patient contexts
- better use of SDOH and real-world constraints in care planning
- more resilient fallback when the personal agent is absent
- more continuity between personal planning and care execution

## Risks To Watch In UX

### Risk 1: Users think sovereign agent replaces CareOS entirely

It should not.
CareOS still owns the care state and policy layer.

### Risk 2: Users without sovereign agents feel second-class

This must be avoided.
Native OpenClaw plus CareOS should remain a genuine personalization path.

### Risk 3: Role confusion

A mixed-role user may not know whether they are acting as patient or caregiver.

The experience should make context clear:

- who the active patient is
- what role the person is currently acting in
- what surface is active

### Risk 4: Unexpected fallback

If the sovereign agent is unavailable and CareOS falls back to WhatsApp or voice, the experience should explain why, not feel random.

## Recommended Product Language

Preferred user-facing language:

- “personal agent” or “sovereign agent”
- “preferred interaction surface”
- “fallback surface”
- “care personalization”
- “acting for [patient name]”

Avoid user-facing language that sounds too infrastructural, such as:

- endpoint
- adapter
- routing tuple
- transport boundary

## Definition Of A Good Experience

The experience is good if:

- users with a sovereign agent feel that CareOS works through their preferred personal layer
- users without a sovereign agent still feel that CareOS understands their care context
- the same human can have different preferences in different roles without confusion
- urgent care requirements are still enforced consistently
- fallback behavior feels safe and understandable

## Immediate Next UX Step

Once phase 1 is implemented, this manual should be updated with:

- concrete setup screens or commands
- exact role preference choices
- fallback examples
- screenshots or sample conversations
