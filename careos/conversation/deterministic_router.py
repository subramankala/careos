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
                text="Commands: schedule, next, status, done <win_id>, delay <win_id> <minutes>, skip <win_id>",
            )

        if command in {"schedule", "today"}:
            today = self.win_service.today(context.patient_id)
            if not today.timeline:
                return CommandResult(action="schedule", text="No wins are scheduled for today.")
            tz = ZoneInfo(today.timezone)
            lines = [f"Schedule ({today.date}):"]
            for item in today.timeline[:10]:
                local_time = item.scheduled_start.astimezone(tz).strftime("%H:%M")
                lines.append(
                    f"- {item.win_instance_id[:8]} {local_time} {item.title} [{item.current_state.value}]"
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
            win_id = raw.split(maxsplit=1)[1].strip()
            self.win_service.complete(win_id, context.participant_id)
            return CommandResult(action="done", text=f"Marked {win_id} as completed.")

        if command.startswith("skip "):
            win_id = raw.split(maxsplit=1)[1].strip()
            self.win_service.skip(win_id, context.participant_id)
            return CommandResult(action="skip", text=f"Marked {win_id} as skipped.")

        if command.startswith("delay "):
            parts = raw.split()
            if len(parts) < 3 or not parts[-1].isdigit():
                return CommandResult(action="delay", text="Use: delay <win_id> <minutes>")
            win_id = parts[1]
            minutes = int(parts[2])
            self.win_service.delay(win_id, context.participant_id, minutes)
            return CommandResult(action="delay", text=f"Delayed {win_id} by {minutes} minutes.")

        return CommandResult(
            action="fallback",
            text="I can handle: schedule, next, status, done, delay, skip, help.",
        )
