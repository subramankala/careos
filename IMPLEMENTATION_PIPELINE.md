# Lightweight Implementation Pipeline

This repository uses a lightweight delivery pipeline built on GitHub issues and labels.

## Stages

- `stage:backlog`
  - described, not yet committed for implementation
- `stage:ready`
  - scoped well enough to start
- `stage:in-progress`
  - active implementation
- `stage:review`
  - code complete, tests run, awaiting review or deployment decision
- `stage:deployed`
  - live, but not yet validated against real behavior
- `stage:validated`
  - verified in real workflow and ready to close

## Core Labels

### Type

- `type:feature`
- `type:bug`
- `type:hardening`
- `type:feedback`

### Area

- `area:gateway`
- `area:dashboard`
- `area:onboarding`
- `area:scheduler`
- `area:policy-auth`

### Priority

- `priority:high`
- `priority:medium`
- `priority:low`

## Working Rules

1. `BACKLOG.md` is the descriptive product source of truth.
2. Promote an item into a GitHub issue when it is near-term enough to consider implementing.
3. Keep at most a small number of items in `stage:in-progress`.
4. Every issue should have explicit acceptance criteria and a test plan.
5. An issue is not complete when code is merged. It is complete when it is `stage:validated`.
6. Live behavior should be verified before closing issues that affect WhatsApp, scheduler, or Care-Dash flows.

## Recommended Cadence

- Weekly:
  - review ranked backlog
  - move the next few items into `stage:ready`
  - pick one major and one minor item for implementation
- During implementation:
  - move issue to `stage:in-progress`
  - update notes and verification status continuously
- After deployment:
  - move to `stage:deployed`
  - validate in the live workflow
  - then move to `stage:validated`
