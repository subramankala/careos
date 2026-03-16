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
                text=(
                    "Commands: schedule, next, status, whoami, patients, switch, use <n>, "
                    "dashboard, caregivers, set caregiver <phone> as observer|primary, "
                    "invite caregiver, pending invites, cancel invite <code>, "
                    "add a medication, add an appointment, add a routine, "
                    "restart setup, cancel setup, register me as patient, cancel onboarding, restart onboarding, "
                    "done <item_no|win_id> [more items...], delay <item_no|win_id> <minutes>, skip <item_no|win_id>"
                ),
            )

        if command in {"schedule", "today"}:
            today = self.win_service.today(context.patient_id)
            prn_items = self.win_service.prn_definitions(context.patient_id)
            if not today.timeline and not prn_items:
                return CommandResult(action="schedule", text="No wins are scheduled for today.")
            tz = ZoneInfo(today.timezone)
            lines = [f"Schedule ({today.date}):"]
            for index, item in enumerate(today.timeline, start=1):
                local_time = item.scheduled_start.astimezone(tz).strftime("%H:%M")
                lines.append(
                    f"{index}. {local_time} {item.title} [{item.current_state.value}]"
                )
            if prn_items:
                if today.timeline:
                    lines.append("")
                lines.append("SOS/PRN (as needed):")
                for index, item in enumerate(prn_items, start=1):
                    instructions = item.get("instructions", "").strip()
                    if instructions:
                        lines.append(f"P{index}. {item['title']} - {instructions}")
                    else:
                        lines.append(f"P{index}. {item['title']}")
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

        if command in {"whoami", "profile"}:
            return CommandResult(
                action="whoami",
                text=(
                    f"You are {context.participant_role.value}. "
                    f"Active patient: {context.patient_id}. "
                    f"Timezone: {context.patient_timezone}."
                ),
            )

        if command.startswith("done "):
            refs = self._parse_done_references(raw.split(maxsplit=1)[1])
            if not refs:
                return CommandResult(action="done", text="Use: done <item_no|win_id> [more items...]")
            completed: list[str] = []
            for ref in refs:
                win_id, error = self._resolve_win_reference(context, ref)
                if win_id is None:
                    return CommandResult(
                        action="done",
                        text=(error or "Unknown win reference.") if not completed else f"Stopped after marking {', '.join(completed)}. {error or 'Unknown win reference.'}",
                    )
                self.win_service.complete(win_id, context.participant_id)
                completed.append(ref)
            if len(completed) == 1:
                return CommandResult(action="done", text=f"Marked {completed[0]} as completed.")
            return CommandResult(action="done", text=f"Marked {', '.join(completed)} as completed.")

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
            text=(
                "I can handle: schedule, next, status, whoami, patients, switch, use, dashboard, caregivers, "
                "invite management, setup shortcuts, onboarding controls, done, delay, skip, help."
            ),
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

    def _parse_done_references(self, value: str) -> list[str]:
        ignored = {"and", "&", "then"}
        tokens = [
            token.strip()
            for token in value.replace(",", " ").split()
            if token.strip() and token.strip().lower() not in ignored
        ]
        return tokens
