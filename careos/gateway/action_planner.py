from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from careos.gateway.action_proposals import StructuredActionProposal, propose_structured_action


@dataclass(frozen=True)
class ParsedAction:
    source_text: str
    proposal: StructuredActionProposal
    parser_name: str = "structured_action_proposal"


@dataclass(frozen=True)
class BoundAction:
    parsed: ParsedAction
    target_binding: dict[str, Any] | None = None
    binding_status: str = "not_required"
    candidate_bindings: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class CompiledActionPlan:
    bound: BoundAction
    execution_strategy: str
    execution_payload: dict[str, Any]
    confirmation_text: str


def _normalized(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def _matching_candidates(proposal: StructuredActionProposal, timeline: list[dict]) -> list[dict[str, Any]]:
    if not proposal.target_instance_id:
        return []
    title = _normalized(proposal.title)
    category = _normalized(proposal.category)
    matches: list[dict[str, Any]] = []
    for item in timeline:
        if _normalized(item.get("title", "")) != title:
            continue
        if _normalized(item.get("category", "")) != category:
            continue
        matches.append(dict(item))
    return matches


def _format_candidate_label(candidate: dict[str, Any], timezone_name: str) -> str:
    title = str(candidate.get("title", "task")).strip() or "task"
    category = str(candidate.get("category", "task")).strip() or "task"
    state = str(candidate.get("current_state", "pending")).strip() or "pending"
    scheduled_start = str(candidate.get("scheduled_start", "")).strip()
    if scheduled_start:
        start_value = datetime.fromisoformat(scheduled_start.replace("Z", "+00:00"))
        local_time = start_value.astimezone(ZoneInfo(timezone_name)).strftime("%-I:%M %p")
        return f"{title} at {local_time} ({category}, {state})"
    return f"{title} ({category}, {state})"


def _clarify_ambiguous_target(bound: BoundAction) -> str:
    proposal = bound.parsed.proposal
    timezone_name = str(proposal.start_at.tzinfo or "UTC")
    candidate_labels = [
        _format_candidate_label(candidate, timezone_name)
        for candidate in (bound.candidate_bindings or [])[:3]
    ]
    joined = "; ".join(candidate_labels)
    return (
        f"I found multiple matches for {proposal.title.lower()}: {joined}. "
        "Reply with the time or item number you mean, or ask for your schedule first."
    )


def parse_action_request(text: str, context: dict, timeline: list[dict]) -> ParsedAction | None:
    proposal = propose_structured_action(text, context, timeline=timeline)
    if proposal is None:
        return None
    return ParsedAction(source_text=text, proposal=proposal)


def bind_action(parsed: ParsedAction, adapter: Any, timeline: list[dict]) -> BoundAction:
    proposal = parsed.proposal
    if not proposal.target_instance_id:
        return BoundAction(parsed=parsed, target_binding=None, binding_status="not_required", candidate_bindings=[])
    candidates = _matching_candidates(proposal, timeline)
    if not candidates:
        return BoundAction(parsed=parsed, target_binding=None, binding_status="not_found", candidate_bindings=[])
    if len(candidates) > 1:
        target = next((item for item in candidates if str(item.get("win_instance_id")) == proposal.target_instance_id), candidates[0])
        return BoundAction(parsed=parsed, target_binding=None, binding_status="ambiguous", candidate_bindings=candidates,)
    binding = adapter.get_win_binding(proposal.target_instance_id)
    return BoundAction(parsed=parsed, target_binding=binding, binding_status="bound", candidate_bindings=candidates)


def compile_action(bound: BoundAction) -> CompiledActionPlan:
    proposal = bound.parsed.proposal
    if bound.binding_status == "not_found":
        return CompiledActionPlan(
            bound=bound,
            execution_strategy="clarify_target",
            execution_payload={},
            confirmation_text=f"I could not find a matching {proposal.title.lower()} in the current schedule. Please rephrase or ask for your schedule first.",
        )
    if bound.binding_status == "ambiguous":
        return CompiledActionPlan(
            bound=bound,
            execution_strategy="clarify_target",
            execution_payload={},
            confirmation_text=_clarify_ambiguous_target(bound),
        )
    if proposal.action_type == "create_task":
        return CompiledActionPlan(
            bound=bound,
            execution_strategy="create_task",
            execution_payload={
                "patient_id": proposal.patient_id,
                "actor_id": proposal.actor_id,
                "category": proposal.category,
                "title": proposal.title,
                "instructions": proposal.instructions,
                "start_at_iso": proposal.start_at.isoformat(),
                "end_at_iso": proposal.end_at.isoformat(),
                "criticality": proposal.criticality,
                "flexibility": proposal.flexibility,
            },
            confirmation_text=proposal.confirmation_text,
        )
    if proposal.action_type == "complete_task":
        return CompiledActionPlan(
            bound=bound,
            execution_strategy="complete_task",
            execution_payload={
                "win_instance_id": proposal.target_instance_id,
                "actor_id": proposal.actor_id,
            },
            confirmation_text=proposal.confirmation_text,
        )
    if proposal.action_type == "update_task":
        recurrence_type = str((bound.target_binding or {}).get("recurrence_type", "one_off"))
        strategy = "override_recurring_task" if recurrence_type != "one_off" else "reschedule_one_off_task"
        return CompiledActionPlan(
            bound=bound,
            execution_strategy=strategy,
            execution_payload={
                "win_instance_id": proposal.target_instance_id,
                "actor_id": proposal.actor_id,
                "start_at_iso": proposal.start_at.isoformat(),
                "end_at_iso": proposal.end_at.isoformat(),
            },
            confirmation_text=proposal.confirmation_text,
        )
    return CompiledActionPlan(
        bound=bound,
        execution_strategy="unsupported",
        execution_payload={},
        confirmation_text=proposal.confirmation_text,
    )


def plan_action_request(text: str, context: dict, timeline: list[dict], adapter: Any) -> CompiledActionPlan | None:
    parsed = parse_action_request(text, context, timeline)
    if parsed is None:
        return None
    bound = bind_action(parsed, adapter, timeline)
    return compile_action(bound)


def _proposal_to_dict(proposal: StructuredActionProposal) -> dict[str, Any]:
    payload = asdict(proposal)
    payload["start_at"] = proposal.start_at.isoformat()
    payload["end_at"] = proposal.end_at.isoformat()
    return payload


def _proposal_from_dict(payload: dict[str, Any]) -> StructuredActionProposal:
    return StructuredActionProposal(
        action_type=str(payload["action_type"]),
        entity_type=str(payload["entity_type"]),
        category=str(payload["category"]),
        title=str(payload["title"]),
        instructions=str(payload["instructions"]),
        patient_id=str(payload["patient_id"]),
        tenant_id=str(payload["tenant_id"]),
        actor_id=str(payload["actor_id"]),
        start_at=datetime.fromisoformat(str(payload["start_at"])),
        end_at=datetime.fromisoformat(str(payload["end_at"])),
        criticality=str(payload["criticality"]),
        flexibility=str(payload["flexibility"]),
        confirmation_text=str(payload["confirmation_text"]),
        target_instance_id=str(payload.get("target_instance_id", "")),
        delay_minutes=int(payload.get("delay_minutes", 0) or 0),
    )


def serialize_compiled_plan(plan: CompiledActionPlan) -> dict[str, Any]:
    return {
        "parsed": {
            "source_text": plan.bound.parsed.source_text,
            "proposal": _proposal_to_dict(plan.bound.parsed.proposal),
            "parser_name": plan.bound.parsed.parser_name,
        },
        "target_binding": dict(plan.bound.target_binding or {}),
        "binding_status": plan.bound.binding_status,
        "candidate_bindings": list(plan.bound.candidate_bindings or []),
        "execution_strategy": plan.execution_strategy,
        "execution_payload": dict(plan.execution_payload),
        "confirmation_text": plan.confirmation_text,
    }


def deserialize_compiled_plan(payload: dict[str, Any]) -> CompiledActionPlan:
    parsed_payload = dict(payload["parsed"])
    parsed = ParsedAction(
        source_text=str(parsed_payload["source_text"]),
        proposal=_proposal_from_dict(dict(parsed_payload["proposal"])),
        parser_name=str(parsed_payload.get("parser_name", "structured_action_proposal")),
    )
    bound = BoundAction(
        parsed=parsed,
        target_binding=dict(payload.get("target_binding") or {}),
        binding_status=str(payload.get("binding_status", "not_required")),
        candidate_bindings=list(payload.get("candidate_bindings") or []),
    )
    return CompiledActionPlan(
        bound=bound,
        execution_strategy=str(payload["execution_strategy"]),
        execution_payload=dict(payload.get("execution_payload") or {}),
        confirmation_text=str(payload["confirmation_text"]),
    )
