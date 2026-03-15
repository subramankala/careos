# CareOS Backlog

This backlog is intended to be descriptive enough for architects and engineers to implement from, not just a title list. Each item captures the user problem, the desired behavior, the main design implications, and a concrete acceptance target.

## 1. Patient-Initiated Caregiver Invites

Status: proposed
Priority: high

Problem:
Today, multiple caregivers can be linked to one patient, but each caregiver must start the onboarding flow and request access individually. The patient can approve those requests, but the patient cannot directly initiate invites from WhatsApp. That is workable, but it is backward for the intended experience. The patient should be able to proactively invite people who should help manage care or simply stay informed.

Desired behavior:
- A patient can send a command like `invite caregiver`.
- The system asks for the invitee's WhatsApp number.
- The system asks which preset to assign:
  - `primary_caregiver`
  - `observer`
- The system sends the invitee a verification/join message.
- The invite remains pending until the invitee accepts or the patient cancels it.
- Once accepted, the caregiver-patient link is created with the chosen preset and notification preferences.

Design notes:
- Reuse the existing caregiver verification model where possible, but invert who initiates the flow.
- Keep the preset explicit during invite creation so the first linked state is already correct.
- Preserve patient safety by requiring an explicit accept/verify step from the invitee.
- The final linked caregiver should still be manageable later via `caregivers` and `set caregiver <phone> as observer|primary`.

Acceptance criteria:
- Patient can invite multiple caregivers one by one from WhatsApp.
- Invite flow supports at least `primary_caregiver` and `observer`.
- Invitee receives a WhatsApp prompt and can accept or decline.
- Pending invites can be listed and canceled.
- Approved invites create active caregiver links with the correct preset metadata.

## 2. Historical Backlog Completion Across Past Days

Status: proposed
Priority: medium

Problem:
Batch completion now works for the current visible schedule context, for example `done 1 2 3 4`. It does not support backlog cleanup across prior dates. A patient or caregiver trying to catch up after missed days still needs a more explicit backlog workflow.

Desired behavior:
- User can ask for backlog or missed items over a recent window.
- User can mark multiple historical items complete in one command.
- The system should distinguish between:
  - current-day schedule actions
  - historical backlog reconciliation

Design notes:
- Do not overload `done 1 2 3` with hidden cross-day semantics.
- Add explicit wording such as:
  - `show missed items from the last 3 days`
  - `done backlog 1 2 3`
- Historical reconciliation should be auditable and should not silently rewrite timestamps without preserving original due dates.

Acceptance criteria:
- User can view historical missed items for a bounded date range.
- User can complete selected historical items in batch.
- Audit logs retain original scheduled date and completion action date.

## 3. Candidate Scoring For Ambiguous Natural-Language Updates

Status: proposed
Priority: high

Problem:
The planner now returns useful clarification prompts when multiple timeline items match a request like `Move my Dytor 5mg to evening`. The current candidate handling is still mostly heuristic and does not rank likely targets deeply enough.

Desired behavior:
- The planner should score candidate matches using title overlap, recency, state, timing proximity, and category.
- If one match is clearly dominant, the planner should bind automatically.
- If several matches remain close, the planner should produce a targeted clarification prompt.

Design notes:
- Keep parse, bind, compile, and execute as separate stages.
- Surface binding confidence in logs and compiled plans.
- Avoid silent auto-binding when confidence is low.

Acceptance criteria:
- Ambiguous commands produce ranked candidates.
- Dominant single candidates bind automatically only above an explicit confidence threshold.
- Clarification prompts explain why a follow-up is needed.

## 4. Persistent Reminder Context For Reply-Based Actions

Status: proposed
Priority: high

Problem:
Replies like `Taken` and `I took it` now work if there is exactly one current due or delayed item. That is a strong improvement, but it still relies on inferring the target from current context rather than the specific reminder that triggered the reply.

Desired behavior:
- Each outbound reminder should carry a reply context or correlation token.
- A short reply should resolve to the exact reminded item whenever possible.
- The system should work correctly even if multiple due reminders are active around the same time.

Design notes:
- Prefer a correlation mechanism linked to the outbound message event.
- Keep the natural user reply short; users should not need to send IDs back manually.
- Fallback to clarification only when correlation is unavailable.

Acceptance criteria:
- A reply to a reminder resolves to the exact associated due item.
- Concurrent reminders do not cause mistaken completions.
- Audit logs link the inbound reply to the original outbound reminder.

## 5. Caregiver Notification Preferences UI And Commands

Status: proposed
Priority: medium

Problem:
Link presets now drive notification preferences, but there is no direct user-facing flow to tune those preferences without changing the whole preset.

Desired behavior:
- A primary caregiver can view and modify a caregiver's notification settings:
  - due reminders
  - critical alerts
  - daily summaries
  - low-adherence alerts
- The system should support both:
  - preset defaults
  - per-link overrides

Design notes:
- Keep preset as the baseline and store explicit overrides separately if needed.
- Provide both internal API support and a constrained WhatsApp management flow.

