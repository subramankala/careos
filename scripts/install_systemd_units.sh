#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_SRC_DIR="$REPO_ROOT/deploy/systemd"
UNIT_DEST_DIR="/etc/systemd/system"

APPLY=false
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=true
fi

API_UNIT="careos-lite-api.service"
SCHED_UNIT="careos-lite-scheduler.service"

for unit in "$API_UNIT" "$SCHED_UNIT"; do
  if [[ ! -f "$UNIT_SRC_DIR/$unit" ]]; then
    echo "Missing unit file: $UNIT_SRC_DIR/$unit" >&2
    exit 1
  fi
done

echo "Unit source directory: $UNIT_SRC_DIR"
echo "Unit destination: $UNIT_DEST_DIR"

echo
if [[ "$APPLY" == "true" ]]; then
  echo "Copying unit files with sudo (reviewed action):"
  sudo cp "$UNIT_SRC_DIR/$API_UNIT" "$UNIT_DEST_DIR/$API_UNIT"
  sudo cp "$UNIT_SRC_DIR/$SCHED_UNIT" "$UNIT_DEST_DIR/$SCHED_UNIT"
  echo "Copied:"
  echo "- $UNIT_DEST_DIR/$API_UNIT"
  echo "- $UNIT_DEST_DIR/$SCHED_UNIT"
else
  echo "Dry run (no files copied)."
  echo "To apply, run:"
  echo "  $0 --apply"
fi

echo
echo "Next commands to run manually:"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable careos-lite-api careos-lite-scheduler"
echo "  sudo systemctl start careos-lite-api careos-lite-scheduler"
echo "  sudo systemctl status careos-lite-api --no-pager"
echo "  sudo systemctl status careos-lite-scheduler --no-pager"
echo "  sudo journalctl -u careos-lite-api -n 100 --no-pager"
echo "  sudo journalctl -u careos-lite-scheduler -n 100 --no-pager"
