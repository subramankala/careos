# CareOS Voice Notification Plan

Last updated: 2026-03-16 UTC

## Goal

Allow patients and caregivers to choose voice calls, WhatsApp text, or both for specific types of CareOS notifications.

Examples:

- patient wants medication reminders as voice calls
- caregiver wants critical missed alerts as voice calls
- observer wants only text summaries
- daily summaries remain text only

This document is a product and architecture plan only. It does not assume implementation yet.

## Product Objective

Notification channel should be configurable by:

- notification type
- recipient type
- patient context
- escalation severity

Voice is not a separate product. It is an additional outbound delivery channel on top of the existing scheduler-driven notification system.

## Core Product Model

Each notification has four dimensions:

1. `event_type`
- due reminder
- critical missed alert
- low adherence alert
- daily summary
- future: appointment reminder, escalation follow-up, refill reminder

2. `recipient`
- patient
- primary caregiver
- observer

3. `channel`
- text
- voice
- both
- off

4. `policy`
- immediate
- fallback after no answer
- retries
- quiet hours
- escalation override

## Ideal User Experience

### For patients

Patient can say:

- `notification settings`
- `set my medication reminders to voice`
- `set my routine reminders to text only`
- `set my critical alerts to voice and text`

If patient is in setup/onboarding, a guided menu can expose:

- `Text only`
- `Voice only`
- `Voice and text`

### For caregivers

Caregiver can say:

- `set caregiver alerts to voice`
- `set critical alerts to voice and text`
- `set daily summary to text only`

Dashboard/settings UX can later mirror these commands.

## Recommended MVP Experience

Do not start with all notification types.

### Start with these

1. Patient medication due reminders
2. Caregiver critical missed alerts

### Keep these as text only initially

1. Daily summaries
2. Low adherence summaries
3. General status reports
4. Non-critical routines

### Why

- medication due reminders are high-value for voice
- critical missed alerts justify interruption
- summaries over voice are noisy and lower value
- one-way voice is much simpler to ship safely than interactive voice
- WhatsApp reply handling already exists and can remain the action path

## Call Experience Design

Voice calls should be deterministic, short, and action-oriented.

### Patient medication reminder call

Example spoken prompt:

`This is CareOS. It is time to take Ecosprin 75 milligrams. After taking it, please reply on WhatsApp with Taken. If you took multiple medicines, reply done all meds or ask for your schedule on WhatsApp.`

Recommended MVP behavior:

- no keypad input
- no in-call completion
- call is informational only
- user action happens on WhatsApp reply

### Caregiver critical missed alert call

Example spoken prompt:

`This is CareOS. A critical medication may have been missed for Mankala Nageswara Rao. Please check WhatsApp for details and reply there if needed.`

Recommended MVP behavior:

- no keypad input
- informational alert only
- any follow-up action remains on WhatsApp

### Why one-way voice first

- lowest implementation complexity
- no TwiML `Gather` flow required
- no call-state-to-action coupling
- no keypad UX edge cases
- reuses the existing WhatsApp completion path

DTMF or speech interaction can be added later if the one-way call channel proves useful.

## Channel Semantics

### `text`

Only WhatsApp text is sent.

### `voice`

Only a voice call is attempted.

### `both`

Recommended meaning for MVP:

- not simultaneous
- primary attempt on one channel
- fallback to the other if unanswered or not delivered

Recommended defaults:

- due reminders: `text` first, optional voice fallback
- critical alerts: `voice` first, text fallback if unanswered

Do not send both at the exact same moment in MVP.

## Notification Preference Model

Use the existing notification policy structure first.

### Near-term storage location

Extend caregiver link and patient-self link notification policy JSON.

Suggested shape:

```json
{
  "notification_preferences": {
    "due_reminders": {
      "channel": "voice"
    },
    "critical_alerts": {
      "channel": "both"
    },
    "daily_summary": {
      "channel": "text"
    }
  },
  "voice_preferences": {
    "fallback_to_text": true,
    "retry_count": 1,
    "quiet_hours": {
      "start": "22:00",
      "end": "07:00"
    },
    "language": "en-IN",
    "voice_name": "alice"
  }
}
```

### Longer-term

Move notification preferences into first-class policy tables once the model stabilizes.

## Architecture Direction

## Existing system to reuse

Current CareOS already has:

- scheduler-driven outbound notifications
- event typing in `message_events`
- idempotent delivery writes
- caregiver link notification preferences
- Twilio integration for WhatsApp text

Voice should plug into this pipeline, not replace it.

### Proposed components

1. `VoiceSender`
- outbound Twilio Calls API client
- creates calls to recipient phone numbers
- points Twilio to a CareOS voice TwiML route

2. `Voice TwiML Route`
- returns spoken prompt using TwiML

3. `Voice Status Callback Route`
- receives Twilio call lifecycle updates
- records answered/no-answer/busy/failed

### Suggested runtime flow

