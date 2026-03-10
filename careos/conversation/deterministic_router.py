from __future__ import annotations

from zoneinfo import ZoneInfo

from careos.conversation.engine_base import ConversationEngine
from careos.domain.models.api import CommandResult, ParticipantContext
from careos.services.win_service import WinService


class DeterministicRouter(ConversationEngine):
    def __init__(self, win_service: WinService) -> None:
        self.win_service = win_service

    def handle(self, text: str, context: ParticipantContext) -> CommandResult:
        raw = text.strip()
        command = raw.lower()

        if command in {"help", "?"}:
            return CommandResult(
                action="help",
                text="Commands: schedule, next, status, done <item_no|win_id>, delay <item_no|win_id> <minutes>, skip <item_no|win_id>",
            )

        if command in {"schedule", "today"}:
            today = self.win_service.today(context.patient_id)
            if not today.timeline:
                return CommandResult(action="schedule", text="No wins are scheduled for today.")
            tz = ZoneInfo(today.timezone)
            lines = [f"Schedule ({today.date}):"]
            for index, item in enumerate(today.timeline, start=1):
                local_time = item.scheduled_start.astimezone(tz).strftime("%H:%M")
                lines.append(
                    f"{index}. {local_time} {item.title} [{item.current_state.value}]"
                )
            return CommandResult(action="schedule", text="\n".join(lines))

        if command == "next":
            return CommandResult(action="next", text=self.win_service.next_text(context.patient_id))

        if command == "status":
            status = self.win_service.status(context.patient_id)
            return CommandResult(
                action="status",
                text=(
                    f"Status: completed={status.completed_count}, due={status.due_count}, "
                    f"missed={status.missed_count}, skipped={status.skipped_count}, score={status.adherence_score}%"
                ),
            )

        if command.startswith("done "):
            ref = raw.split(maxsplit=1)[1].strip()
            win_id, error = self._resolve_win_reference(context, ref)
            if win_id is None:
                return CommandResult(action="done", text=error or "Unknown win reference.")
            self.win_service.complete(win_id, context.participant_id)
            return CommandResult(action="done", text=f"Marked {ref} as completed.")

        if command.startswith("skip "):
            ref = raw.split(maxsplit=1)[1].strip()
            win_id, error = self._resolve_win_reference(context, ref)
            if win_id is None:
                return CommandResult(action="skip", text=error or "Unknown win reference.")
            self.win_service.skip(win_id, context.participant_id)
            return CommandResult(action="skip", text=f"Marked {ref} as skipped.")

        if command.startswith("delay "):
            parts = raw.split()
            if len(parts) < 3 or not parts[-1].isdigit():
                return CommandResult(action="delay", text="Use: delay <item_no|win_id> <minutes>")
            ref = parts[1]
            win_id, error = self._resolve_win_reference(context, ref)
            if win_id is None:
                return CommandResult(action="delay", text=error or "Unknown win reference.")
            minutes = int(parts[2])
            self.win_service.delay(win_id, context.participant_id, minutes)
            return CommandResult(action="delay", text=f"Delayed {ref} by {minutes} minutes.")

        return CommandResult(
            action="fallback",
            text="I can handle: schedule, next, status, done, delay, skip, help.",
        )

    def _resolve_win_reference(self, context: ParticipantContext, reference: str) -> tuple[str | None, str | None]:
        today = self.win_service.today(context.patient_id)
        if reference.isdigit():
            idx = int(reference)
            if idx < 1 or idx > len(today.timeline):
                return None, f"Item number {reference} is out of range for today's schedule."
            return today.timeline[idx - 1].win_instance_id, None

        matches = [item.win_instance_id for item in today.timeline if item.win_instance_id.startswith(reference)]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, f"Reference {reference} is ambiguous. Use the item number from schedule."

        if len(reference) >= 8:
            return reference, None
        return None, "Could not find that task. Send 'schedule' and use the item number."