Acceptance criteria:
- Notification preferences can be viewed and updated per caregiver link.
- Overrides do not destroy the selected preset label.
- Scheduler respects the updated preferences immediately.

## 6. Read/Write Policy Separation For Caregiver Personas

Status: proposed
Priority: medium

Problem:
`primary_caregiver` and `observer` are now implemented, but the write controls and dashboard scopes will become more complex as more operations are added. The authorization policy should become clearer before more caregiver personas or exceptions are introduced.

Desired behavior:
- Read scopes and write scopes are explicitly separated in policy.
- Observer remains read-only by default.
- Primary caregiver can manage care plan actions and caregiver presets.

Design notes:
- Preserve link-level `authorization_version` semantics.
- Make scope evaluation reusable across dashboard, scheduler, gateway, and internal APIs.
- Keep persona presets lightweight; avoid role explosion.

Acceptance criteria:
- All caregiver actions map to explicit scopes.
- Dashboard rendering and gateway commands check the same scope model.
- Changing a link's scopes invalidates old authorization tokens where relevant.

## 7. Care-Dash Care Plan Editing For Authorized Caregivers

Status: proposed
Priority: high

Problem:
The caregiver dashboard is currently a read-only summary surface. That is useful for visibility, but it stops short of the more important operational workflow: an authorized caregiver should be able to adjust the care plan from the dashboard when they are actively managing the patient's day-to-day care. Right now, caregivers can trigger some changes via WhatsApp, but the dashboard itself does not serve as an editing surface.

Desired behavior:
- A caregiver with edit permissions can open Care-Dash and update care-plan items directly.
- Supported edit operations should include at least:
  - add a new care-plan item
  - edit an existing item
  - reschedule an item
  - mark one-off items completed or skipped
  - adjust reminder timing windows
- Observer caregivers should continue to see a read-only dashboard.
- Primary caregivers should see editing controls only where they have the required scopes.

Design notes:
- Care-Dash should remain presentation-first, but it should be able to submit authorized edit intents through CareOS rather than becoming its own source of truth.
- Reuse the same scope model already introduced for caregiver presets:
  - read scopes
  - write scopes
- Care plan editing from the dashboard should follow the same execution semantics as the gateway planner where possible:
  - definition-aware edits for recurring items
  - instance-aware overrides for one-off or occurrence-level changes
- All mutations should be auditable and should increment authorization-sensitive state where applicable.
- The dashboard should make it obvious whether the user is editing:
  - a recurring definition
  - a single occurrence
  - a one-off item

Acceptance criteria:
- Primary caregivers can edit care-plan items from Care-Dash.
- Observer caregivers cannot see or use editing controls.
- Dashboard mutations flow through CareOS APIs and are reflected in the next dashboard refresh.
- Recurring edits and one-off overrides behave consistently with the backend action model.
- All care-plan edits are logged with actor, patient, timestamp, and mutation type.

## 8. Better Help, Discovery, And Progressive Guidance

Status: proposed
Priority: medium

Problem:
The help menu now reflects many more commands, but discoverability is still text-heavy. New users can still miss the difference between schedule actions, setup flows, dashboard access, and caregiver management.

Desired behavior:
- Help should be segmented by intent:
  - daily care
  - caregiver tools
  - setup
  - onboarding
- The system should provide short follow-up hints after relevant actions.

Design notes:
- Keep WhatsApp responses compact.
- Avoid dumping the full command list every time.
- Consider `help caregiver`, `help setup`, `help meds`, and similar submenus.

Acceptance criteria:
- Users can discover major flows without reading a long single menu.
- Command discovery improves after the first failed or ambiguous request.

## 9. Daily Digest And Alert Tuning Controls

Status: proposed
Priority: medium

Problem:
Proactive caregiver notifications now exist for due reminders, critical missed items, low adherence, and daily summaries. The content and timing are still first-slice defaults.

Desired behavior:
- Per-patient or per-caregiver tuning for:
  - daily summary time
  - grace period before critical-missed alerts
  - due reminder aggressiveness
- Better separation between urgent alerts and informational summaries.

Design notes:
- Reuse the caregiver link preference model where possible.
- Consider timezone-aware quiet hours and escalation windows.

Acceptance criteria:
- Notification timing can be tuned without code changes.
- Urgent alerts and informational digests follow different policies.

## 10. GitHub Issue Sync For Backlog Items

Status: proposed
Priority: low

Problem:
A Markdown backlog in the repo is durable and reviewable, but it is not yet synchronized with GitHub issues or project boards.

Desired behavior:
- Important backlog items can be promoted into GitHub issues with labels and status.
- The repo should remain the source of feature descriptions, while issues track execution.

Design notes:
- Keep `BACKLOG.md` as the descriptive source.
- Use issues for owner, milestone, and implementation status tracking.

Acceptance criteria:
- High-priority backlog items are mirrored into GitHub issues.
- The Markdown backlog and issues reference each other cleanly.