1. scheduler decides a notification should be sent
2. scheduler checks recipient policy for preferred channel
3. scheduler creates one logical outbound notification event
4. channel executor performs either:
- WhatsApp send
- voice call
- fallback sequence
5. delivery attempts are logged
6. user completes or acknowledges through WhatsApp reply flow if action is needed

## Twilio Voice Integration Shape

### Outbound call

Scheduler invokes Twilio call creation with:

- `to`
- `from`
- `url` for TwiML
- `status_callback`

### TwiML route

Suggested route:

- `POST /voice/outbound/twiml`

This route:

- validates signed request or opaque token
- looks up notification context
- speaks prompt

### Status callback

Suggested route:

- `POST /voice/outbound/status`

This route:

- records call states:
  - initiated
  - ringing
  - answered
  - completed
  - busy
  - no-answer
  - failed

## Event Model Recommendation

Current `message_events` is enough for early MVP, but voice will stress it.

### MVP-compatible approach

Continue using `message_events` with:

- `channel = whatsapp` or `voice`
- `message_type = scheduled_reminder`, `critical_missed_status_alert`, etc.
- structured payload carrying voice metadata

### Better long-term model

Introduce:

- `notification_events`
- `notification_delivery_attempts`

This would separate:

- logical notification intent
- channel-level delivery attempts

But this can wait until voice proves product value.

## Policy Rules

### Quiet hours

Default:

- voice suppressed during quiet hours
- except critical alerts if explicitly allowed

### Retry behavior

Default:

- one voice attempt
- if unanswered, fallback to text when enabled

### Escalation behavior

Voice for critical alerts should be allowed to override normal quiet-hour rules if configured.

### Observer behavior

Default:

- observers do not get voice calls unless explicitly enabled

### Patient self behavior

Patient voice reminders are allowed for medications only in MVP.

## Command / Settings UX

### MVP command set

Suggested exact commands:

- `notification settings`
- `set medication reminders to voice`
- `set medication reminders to text`
- `set critical alerts to voice`
- `set critical alerts to text`
- `set critical alerts to voice and text`
- `set daily summary to text`

For caregivers:

- `set my critical alerts to voice`
- `set my daily summary to text`

For patients:

- `set my meds to voice`

### Response examples

- `Medication reminders will now use voice calls.`
- `Critical alerts will now use voice first, then text if missed.`
- `Daily summaries will remain text only.`

## Phased Implementation Plan

### Phase 1. Policy and configuration

Scope:

- extend notification preference model with channel selection
- expose configuration via internal API and deterministic commands
- no voice calls yet

Outcome:

- product can express channel intent before delivery changes

### Phase 2. Outbound voice transport

Scope:

- add Twilio voice sender
- add TwiML endpoint
- add status callback route
- log call attempts

Outcome:

- CareOS can place outbound calls for a notification

### Phase 3. Patient medication voice reminder

Scope:

- voice calls for due medication reminders
- spoken reminder tells patient to reply on WhatsApp with `Taken`
- for multiple medication cases, spoken reminder points user to `done all meds` or `schedule`

Outcome:

- end-to-end one-way patient voice reminders with WhatsApp as action path

### Phase 4. Caregiver critical missed alert voice

Scope:

- caregiver call on critical missed events
- spoken alert tells caregiver to check or reply on WhatsApp

Outcome:

- critical caregiver alerting on voice

### Phase 5. Fallback and polish

Scope:

- voice-to-text fallback
- retries
- quiet hours
- language/voice selection

Outcome:

- reliable user-facing voice behavior

## Risks

### 1. Notification fatigue

If too many events are moved to voice, users will disengage.

Mitigation:

- start with meds and critical alerts only
- keep daily summaries as text

### 2. Ambiguous voice actions

If the voice call implies an action path that differs from WhatsApp behavior, users may be confused.

Mitigation:

- keep the call one-way in MVP
- make WhatsApp the single action surface
- keep spoken instructions aligned with actual supported text replies

### 3. Duplicate channel delivery

If text and voice run independently, the same event may be sent twice unexpectedly.

Mitigation:

- centralize notification intent and fallback policy
- keep idempotency per event + channel

### 4. Quiet-hour intrusion

Voice at the wrong time will feel hostile.

Mitigation:

- quiet hours by default
- explicit critical override only

### 5. Action safety

Completing meds from voice is a high-stakes action.

Mitigation:

- single clear action per call
- do not batch-complete on ambiguous input

## Recommended MVP Decisions

1. Support voice only for:
- patient medication reminders
- caregiver critical missed alerts

2. Use one-way voice only, not DTMF or speech AI, in MVP

3. Make `both` mean fallback, not simultaneous dual-send

4. Default observers to text only

5. Keep daily summaries as text only in MVP

## Suggested Next Engineering Slice After Approval

1. Extend notification policy schema/API for channel preferences
2. Add Twilio voice sender and basic one-way TwiML route
3. Implement patient medication reminder call flow that directs the user back to WhatsApp
4. Add call logging, idempotency, and fallback-to-text behavior
