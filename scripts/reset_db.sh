#!/usr/bin/env bash
set -euo pipefail

MODE="dry-run"
RESTART_SERVICES="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      MODE="apply"
      shift
      ;;
    --restart-services)
      RESTART_SERVICES="true"
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/reset_db.sh [--apply] [--restart-services]

Default behavior (no --apply): print all commands only (safe review mode).

Options:
  --apply             Execute destructive DB reset and migration re-apply.
  --restart-services  After apply, print and run systemctl restart commands.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

MIGRATIONS=(
  "careos/db/migrations/0001_initial.sql"
  "careos/db/migrations/0002_care_plan_deltas.sql"
  "careos/db/migrations/0003_recurrence_support.sql"
  "careos/db/migrations/0004_participant_active_context.sql"
  "careos/db/migrations/0005_onboarding_sessions.sql"
  "careos/db/migrations/0006_caregiver_verification_requests.sql"
  "careos/db/migrations/0007_personalization_and_mediation.sql"
  "careos/db/migrations/0008_person_identity_and_memberships.sql"
  "careos/db/migrations/0009_patient_clinical_facts.sql"
  "careos/db/migrations/0010_patient_observations.sql"
)

if [[ -z "${CAREOS_DATABASE_URL:-}" ]]; then
  cat <<'EOF' >&2
CAREOS_DATABASE_URL is not set.
Load env first:
  set -a; source .env; set +a
EOF
  exit 1
fi

print_plan() {
  cat <<EOF
Database reset plan (mode: $MODE)
1) DROP SCHEMA public CASCADE; CREATE SCHEMA public;
2) Apply migrations in order:
$(for m in "${MIGRATIONS[@]}"; do echo "   - $m"; done)
3) Optional service restart:
   sudo systemctl restart careos-lite-api careos-lite-scheduler
EOF
}

run_apply() {
  echo "Executing destructive reset against CAREOS_DATABASE_URL"
  psql "$CAREOS_DATABASE_URL" -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

  for migration in "${MIGRATIONS[@]}"; do
    if [[ ! -f "$migration" ]]; then
      echo "Missing migration file: $migration" >&2
      exit 1
    fi
    echo "Applying $migration"
    psql "$CAREOS_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"
  done

  echo "Reset complete."

  if [[ "$RESTART_SERVICES" == "true" ]]; then
    echo "Restarting services..."
    sudo systemctl restart careos-lite-api careos-lite-scheduler
    sudo systemctl status careos-lite-api --no-pager
    sudo systemctl status careos-lite-scheduler --no-pager
  else
    echo "If needed, restart services manually:"
    echo "  sudo systemctl restart careos-lite-api careos-lite-scheduler"
  fi
}

print_plan

if [[ "$MODE" == "apply" ]]; then
  run_apply
else
  cat <<'EOF'

Review mode only. To execute:
  scripts/reset_db.sh --apply

To also restart services:
  scripts/reset_db.sh --apply --restart-services
EOF
fi
