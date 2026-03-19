from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from careos.conversation.fallback_bridge_logic import fallback_intent, resolve_fallback_text
from careos.conversation.engine_base import ConversationEngine
from careos.domain.models.api import CommandResult, ParticipantContext
from careos.logging import get_logger
from careos.services.patient_context_service import PatientContextService
from careos.settings import settings
from careos.services.win_service import WinService

logger = get_logger("openclaw_engine")


class OpenClawConversationEngine(ConversationEngine):
    _MEDICATION_KNOWLEDGE: tuple[dict[str, object], ...] = (
        {
            "aliases": ("ecosprin", "aspirin", "brilinta", "ticagrelor"),
            "category": "blood thinner",
            "clinical_class": "antiplatelet",
            "purpose": "helps reduce blood clot risk after heart or vessel events",
        },
        {
            "aliases": ("pantop", "pantoprazole"),
            "category": "stomach acid control",
            "clinical_class": "proton pump inhibitor",
            "purpose": "reduces stomach acid and protects against acidity or reflux",
        },
        {
            "aliases": ("cardivas", "carvedilol"),
            "category": "blood pressure / heart support",
            "clinical_class": "beta blocker",
            "purpose": "helps control blood pressure and reduce strain on the heart",
        },
        {
            "aliases": ("nikoran", "nicorandil"),
            "category": "heart / angina support",
            "clinical_class": "anti-anginal vasodilator",
            "purpose": "helps prevent or relieve chest pain from reduced heart blood flow",
        },
        {
            "aliases": ("dytor", "torsemide", "torasemide"),
            "category": "fluid control / blood pressure",
            "clinical_class": "diuretic",
            "purpose": "helps remove extra fluid and can support blood pressure control",
        },
        {
            "aliases": ("gener sita", "metformin", "sitagliptin"),
            "category": "diabetes control",
            "clinical_class": "blood sugar lowering medication",
            "purpose": "helps control blood glucose",
        },
        {
            "aliases": ("aztor", "atorvastatin"),
            "category": "cholesterol control",
            "clinical_class": "statin",
            "purpose": "helps lower cholesterol and reduce cardiovascular risk",
        },
        {
            "aliases": ("cremafin",),
            "category": "constipation relief",
            "clinical_class": "laxative",
            "purpose": "helps bowel movement and constipation relief",
        },
        {
            "aliases": ("sorbitrate", "nitroglycerin"),
            "category": "angina rescue",
            "clinical_class": "nitrate vasodilator",
            "purpose": "used for chest pain relief",
        },
        {
            "aliases": ("t-bact", "mupirocin"),
            "category": "wound / skin infection care",
            "clinical_class": "topical antibiotic",
            "purpose": "helps treat or prevent localized skin infection",
        },
        {
            "aliases": ("advil pm", "ibuprofen"),
            "category": "pain relief / sleep aid",
            "clinical_class": "pain reliever combination",
            "purpose": "helps with pain and nighttime sleep support",
        },
    )

    """OpenClaw fallback engine.

    Expected OpenClaw endpoint contract:
    - POST {base_url}/v1/careos/fallback
    - request JSON:
      {
        "text": "...",
        "participant_context": {...},
        "allowed_actions": ["read", "write_via_mcp"]
      }
    - response JSON:
      {
        "text": "user-facing reply",
        "action": "openclaw_fallback"
      }
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int = 15,
        win_service: WinService | None = None,
        patient_context_service: PatientContextService | None = None,
        fallback_path: str = "/v1/careos/fallback",
        responses_path: str = "/v1/responses",
        gateway_token: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(int(timeout_seconds), 1)
        self.win_service = win_service
        self.patient_context_service = patient_context_service
        self.fallback_path = fallback_path if fallback_path.startswith("/") else f"/{fallback_path}"
        self.responses_path = responses_path if responses_path.startswith("/") else f"/{responses_path}"
        self.gateway_token = gateway_token.strip()

    def _is_local_bridge_url(self) -> bool:
        if not self.base_url:
            return False
        parsed = urlparse(self.base_url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
        if host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
            return False
        return port in {None, int(settings.api_port)}

    def _candidate_paths(self) -> list[str]:
        paths = [
            self.fallback_path,
            "/v1/careos/fallback",
            "/careos/fallback",
            "/api/v1/careos/fallback",
            "/v1/fallback",
        ]
        seen: set[str] = set()
        ordered: list[str] = []
        for path in paths:
            cleaned = path.strip()
            if not cleaned or not cleaned.startswith("/") or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
        return ordered

    @classmethod
    def _match_medication_knowledge(cls, name: str) -> dict[str, str] | None:
        normalized = " ".join(str(name).strip().lower().split())
        if not normalized:
            return None
        for entry in cls._MEDICATION_KNOWLEDGE:
            aliases = tuple(str(alias).lower() for alias in entry.get("aliases", ()))
            if any(alias in normalized for alias in aliases):
                return {
                    "matched_name": str(name),
                    "category": str(entry["category"]),
                    "clinical_class": str(entry["clinical_class"]),
                    "purpose": str(entry["purpose"]),
                }
        return None

    def _grounding_context(self, context: ParticipantContext) -> dict[str, object]:
        if self.win_service is None:
            return {
                "active_medications": [],
                "clinical_facts": [],
                "prn_medications": [],
                "medication_knowledge": [],
                "tool_hints": [
                    "careos_get_clinical_facts",
                    "careos_get_medications",
                    "careos_get_today",
                    "careos_get_status",
                ],
            }
        now = datetime.now(UTC)
        today = self.win_service.today(context.patient_id, at=now)
        active_medications: list[dict[str, str]] = []
        knowledge_rows: list[dict[str, str]] = []
        seen_knowledge: set[str] = set()
        for item in today.timeline:
            if item.category.strip().lower() != "medication":
                continue
            active_medications.append(
                {
                    "name": item.title,
                    "scheduled_start": item.scheduled_start.isoformat(),
                    "status": item.current_state.value,
                }
            )
            knowledge = self._match_medication_knowledge(item.title)
            if knowledge is None:
                continue
            key = knowledge["matched_name"].casefold()
            if key in seen_knowledge:
                continue
            seen_knowledge.add(key)
            knowledge_rows.append(knowledge)
        prn_medications = [
            {
                "name": str(item.get("title", "")),
                "instructions": str(item.get("instructions", "")),
            }
            for item in self.win_service.prn_definitions(context.patient_id)
        ]
        for item in prn_medications:
            knowledge = self._match_medication_knowledge(item["name"])
            if knowledge is None:
                continue
            key = knowledge["matched_name"].casefold()
            if key in seen_knowledge:
                continue
            seen_knowledge.add(key)
            knowledge_rows.append(knowledge)
        clinical_facts: list[dict[str, object]] = []
        if self.patient_context_service is not None:
            rows = self.patient_context_service.active_clinical_facts(
                tenant_id=context.tenant_id,
                patient_id=context.patient_id,
            )
            clinical_facts = [
                {
                    "fact_key": str(row.get("fact_key", "")),
                    "summary": str(row.get("summary", "")),
                    "fact_value": dict(row.get("fact_value") or {}),
                    "source": str(row.get("source", "")),
                    "effective_at": row.get("effective_at").isoformat() if row.get("effective_at") else None,
                }
                for row in rows
            ]
        return {
            "generated_at_utc": now.isoformat(),
            "active_medications": active_medications,
            "clinical_facts": clinical_facts,
            "prn_medications": prn_medications,
            "medication_knowledge": knowledge_rows,
            "tool_hints": [
                "careos_get_clinical_facts",
                "careos_get_medications",
                "careos_get_today",
                "careos_get_status",
            ],
        }

    def _build_openresponses_prompt(self, text: str, context: ParticipantContext) -> str:
        grounding = self._grounding_context(context)
        return (
            "You are a CareOS assistant. Use only the provided care context and grounded medication context. "
            "Answer concisely and do not invent facts.\n"
            "If durable clinical facts are provided, use them when they are relevant to the user's question. "
            "Treat them as patient-specific grounding context and prefer them over generic assumptions.\n"
            "For medication questions, answer from the patient's current medication list first. "
            "If the user asks which medicines are blood thinners or asks to categorize medicines by purpose, "
            "use the active medications and medication knowledge below. "
            "Treat the medication knowledge as common-use guidance, not a patient-specific prescribing instruction. "
            "If a classification is uncertain, say which medication is uncertain instead of giving a generic refusal.\n"
            "If the runtime supports CareOS MCP tools, prefer these read tools for grounding: "
            "careos_get_clinical_facts, careos_get_medications, careos_get_today, careos_get_status.\n"
            f"Now (UTC): {datetime.utcnow().isoformat()}Z\n"
            f"Tenant: {context.tenant_id}\n"
            f"Participant: {context.participant_id} ({context.participant_role.value})\n"
            f"Patient: {context.patient_id}, timezone={context.patient_timezone}, persona={context.patient_persona.value}\n"
            f"Grounded context JSON: {json.dumps(grounding, sort_keys=True)}\n"
            f"User message: {text}"
        )

    @staticmethod
    def _extract_text(data: object) -> tuple[str, str]:
        if isinstance(data, dict):
            text = str(data.get("text", "")).strip()
            action = str(data.get("action", "openclaw_fallback")).strip() or "openclaw_fallback"
            if text:
                return text, action
            message = data.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip(), action
            response = data.get("response")
            if isinstance(response, str) and response.strip():
                return response.strip(), action
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    msg = first.get("message")
                    if isinstance(msg, dict):
                        content = msg.get("content")
                        if isinstance(content, str) and content.strip():
                            return content.strip(), action
                    text_out = first.get("text")
                    if isinstance(text_out, str) and text_out.strip():
                        return text_out.strip(), action
            output = data.get("output")
            if isinstance(output, list):
                chunks: list[str] = []
                for item in output:
                    if not isinstance(item, dict):
                        continue
                    content = item.get("content")
                    if not isinstance(content, list):
                        continue
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        if part.get("type") == "output_text":
                            piece = part.get("text")
                            if isinstance(piece, str) and piece.strip():
                                chunks.append(piece.strip())
                if chunks:
                    return "\n".join(chunks), action
        return "", "openclaw_fallback"

    def _call_openresponses(self, text: str, context: ParticipantContext) -> CommandResult:
        if not self.gateway_token:
            return CommandResult(action="unavailable", text="")

        prompt = self._build_openresponses_prompt(text, context)
        payload = {
            "model": "openclaw:main",
            "stream": False,
            "user": context.participant_id,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
        }
        req = Request(
            f"{self.base_url}{self.responses_path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.gateway_token}",
            },
        )
        try:
            with urlopen(req, timeout=self.timeout_seconds) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            logger.warning(
                "nl_fallback_unavailable",
                reason=f"openresponses_http_{exc.code}",
                base_url=self.base_url,
                path=self.responses_path,
                patient_id=context.patient_id,
                participant_id=context.participant_id,
            )
            return CommandResult(action="unavailable", text="")
        except (URLError, OSError, ValueError):
            logger.exception(
                "nl_fallback_unavailable",
                reason="openresponses_transport_or_parse_error",
                base_url=self.base_url,
                path=self.responses_path,
                patient_id=context.patient_id,
                participant_id=context.participant_id,
            )
            return CommandResult(action="unavailable", text="")

        text_reply, action = self._extract_text(data)
        if not text_reply:
            return CommandResult(action="unavailable", text="")
        logger.info(
            "nl_fallback_used",
            source="openresponses_http",
            base_url=self.base_url,
            path=self.responses_path,
            patient_id=context.patient_id,
            participant_id=context.participant_id,
            action=action,
        )
        return CommandResult(action=action, text=text_reply)

    def _call_remote(self, payload: dict, context: ParticipantContext) -> CommandResult:
        last_error_reason = "unknown"
        for path in self._candidate_paths():
            req = Request(
                f"{self.base_url}{path}",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with urlopen(req, timeout=self.timeout_seconds) as resp:  # noqa: S310
                    data = json.loads(resp.read().decode("utf-8"))
            except HTTPError as exc:
                last_error_reason = f"http_{exc.code}"
                if exc.code in {404, 405}:
                    continue
                logger.exception(
                    "nl_fallback_unavailable",
                    reason=last_error_reason,
                    base_url=self.base_url,
                    path=path,
                    patient_id=context.patient_id,
                    participant_id=context.participant_id,
                )
                return CommandResult(action="unavailable", text="")
            except (URLError, OSError, ValueError):
                last_error_reason = "transport_or_parse_error"
                logger.exception(
                    "nl_fallback_unavailable",
                    reason=last_error_reason,
                    base_url=self.base_url,
                    path=path,
                    patient_id=context.patient_id,
                    participant_id=context.participant_id,
                )
                return CommandResult(action="unavailable", text="")

            text_reply, action = self._extract_text(data)
            if text_reply:
                logger.info(
                    "nl_fallback_used",
                    source="remote_bridge",
                    base_url=self.base_url,
                    path=path,
                    patient_id=context.patient_id,
                    participant_id=context.participant_id,
                    action=action,
                )
                return CommandResult(action=action, text=text_reply)

        via_openresponses = self._call_openresponses(payload.get("text", ""), context)
        if via_openresponses.action != "unavailable" and via_openresponses.text.strip():
            return via_openresponses

        logger.warning(
            "nl_fallback_unavailable",
            reason=last_error_reason,
            base_url=self.base_url,
            patient_id=context.patient_id,
            participant_id=context.participant_id,
        )
        return CommandResult(action="unavailable", text="")

    def handle(self, text: str, context: ParticipantContext) -> CommandResult:
        if not self.base_url:
            logger.warning("nl_fallback_unavailable", reason="missing_base_url")
            return CommandResult(action="unavailable", text="")
        via_openresponses = self._call_openresponses(text, context)
        if via_openresponses.action != "unavailable" and via_openresponses.text.strip():
            return via_openresponses
        if self._is_local_bridge_url() and self.win_service is not None:
            mapped_intent = fallback_intent(text)
            logger.info(
                "nl_fallback_used",
                source="inprocess_bridge",
                patient_id=context.patient_id,
                participant_id=context.participant_id,
                mapped_intent=mapped_intent,
            )
            local_text = resolve_fallback_text(text, context, self.win_service)
            if mapped_intent == "unmapped":
                logger.info(
                    "nl_fallback_unmapped",
                    source="inprocess_bridge",
                    patient_id=context.patient_id,
                    participant_id=context.participant_id,
                )
            return CommandResult(action="openclaw_fallback", text=local_text)

        grounding = self._grounding_context(context)
        payload = {
            "text": text,
            "participant_context": {
                "tenant_id": context.tenant_id,
                "participant_id": context.participant_id,
                "participant_role": context.participant_role.value,
                "patient_id": context.patient_id,
                "patient_timezone": context.patient_timezone,
                "patient_persona": context.patient_persona.value,
            },
            "allowed_actions": ["read", "write_via_mcp"],
            "grounding": grounding,
            "tool_hints": grounding.get("tool_hints", []),
            "response_guidance": {
                "answer_from_current_medications_first": True,
                "use_common_medication_purpose_guidance_when_available": True,
                "avoid_generic_refusal_when_grounding_is_present": True,
            },
        }
        return self._call_remote(payload, context)
