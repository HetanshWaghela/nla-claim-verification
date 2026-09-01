"""Execute Phase 3 claims, labels, recurrence, and the human checkpoint.

This module is intentionally local and sequential. Every OpenRouter request is
schema-validated, retried at most twice, and logged with its raw request and
response. Phase 4 is not implemented here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
LOGS = ROOT / "logs"
SOURCE_CODE = Path(__file__).resolve()

EXPLANATIONS_PATH = DATA / "explanations.parquet"
CONTEXTS_PATH = DATA / "contexts.parquet"
ACTIVATIONS_DIR = DATA / "activations"
PHASE2_GATE_PATH = RESULTS / "phase2_merge_gate.json"
OUTLIER_PATH = RESULTS / "outlier_flags.json"

STARTUP_EVIDENCE_PATH = RESULTS / "phase3_startup.json"
PREFLIGHT_EVIDENCE_PATH = RESULTS / "phase3_preflight.json"
SPLIT_EVIDENCE_PATH = RESULTS / "phase3_split.json"
LABEL_EVIDENCE_PATH = RESULTS / "phase3_label.json"
RECURRENCE_EVIDENCE_PATH = RESULTS / "phase3_recurrence.json"
RECURRENCE_SPOT_CHECK_PATH = RESULTS / "recurrence_spot_checks.json"
HUMAN_SAMPLE_EVIDENCE_PATH = RESULTS / "phase3_human_sample.json"
COST_GUARD_PATH = RESULTS / "openrouter_cost_guard.json"

CLAIMS_PATH = DATA / "claims.parquet"
LABELED_CLAIMS_PATH = DATA / "claims_labeled.parquet"
SPLIT_CHECKPOINT_PATH = RESULTS / "phase3_split_checkpoint.json"
LABEL_CHECKPOINT_PATH = RESULTS / "phase3_label_checkpoint.json"
RECURRENCE_CHECKPOINT_PATH = RESULTS / "phase3_recurrence_checkpoint.json"
LABEL_DISTRIBUTION_PATH = RESULTS / "label_distribution.json"
HUMAN_SAMPLE_PATH = RESULTS / "human_label_sample.md"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_CHAT_URL = f"{OPENROUTER_BASE_URL}/chat/completions"
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"
TEMPERATURE = 0
PHASE_BUDGET = Decimal("60")
PRIMARY_COUNT = 300
RECURRENCE_COUNT = 300

REQUESTED_SPLITTER_MODEL = "anthropic/claude-haiku-4.5"
REQUESTED_LABELER_MODEL = "anthropic/claude-sonnet-5"

SPLITTER_PROMPT = (
    """You will be given a paragraph that describes the contents of a language model's internal state. Split it into a numbered list of atomic factual claims. Rules:
- One claim per line, self-contained (resolve pronouns).
- Preserve the original wording as much as possible.
- Include claims about the text/topic (e.g. "the text is about X", "the person named Y is mentioned") AND claims about the model's cognition (e.g. "the model is planning to answer Z").
- Do not merge, do not add, do not interpret.
- Also output, for each claim, the exact substring(s) of the paragraph it came from, as """
    + chr(96)
    + """SPAN: ..."""
    + chr(96)
    + """.
Paragraph:
{explanation}"""
)

LABELER_PROMPT = """A model wrote a description of a text. You get the ORIGINAL TEXT and one CLAIM from the description. Label the claim:
- TRUE: directly supported by the original text.
- RELATED_FALSE: not supported (or contradicted), but thematically consistent with the text (plausible-sounding specifics, wrong names/numbers/titles on the right topic).
- UNRELATED_FALSE: not supported and off-topic for this text.
- UNVERIFIABLE: a claim about the model's internal cognition or anything that cannot be checked against the text (e.g. "the model expects a question next").
Output exactly one label and a one-sentence justification.
ORIGINAL TEXT:
{context}
CLAIM:
{claim_text}"""

LABELS = {"TRUE", "RELATED_FALSE", "UNRELATED_FALSE", "UNVERIFIABLE"}
CLAIM_TYPES = {"CONTEXT", "COGNITION"}


class Phase3Error(RuntimeError):
    """A specification or guardrail failure that must halt the phase."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_metadata() -> dict[str, Any]:
    digest = hashlib.sha256(SOURCE_CODE.read_bytes()).hexdigest()
    return {
        "source_path": str(SOURCE_CODE),
        "source_sha256": digest,
        "source_mtime_ns": SOURCE_CODE.stat().st_mtime_ns,
    }


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _atomic_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise Phase3Error(f"refusing to write empty parquet: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, temporary)
    os.replace(temporary, path)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise Phase3Error(f"missing parquet input: {path}")
    return pq.read_table(path).to_pylist()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise Phase3Error(f"missing evidence file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Phase3Error(f"evidence is not a JSON object: {path}")
    return value


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:180]


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_string(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _sum_costs(values: list[Decimal | None]) -> Decimal | None:
    if any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal("0"))


def _assert_predecessor(path: Path, expected_status: str = "passed") -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("status") != expected_status:
        raise Phase3Error(
            f"predecessor evidence is not {expected_status}: {path} "
            f"(status={payload.get('status')!r})"
        )
    return payload


def _assert_runtime_preflight() -> dict[str, Any]:
    _assert_predecessor(STARTUP_EVIDENCE_PATH)
    preflight = _assert_predecessor(PREFLIGHT_EVIDENCE_PATH)
    current = _source_metadata()
    if preflight.get("source_sha256") != current["source_sha256"]:
        raise Phase3Error("preflight was generated for a different source revision")
    if PREFLIGHT_EVIDENCE_PATH.stat().st_mtime_ns <= SOURCE_CODE.stat().st_mtime_ns:
        raise Phase3Error("preflight evidence is not newer than the phase code")
    return preflight


def _activation_vector_width(schema: pa.Schema) -> int | None:
    field = schema.field("activation_vector")
    list_size = getattr(field.type, "list_size", None)
    return None if list_size is None else int(list_size)


def run_startup() -> None:
    """Assert the inherited Phase 2 state and write the G1 evidence."""

    evidence: dict[str, Any] = {
        "status": "failed",
        "created_at": _now(),
        "step": "phase3_startup",
        "checks": {},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    try:
        explanations = pq.read_table(EXPLANATIONS_PATH)
        required_explanation_columns = {
            "context_id",
            "stratum",
            "position_offset",
            "sample_idx",
            "text",
            "batch_size",
        }
        explanation_check = {
            "exists": EXPLANATIONS_PATH.exists(),
            "rows": explanations.num_rows,
            "required_columns_present": required_explanation_columns
            <= set(explanations.column_names),
        }
        if explanations.num_rows != 3900 or not explanation_check["required_columns_present"]:
            raise Phase3Error(f"explanations inherited-state check failed: {explanation_check}")

        contexts = pq.read_table(CONTEXTS_PATH)
        context_check = {
            "exists": CONTEXTS_PATH.exists(),
            "rows": contexts.num_rows,
            "required_columns_present": {"context_id", "text", "stratum"}
            <= set(contexts.column_names),
        }
        if contexts.num_rows != 300 or not context_check["required_columns_present"]:
            raise Phase3Error(f"contexts inherited-state check failed: {context_check}")

        activation_paths = sorted(ACTIVATIONS_DIR.glob("shard_*.parquet"))
        activation_rows = 0
        widths: list[int | None] = []
        activation_columns: set[str] | None = None
        for path in activation_paths:
            metadata = pq.read_metadata(path)
            activation_rows += metadata.num_rows
            schema = pq.read_schema(path)
            widths.append(_activation_vector_width(schema))
            columns = set(schema.names)
            activation_columns = (
                columns if activation_columns is None else activation_columns & columns
            )
        activation_check = {
            "directory_exists": ACTIVATIONS_DIR.exists(),
            "shard_count": len(activation_paths),
            "rows": activation_rows,
            "common_columns": sorted(activation_columns or set()),
            "vector_widths": widths,
            "layer": 42,
        }
        if (
            len(activation_paths) != 30
            or activation_rows != 3000
            or activation_columns is None
            or not {"context_id", "position_offset", "activation_vector"}
            <= activation_columns
            or any(width not in (None, 5120) for width in widths)
        ):
            raise Phase3Error(f"activation inherited-state check failed: {activation_check}")

        phase2_gate = _read_json(PHASE2_GATE_PATH)
        phase2_check = {
            "path_exists": PHASE2_GATE_PATH.exists(),
            "status": phase2_gate.get("status"),
            "rows_total": phase2_gate.get("rows_total"),
            "all_gates_pass": phase2_gate.get(
                "all_gates_pass", phase2_gate.get("status") == "passed"
            ),
        }
        if phase2_gate.get("status") != "passed":
            raise Phase3Error(f"Phase 2 merge gate did not pass: {phase2_check}")

        outlier_check = {
            "path_exists": OUTLIER_PATH.exists(),
            "value": json.loads(OUTLIER_PATH.read_text(encoding="utf-8")),
        }
        if not OUTLIER_PATH.exists():
            raise Phase3Error("missing results/outlier_flags.json")

        evidence["checks"] = {
            "explanations": explanation_check,
            "contexts": context_check,
            "activations": activation_check,
            "phase2_merge_gate": phase2_check,
            "outlier_flags": outlier_check,
        }
        evidence["status"] = "passed"
        _atomic_json(STARTUP_EVIDENCE_PATH, evidence)
    except Exception as exc:
        evidence["error"] = _error_text(exc)
        _atomic_json(STARTUP_EVIDENCE_PATH, evidence)
        raise


def _message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise Phase3Error("OpenRouter response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise Phase3Error("OpenRouter response has no message")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "".join(parts)
    raise Phase3Error("OpenRouter message content is not text")


def _json_from_text(text: str) -> Any:
    stripped = text.strip()
    fence = chr(96) * 3
    if stripped.startswith(fence):
        stripped = re.sub(r"^" + re.escape(fence) + r"(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*" + re.escape(fence) + r"$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, character in enumerate(stripped):
            if character not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(stripped[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise Phase3Error("response content is not valid JSON")


def _string_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return " ".join(item.strip() for item in value).strip()
    raise Phase3Error("schema field is not a string")


def parse_split_response(response: dict[str, Any]) -> list[dict[str, str]]:
    content = _message_content(response)
    try:
        decoded = _json_from_text(content)
    except Phase3Error:
        decoded = None

    if decoded is not None:
        items: Any = decoded
        if isinstance(decoded, dict):
            items = decoded.get("claims", decoded.get("items"))
        if isinstance(items, list):
            parsed: list[dict[str, str]] = []
            for item in items:
                if not isinstance(item, dict):
                    raise Phase3Error("split claim item is not an object")
                claim = item.get("claim_text", item.get("text", item.get("claim")))
                span = item.get("span_text", item.get("span", item.get("SPAN")))
                claim_text = _string_value(claim)
                span_text = _string_value(span)
                if not claim_text or not span_text:
                    raise Phase3Error("split claim or span is empty")
                parsed.append({"claim_text": claim_text, "span_text": span_text})
            if parsed:
                return parsed
        if isinstance(decoded, (list, dict)):
            decoded_keys = set(decoded) if isinstance(decoded, dict) else set()
            if decoded_keys & {"claims", "items"}:
                raise Phase3Error(
                    "split JSON does not contain a nonempty claims list"
                )

    claims: list[str] = []
    spans: list[str] = []
    for line in content.splitlines():
        match = re.match(r"^\s*(?:\d+[\.)]\s*|[-*]\s+)(.+?)\s*$", line)
        if match and not line.strip().upper().startswith("SPAN:"):
            claims.append(match.group(1).strip())
            continue
        if line.strip().upper().startswith("SPAN:"):
            spans.append(line.split(":", 1)[1].strip().strip('"'))
    if not claims or len(claims) != len(spans):
        raise Phase3Error("plain split response does not pair claims and spans")
    return [
        {"claim_text": claim, "span_text": span}
        for claim, span in zip(claims, spans)
        if claim and span
    ]


def parse_label_response(response: dict[str, Any]) -> dict[str, str]:
    content = _message_content(response)
    try:
        decoded = _json_from_text(content)
    except Phase3Error:
        decoded = None
    if isinstance(decoded, dict):
        label = decoded.get("label")
        justification = decoded.get("justification", decoded.get("reason"))
        if isinstance(label, str) and isinstance(justification, str):
            normalized = label.strip().upper()
            if normalized in LABELS and justification.strip():
                return {"label": normalized, "justification": justification.strip()}
        raise Phase3Error("label JSON does not match the required schema")

    match = re.search(
        r"\b(TRUE|RELATED_FALSE|UNRELATED_FALSE|UNVERIFIABLE)\b",
        content,
        flags=re.IGNORECASE,
    )
    if not match:
        raise Phase3Error("label response has no recognized label")
    justification = content[match.end():].strip(" \n:-")
    if not justification:
        raise Phase3Error("label response has no justification")
    return {"label": match.group(1).upper(), "justification": justification}


def parse_recurrence_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    content = _message_content(response)
    decoded = _json_from_text(content)
    if not isinstance(decoded, dict) or not isinstance(decoded.get("claims"), list):
        raise Phase3Error("recurrence response does not contain claims")
    parsed: list[dict[str, Any]] = []
    for item in decoded["claims"]:
        if not isinstance(item, dict):
            raise Phase3Error("recurrence item is not an object")
        claim_id = item.get("claim_id")
        positions = item.get(
            "recurrence_positions",
            item.get("positions", item.get("sibling_positions")),
        )
        samples = item.get(
            "recurrence_samples",
            item.get("samples", item.get("primary_samples")),
        )
        if (
            not isinstance(claim_id, str)
            or not isinstance(positions, int)
            or not isinstance(samples, int)
        ):
            raise Phase3Error("recurrence item has invalid fields")
        parsed.append(
            {
                "claim_id": claim_id,
                "recurrence_positions": positions,
                "recurrence_samples": samples,
            }
        )
    if not parsed:
        raise Phase3Error("recurrence response claims list is empty")
    return parsed


def _supports_request_parameters(metadata: dict[str, Any]) -> bool:
    supported = metadata.get("supported_parameters")
    if not isinstance(supported, list):
        return False
    return {"temperature", "max_tokens", "response_format"} <= set(supported)


def _model_candidates(
    available_models: dict[str, dict[str, Any]],
    requested: str,
    tier: str,
) -> tuple[str, str | None]:
    available_ids = set(available_models)
    if requested in available_ids and _supports_request_parameters(
        available_models[requested]
    ):
        return requested, None
    preferred = {
        "haiku": [
            "anthropic/claude-haiku-4",
            "anthropic/claude-3.5-haiku",
            "anthropic/claude-3-haiku",
        ],
        "sonnet": [
            "anthropic/claude-sonnet-4.6",
            "anthropic/claude-sonnet-4.5",
            "anthropic/claude-sonnet-4",
            "anthropic/claude-3.7-sonnet",
            "anthropic/claude-3.5-sonnet",
            "anthropic/claude-3-sonnet",
        ],
    }[tier]
    for candidate in preferred:
        if candidate in available_ids and _supports_request_parameters(
            available_models[candidate]
        ):
            return (
                candidate,
                f"{requested} unavailable for required parameters; selected closest "
                f"same-tier listed {candidate}",
            )
    same_tier = sorted(
        model_id
        for model_id in available_ids
        if model_id.startswith("anthropic/")
        and tier in model_id.lower()
        and _supports_request_parameters(available_models[model_id])
    )
    if same_tier:
        return (
            same_tier[0],
            f"{requested} unavailable for required parameters; selected same-tier "
            f"listed {same_tier[0]}",
        )
    raise Phase3Error(
        f"no available Anthropic {tier} model for required parameters and {requested}"
    )


def _http_json(
    url: str,
    headers: dict[str, str],
    body: bytes | None = None,
) -> tuple[int, str, dict[str, Any] | None]:
    method = "POST" if body is not None else "GET"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            status = int(response.status)
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raw = exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise Phase3Error(f"OpenRouter network error: {exc}") from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = None
    return status, raw, decoded


def _model_list(api_key: str) -> tuple[list[dict[str, Any]], str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    status, raw, decoded = _http_json(OPENROUTER_MODELS_URL, headers)
    _atomic_json(
        LOGS / "phase3_openrouter_models.json",
        {
            "created_at": _now(),
            "url": OPENROUTER_MODELS_URL,
            "status_code": status,
            "response_raw": raw.replace(api_key, "[REDACTED]"),
        },
    )
    if status < 200 or status >= 300:
        raise Phase3Error(f"OpenRouter models request failed with HTTP {status}")
    if not isinstance(decoded, dict) or not isinstance(decoded.get("data"), list):
        raise Phase3Error("OpenRouter models response has no data list")
    return [item for item in decoded["data"] if isinstance(item, dict)], raw


def _cost_from_response(
    response: dict[str, Any],
    model_metadata: dict[str, Any] | None,
) -> tuple[Decimal | None, str, dict[str, Any]]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    direct = _decimal(usage.get("cost"))
    if direct is None:
        direct = _decimal(response.get("cost"))
    if direct is not None:
        return (
            direct,
            "OpenRouter response usage.cost",
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        )
    pricing = (model_metadata or {}).get("pricing")
    if (
        isinstance(pricing, dict)
        and prompt_tokens is not None
        and completion_tokens is not None
    ):
        prompt_price = _decimal(pricing.get("prompt"))
        completion_price = _decimal(pricing.get("completion"))
        if prompt_price is not None and completion_price is not None:
            calculated = (
                prompt_price * Decimal(str(prompt_tokens))
                + completion_price * Decimal(str(completion_tokens))
            )
            return (
                calculated,
                "OpenRouter model pricing x response token usage",
                {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "prompt_price_per_token": _decimal_string(prompt_price),
                    "completion_price_per_token": _decimal_string(completion_price),
                },
            )
    return (
        None,
        "unavailable",
        {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    )


class OpenRouterClient:
    """Small OpenRouter client with raw per-attempt logging."""

    def __init__(
        self,
        api_key: str,
        selected_models: dict[str, str],
        model_metadata: dict[str, dict[str, Any]],
    ) -> None:
        self.api_key = api_key
        self.selected_models = selected_models
        self.model_metadata = model_metadata
        self.attempts: list[dict[str, Any]] = []

    def call(
        self,
        *,
        step: str,
        call_id: str,
        role: str,
        prompt: str,
        parser: Callable[[dict[str, Any]], Any],
        max_tokens: int,
    ) -> tuple[Any, dict[str, Any]]:
        model = self.selected_models[role]
        request_body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE,
            "max_tokens": max_tokens,
            "provider": {"require_parameters": True},
            "response_format": {"type": "json_object"},
        }
        last_error: str | None = None
        for attempt_index in range(3):
            started = time.time()
            log_path = LOGS / (
                f"phase3_{_safe_name(step)}_{_safe_name(call_id)}_"
                f"attempt_{attempt_index}.json"
            )
            if log_path.exists():
                log_path = LOGS / (
                    f"phase3_{_safe_name(step)}_{_safe_name(call_id)}_"
                    f"attempt_{attempt_index}_{time.time_ns()}.json"
                )
            log: dict[str, Any] = {
                "created_at": _now(),
                "step": step,
                "call_id": call_id,
                "role": role,
                "model": model,
                "temperature": TEMPERATURE,
                "attempt": attempt_index,
                "request": request_body,
            }
            cost: Decimal | None = None
            cost_basis = "unavailable"
            usage: dict[str, Any] = {}
            try:
                status, raw, decoded = _http_json(
                    OPENROUTER_CHAT_URL,
                    {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
                )
                log["status_code"] = status
                log["response_raw"] = raw.replace(self.api_key, "[REDACTED]")
                if status < 200 or status >= 300:
                    raise Phase3Error(f"OpenRouter chat request failed with HTTP {status}")
                if not isinstance(decoded, dict):
                    raise Phase3Error("OpenRouter chat response is not a JSON object")
                cost, cost_basis, usage = _cost_from_response(
                    decoded, self.model_metadata.get(model)
                )
                log["usage"] = usage
                log["cost"] = _decimal_string(cost)
                log["cost_basis"] = cost_basis
                parsed = parser(decoded)
                log["schema_validation"] = "passed"
                log["elapsed_seconds"] = time.time() - started
                _atomic_json(log_path, log)
                attempt_info = {
                    "step": step,
                    "call_id": call_id,
                    "role": role,
                    "model": model,
                    "attempt": attempt_index,
                    "cost": _decimal_string(cost),
                    "cost_basis": cost_basis,
                    "usage": usage,
                    "log_path": str(log_path),
                }
                self.attempts.append(attempt_info)
                return parsed, attempt_info
            except Exception as exc:
                last_error = _error_text(exc)
                log["error"] = last_error
                log["cost"] = _decimal_string(cost)
                log["cost_basis"] = cost_basis
                log["usage"] = usage
                log["elapsed_seconds"] = time.time() - started
                _atomic_json(log_path, log)
                self.attempts.append(
                    {
                        "step": step,
                        "call_id": call_id,
                        "role": role,
                        "model": model,
                        "attempt": attempt_index,
                        "cost": _decimal_string(cost),
                        "cost_basis": cost_basis,
                        "usage": usage,
                        "log_path": str(log_path),
                        "error": last_error,
                    }
                )
                if attempt_index == 2:
                    raise Phase3Error(
                        f"call {step}/{call_id} failed after two retries: {last_error}"
                    ) from exc
        raise Phase3Error(last_error or "OpenRouter call failed")


def _client_from_preflight(preflight: dict[str, Any]) -> OpenRouterClient:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise Phase3Error("OPENROUTER_API_KEY is not present in the process environment")
    models = preflight.get("models")
    if not isinstance(models, dict):
        raise Phase3Error("preflight has no model selection")
    selected = {
        "splitter": models.get("splitter", {}).get("selected"),
        "labeler": models.get("labeler", {}).get("selected"),
    }
    if not all(isinstance(value, str) for value in selected.values()):
        raise Phase3Error("preflight model selection is incomplete")
    metadata: dict[str, dict[str, Any]] = {}
    for role_name in ("splitter", "labeler"):
        role_metadata = models.get(role_name, {}).get("metadata", {})
        if isinstance(role_metadata, dict):
            metadata[selected[role_name]] = role_metadata
    return OpenRouterClient(api_key, selected, metadata)


def _attempt_costs(client: OpenRouterClient, step: str) -> list[Decimal | None]:
    return [
        _decimal(item.get("cost"))
        for item in client.attempts
        if item.get("step") == step
    ]


def _preflight_cost() -> Decimal | None:
    if not PREFLIGHT_EVIDENCE_PATH.exists():
        return None
    payload = _read_json(PREFLIGHT_EVIDENCE_PATH)
    return _decimal(payload.get("cost", {}).get("total"))


def _completed_step_cost(evidence_path: Path) -> Decimal | None:
    if not evidence_path.exists():
        return None
    payload = _read_json(evidence_path)
    return _decimal(payload.get("cost", {}).get("total"))


def _cost_guard_needed(step: str) -> bool:
    if not COST_GUARD_PATH.exists():
        return True
    try:
        payload = _read_json(COST_GUARD_PATH)
    except Exception:
        return True
    return payload.get("step") != step or payload.get("status") != "passed"


def _write_cost_guard(
    *,
    client: OpenRouterClient,
    step: str,
    planned_calls: int,
    phase3_completed_costs: list[Decimal | None],
    recurrence_planned_calls: int,
) -> dict[str, Any]:
    costs = _attempt_costs(client, step)
    measured_sum = _sum_costs(costs)
    projection_error: str | None = None
    projected_step: Decimal | None = None
    average: Decimal | None = None
    if not costs or measured_sum is None:
        projection_error = "one or more measured request costs are unavailable"
    else:
        average = measured_sum / Decimal(len(costs))
        projected_step = average * Decimal(planned_calls)

    completed_sum = _sum_costs(phase3_completed_costs)
    recurrence_projection: Decimal | None = None
    if average is not None:
        recurrence_projection = average * Decimal(recurrence_planned_calls)
    known_projection = None
    if completed_sum is not None and projected_step is not None and recurrence_projection is not None:
        known_projection = (
            (_preflight_cost() or Decimal("0"))
            + completed_sum
            + projected_step
            + recurrence_projection
        )
    status = "passed"
    if projection_error is not None:
        status = "halted_insufficient_cost_data"
    elif known_projection is not None and known_projection > PHASE_BUDGET:
        status = "halted_budget_projection"

    evidence = {
        "status": status,
        "created_at": _now(),
        "step": step,
        "budget_usd": _decimal_string(PHASE_BUDGET),
        "measured_attempt_count": len(costs),
        "measured_cost_total_usd": _decimal_string(measured_sum),
        "measured_average_cost_usd": _decimal_string(average),
        "planned_calls_for_step": planned_calls,
        "projected_step_cost_usd": _decimal_string(projected_step),
        "completed_phase3_costs_usd": [
            _decimal_string(value) for value in phase3_completed_costs
        ],
        "recurrence_planned_calls": recurrence_planned_calls,
        "projected_recurrence_cost_usd": _decimal_string(recurrence_projection),
        "known_phase3_plus_recurrence_projection_usd": _decimal_string(known_projection),
        "phase4_projection": "not_started; no Phase 4 cost estimate made",
        "billing_basis": (
            "OpenRouter response usage.cost when present, otherwise the selected "
            "model's listed per-token pricing multiplied by that response's token usage"
        ),
        "projection_error": projection_error,
        "decision": (
            "halt"
            if status.startswith("halted")
            else "continue; Phase 4 remains prohibited until human checkpoint clears"
        ),
    }
    _atomic_json(COST_GUARD_PATH, evidence)
    if status != "passed":
        raise Phase3Error(f"OpenRouter cost guard halted: {evidence}")
    return evidence


def run_preflight() -> None:
    """Run configuration checks and two schema-validated dummy calls."""

    evidence: dict[str, Any] = {
        "status": "failed",
        "created_at": _now(),
        "step": "phase3_preflight",
        **_source_metadata(),
        "api_url": OPENROUTER_BASE_URL,
        "temperature": TEMPERATURE,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    try:
        _assert_predecessor(STARTUP_EVIDENCE_PATH)
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise Phase3Error("OPENROUTER_API_KEY is missing")
        models, models_raw = _model_list(api_key)
        by_id = {
            str(item.get("id")): item
            for item in models
            if isinstance(item.get("id"), str)
        }
        available_ids = set(by_id)
        splitter_model, splitter_substitution = _model_candidates(
            by_id, REQUESTED_SPLITTER_MODEL, "haiku"
        )
        labeler_model, labeler_substitution = _model_candidates(
            by_id, REQUESTED_LABELER_MODEL, "sonnet"
        )
        selected_models = {
            "splitter": {
                "requested": REQUESTED_SPLITTER_MODEL,
                "selected": splitter_model,
                "substitution": splitter_substitution,
                "metadata": by_id.get(splitter_model, {}),
            },
            "labeler": {
                "requested": REQUESTED_LABELER_MODEL,
                "selected": labeler_model,
                "substitution": labeler_substitution,
                "metadata": by_id.get(labeler_model, {}),
            },
        }
        client = OpenRouterClient(
            api_key,
            {"splitter": splitter_model, "labeler": labeler_model},
            {
                splitter_model: by_id.get(splitter_model, {}),
                labeler_model: by_id.get(labeler_model, {}),
            },
        )
        dummy_explanation = "The text describes a small river. The model expects a question next."
        dummy_split, split_info = client.call(
            step="preflight_split",
            call_id="dummy",
            role="splitter",
            prompt=SPLITTER_PROMPT.replace("{explanation}", dummy_explanation),
            parser=parse_split_response,
            max_tokens=512,
        )
        if not dummy_split:
            raise Phase3Error("dummy split schema validation returned no claims")
        dummy_label, label_info = client.call(
            step="preflight_label",
            call_id="dummy",
            role="labeler",
            prompt=LABELER_PROMPT.replace(
                "{context}", "A small river crosses the valley."
            ).replace("{claim_text}", "The text describes a small river."),
            parser=parse_label_response,
            max_tokens=256,
        )
        if dummy_label["label"] not in LABELS or not dummy_label["justification"]:
            raise Phase3Error("dummy label schema validation returned invalid fields")
        if "small river" not in dummy_explanation:
            raise Phase3Error("dummy span dry-run failed")

        import_checks = {
            "json": True,
            "pyarrow": True,
            "urllib": True,
            "source_exists": SOURCE_CODE.exists(),
        }
        directory_checks = {
            "data": DATA.exists(),
            "results": RESULTS.exists(),
            "logs": LOGS.exists(),
            "claims_parent": CLAIMS_PATH.parent.exists(),
        }
        if not all(import_checks.values()) or not all(directory_checks.values()):
            raise Phase3Error(
                f"preflight import or directory check failed: {import_checks}, {directory_checks}"
            )
        costs = [_decimal(split_info.get("cost")), _decimal(label_info.get("cost"))]
        total = _sum_costs(costs)
        if total is None:
            raise Phase3Error("preflight call cost was unavailable")
        evidence.update(
            {
                "status": "passed",
                "openrouter_key_valid": True,
                "models": selected_models,
                "available_anthropic_model_count": sum(
                    1 for model_id in available_ids if model_id.startswith("anthropic/")
                ),
                "model_list_response_sha256": hashlib.sha256(
                    models_raw.encode("utf-8")
                ).hexdigest(),
                "import_checks": import_checks,
                "directory_checks": directory_checks,
                "dummy_split": {
                    "schema_validated": True,
                    "claim_count": len(dummy_split),
                    "cost_usd": split_info.get("cost"),
                    "log_path": split_info.get("log_path"),
                },
                "dummy_label": {
                    "schema_validated": True,
                    "label": dummy_label["label"],
                    "cost_usd": label_info.get("cost"),
                    "log_path": label_info.get("log_path"),
                },
                "cost": {
                    "total": _decimal_string(total),
                    "billing_basis": (
                        "OpenRouter response usage.cost when present, otherwise the "
                        "selected model's listed per-token pricing multiplied by "
                        "response token usage"
                    ),
                },
            }
        )
        _atomic_json(PREFLIGHT_EVIDENCE_PATH, evidence)
    except Exception as exc:
        evidence["error"] = _error_text(exc)
        _atomic_json(PREFLIGHT_EVIDENCE_PATH, evidence)
        raise


def _split_rows_for_explanation(
    *,
    explanation: dict[str, Any],
    parsed: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[int]]:
    text = str(explanation["text"])
    rows: list[dict[str, Any]] = []
    mismatch_indices: list[int] = []
    for claim_index, item in enumerate(parsed):
        claim_text = item["claim_text"]
        span_text = item["span_text"]
        mismatch = span_text not in text
        if not mismatch:
            assert span_text in text
        else:
            mismatch_indices.append(claim_index)
        rows.append(
            {
                "claim_id": (
                    f"{explanation['context_id']}/"
                    f"{explanation['generation_index']}/{claim_index:03d}"
                ),
                "context_id": explanation["context_id"],
                "explanation_id": f"generation_{explanation['generation_index']}",
                "generation_index": int(explanation["generation_index"]),
                "stratum": explanation["stratum"],
                "claim_index": claim_index,
                "claim_text": claim_text,
                "span_text": span_text,
                "span_mismatch": bool(mismatch),
            }
        )
    return rows, mismatch_indices


def _split_checkpoint_rows() -> tuple[
    dict[int, list[dict[str, Any]]], list[dict[str, Any]]
]:
    if not SPLIT_CHECKPOINT_PATH.exists():
        return {}, []
    payload = _read_json(SPLIT_CHECKPOINT_PATH)
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise Phase3Error("split checkpoint rows are not a list")
    by_generation: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise Phase3Error("split checkpoint row is not an object")
        generation_index = int(row["generation_index"])
        by_generation.setdefault(generation_index, []).append(row)
    return by_generation, rows


def run_split() -> None:
    """Split the 300 primary explanations and enforce the span gate."""

    evidence: dict[str, Any] = {
        "status": "failed",
        "created_at": _now(),
        "step": "phase3_split",
        "models": {},
    }
    client: OpenRouterClient | None = None
    try:
        preflight = _assert_runtime_preflight()
        if SPLIT_EVIDENCE_PATH.exists() and CLAIMS_PATH.exists():
            existing = _read_json(SPLIT_EVIDENCE_PATH)
            if existing.get("status") == "passed":
                return
        client = _client_from_preflight(preflight)
        explanations = _read_rows(EXPLANATIONS_PATH)
        primary = [
            row
            for row in explanations
            if int(row["position_offset"]) == 0 and int(row["sample_idx"]) == 0
        ]
        primary.sort(key=lambda row: int(row["generation_index"]))
        if len(primary) != PRIMARY_COUNT:
            raise Phase3Error(f"expected 300 primary explanations, found {len(primary)}")
        if len({row["context_id"] for row in primary}) != PRIMARY_COUNT:
            raise Phase3Error("primary explanations do not have unique context IDs")

        checkpoint_by_generation, checkpoint_rows = _split_checkpoint_rows()
        all_rows: list[dict[str, Any]] = list(checkpoint_rows)
        flagged_rows: list[dict[str, Any]] = []
        completed_generations = set(checkpoint_by_generation)
        for explanation in primary:
            generation_index = int(explanation["generation_index"])
            if generation_index in completed_generations:
                rows = checkpoint_by_generation[generation_index]
                flagged_rows.extend(row for row in rows if row.get("span_mismatch"))
                continue
            parsed, _ = client.call(
                step="split",
                call_id=str(explanation["context_id"]),
                role="splitter",
                prompt=SPLITTER_PROMPT.replace(
                    "{explanation}", str(explanation["text"])
                ),
                parser=parse_split_response,
                max_tokens=1024,
            )
            rows, mismatches = _split_rows_for_explanation(
                explanation=explanation, parsed=parsed
            )
            if mismatches:
                retry_parsed, _ = client.call(
                    step="split_span_retry",
                    call_id=str(explanation["context_id"]),
                    role="splitter",
                    prompt=SPLITTER_PROMPT.replace(
                        "{explanation}", str(explanation["text"])
                    ),
                    parser=parse_split_response,
                    max_tokens=1024,
                )
                rows, mismatches = _split_rows_for_explanation(
                    explanation=explanation, parsed=retry_parsed
                )
            all_rows.extend(rows)
            checkpoint_by_generation[generation_index] = rows
            completed_generations.add(generation_index)
            flagged_rows.extend(row for row in rows if row.get("span_mismatch"))
            _atomic_json(
                SPLIT_CHECKPOINT_PATH,
                {
                    "status": "running",
                    "created_at": _now(),
                    "completed_explanations": len(completed_generations),
                    "rows": all_rows,
                },
            )
            if len(_attempt_costs(client, "split")) >= 50 and _cost_guard_needed("split"):
                _write_cost_guard(
                    client=client,
                    step="split",
                    planned_calls=PRIMARY_COUNT,
                    phase3_completed_costs=[],
                    recurrence_planned_calls=RECURRENCE_COUNT,
                )

        if len(completed_generations) != PRIMARY_COUNT:
            raise Phase3Error("split did not complete all 300 explanations")
        all_rows.sort(key=lambda row: row["claim_id"])
        claim_counts = [
            len(checkpoint_by_generation[int(row["generation_index"])])
            for row in primary
        ]
        median_count = statistics.median(claim_counts)
        distribution = {
            "minimum": min(claim_counts),
            "maximum": max(claim_counts),
            "median": median_count,
            "mean": statistics.mean(claim_counts),
            "counts": {
                str(count): claim_counts.count(count)
                for count in sorted(set(claim_counts))
            },
        }
        if not 4 <= median_count <= 15:
            examples = [
                {
                    "context_id": row["context_id"],
                    "generation_index": row["generation_index"],
                    "explanation": row["text"],
                    "claim_count": len(
                        checkpoint_by_generation[int(row["generation_index"])]
                    ),
                }
                for row in primary[:5]
            ]
            evidence.update(
                {
                    "status": "failed",
                    "gate": "claim_count_median_4_to_15",
                    "claim_count_distribution": distribution,
                    "examples": examples,
                }
            )
            _atomic_json(SPLIT_EVIDENCE_PATH, evidence)
            raise Phase3Error(f"split claim-count median gate failed: {distribution}")

        _atomic_parquet(CLAIMS_PATH, all_rows)
        total_cost = _sum_costs(_attempt_costs(client, "split")) or Decimal("0")
        evidence.update(
            {
                "status": "passed",
                "models": {
                    "requested": REQUESTED_SPLITTER_MODEL,
                    "selected": client.selected_models["splitter"],
                    "temperature": TEMPERATURE,
                    "substitution": preflight["models"]["splitter"].get("substitution"),
                },
                "explanations_split": len(completed_generations),
                "claims_total": len(all_rows),
                "claim_count_distribution": distribution,
                "span_mismatch_count": len(flagged_rows),
                "span_mismatch_rows": flagged_rows,
                "cost": {
                    "total": _decimal_string(total_cost),
                    "attempt_count": len(_attempt_costs(client, "split")),
                    "billing_basis": (
                        "OpenRouter response usage.cost when present, otherwise the "
                        "selected model's listed per-token pricing multiplied by "
                        "response token usage"
                    ),
                },
                "output": str(CLAIMS_PATH),
            }
        )
        _atomic_json(SPLIT_EVIDENCE_PATH, evidence)
        if len(_attempt_costs(client, "split")) >= 50:
            _write_cost_guard(
                client=client,
                step="split",
                planned_calls=PRIMARY_COUNT,
                phase3_completed_costs=[total_cost],
                recurrence_planned_calls=RECURRENCE_COUNT,
            )
    except Exception as exc:
        evidence["error"] = _error_text(exc)
        if client is not None:
            evidence["cost"] = {
                "total": _decimal_string(
                    _sum_costs(_attempt_costs(client, "split"))
                ),
                "billing_basis": (
                    "OpenRouter response usage.cost when present, otherwise the "
                    "selected model's listed per-token pricing multiplied by "
                    "response token usage"
                ),
            }
        _atomic_json(SPLIT_EVIDENCE_PATH, evidence)
        raise


def _infer_claim_type(label: str, claim_text: str, justification: str) -> str:
    if label != "UNVERIFIABLE":
        return "CONTEXT"
    cognition_terms = (
        "model",
        "cognition",
        "cognitive",
        "expects",
        "expecting",
        "planning",
        "plan to",
        "thinking",
        "internal",
        "believes",
        "intends",
        "predict",
        "prediction",
        "answer next",
    )
    joined = f"{claim_text} {justification}".lower()
    return "COGNITION" if any(term in joined for term in cognition_terms) else "CONTEXT"


def _label_checkpoint() -> dict[str, dict[str, Any]]:
    if not LABEL_CHECKPOINT_PATH.exists():
        return {}
    payload = _read_json(LABEL_CHECKPOINT_PATH)
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise Phase3Error("label checkpoint rows are not a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("claim_id"), str):
            raise Phase3Error("label checkpoint row is invalid")
        result[row["claim_id"]] = row
    return result


def _distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_stratum: dict[str, Any] = {}
    for stratum in sorted({str(row["stratum"]) for row in rows}):
        stratum_rows = [row for row in rows if str(row["stratum"]) == stratum]
        by_type: dict[str, Any] = {}
        for claim_type in sorted({str(row["claim_type"]) for row in stratum_rows}):
            type_rows = [
                row for row in stratum_rows if row["claim_type"] == claim_type
            ]
            counts = {
                label: sum(1 for row in type_rows if row["label"] == label)
                for label in sorted(LABELS)
            }
            by_type[claim_type] = {
                "total": len(type_rows),
                "counts": counts,
                "fractions": {
                    label: (counts[label] / len(type_rows) if type_rows else None)
                    for label in sorted(LABELS)
                },
            }
        by_stratum[stratum] = {
            "total": len(stratum_rows),
            "by_claim_type": by_type,
        }
    overall_counts = {
        label: sum(1 for row in rows if row["label"] == label)
        for label in sorted(LABELS)
    }
    context_rows = [row for row in rows if row["claim_type"] == "CONTEXT"]
    related_false_context = sum(
        1 for row in context_rows if row["label"] == "RELATED_FALSE"
    )
    cognition_count = sum(1 for row in rows if row["claim_type"] == "COGNITION")
    return {
        "total_claims": len(rows),
        "overall": {
            "counts": overall_counts,
            "fractions": {
                label: (overall_counts[label] / len(rows) if rows else None)
                for label in sorted(LABELS)
            },
        },
        "by_stratum": by_stratum,
        "context_claims": len(context_rows),
        "related_false_context_count": related_false_context,
        "related_false_context_fraction": (
            related_false_context / len(context_rows) if context_rows else None
        ),
        "cognition_claims": cognition_count,
        "cognition_fraction": cognition_count / len(rows) if rows else None,
    }


def run_label() -> None:
    """Label every split claim with the full original context."""

    evidence: dict[str, Any] = {
        "status": "failed",
        "created_at": _now(),
        "step": "phase3_label",
    }
    client: OpenRouterClient | None = None
    try:
        preflight = _assert_runtime_preflight()
        split_evidence = _assert_predecessor(SPLIT_EVIDENCE_PATH)
        if LABEL_EVIDENCE_PATH.exists() and LABELED_CLAIMS_PATH.exists():
            existing = _read_json(LABEL_EVIDENCE_PATH)
            if existing.get("status") == "passed":
                return
        client = _client_from_preflight(preflight)
        claims = _read_rows(CLAIMS_PATH)
        if not claims:
            raise Phase3Error("claims.parquet is empty")
        contexts = {
            str(row["context_id"]): row for row in _read_rows(CONTEXTS_PATH)
        }
        if len(contexts) != PRIMARY_COUNT:
            raise Phase3Error("context lookup is not exactly 300 rows")
        checkpoint = _label_checkpoint()
        labeled_rows: list[dict[str, Any]] = list(checkpoint.values())
        seen = set(checkpoint)
        claims_sorted = sorted(claims, key=lambda row: str(row["claim_id"]))
        guard_written = False
        for claim in claims_sorted:
            claim_id = str(claim["claim_id"])
            if claim_id in seen:
                continue
            context_id = str(claim["context_id"])
            if context_id not in contexts:
                raise Phase3Error(f"claim has no context: {claim_id}")
            label_result, _ = client.call(
                step="label",
                call_id=claim_id,
                role="labeler",
                prompt=LABELER_PROMPT.replace(
                    "{context}", str(contexts[context_id]["text"])
                ).replace("{claim_text}", str(claim["claim_text"])),
                parser=parse_label_response,
                max_tokens=256,
            )
            claim_type = _infer_claim_type(
                label_result["label"],
                str(claim["claim_text"]),
                label_result["justification"],
            )
            if claim_type not in CLAIM_TYPES:
                raise Phase3Error(f"invalid inferred claim type for {claim_id}")
            row = dict(claim)
            row.update(
                {
                    "label": label_result["label"],
                    "justification": label_result["justification"],
                    "claim_type": claim_type,
                }
            )
            labeled_rows.append(row)
            seen.add(claim_id)
            if len(seen) % 25 == 0 or len(seen) == len(claims_sorted):
                _atomic_json(
                    LABEL_CHECKPOINT_PATH,
                    {
                        "status": "running",
                        "created_at": _now(),
                        "completed_claims": len(seen),
                        "rows": labeled_rows,
                    },
                )
            if not guard_written and len(_attempt_costs(client, "label")) >= 50:
                _write_cost_guard(
                    client=client,
                    step="label",
                    planned_calls=len(claims_sorted),
                    phase3_completed_costs=[
                        _completed_step_cost(SPLIT_EVIDENCE_PATH) or Decimal("0")
                    ],
                    recurrence_planned_calls=RECURRENCE_COUNT,
                )
                guard_written = True
        if len(labeled_rows) != len(claims_sorted):
            raise Phase3Error(
                f"label count mismatch: {len(labeled_rows)} != {len(claims_sorted)}"
            )
        labeled_rows.sort(key=lambda row: str(row["claim_id"]))
        _atomic_parquet(LABELED_CLAIMS_PATH, labeled_rows)
        distribution = _distribution(labeled_rows)
        related_fraction = distribution["related_false_context_fraction"]
        gate_pass = related_fraction is not None and related_fraction >= 0.05
        _atomic_json(
            LABEL_DISTRIBUTION_PATH,
            {
                "status": "passed" if gate_pass else "failed",
                "created_at": _now(),
                "step": "phase3_label_distribution",
                **distribution,
            },
        )
        total_cost = _sum_costs(_attempt_costs(client, "label")) or Decimal("0")
        evidence.update(
            {
                "status": "passed" if gate_pass else "failed",
                "models": {
                    "requested": REQUESTED_LABELER_MODEL,
                    "selected": client.selected_models["labeler"],
                    "temperature": TEMPERATURE,
                    "substitution": preflight["models"]["labeler"].get("substitution"),
                },
                "claims_labeled": len(labeled_rows),
                "label_distribution_path": str(LABEL_DISTRIBUTION_PATH),
                "distribution": distribution,
                "related_false_context_gate": {
                    "threshold": 0.05,
                    "observed": related_fraction,
                    "passed": gate_pass,
                },
                "unverifiable_note": (
                    "A large UNVERIFIABLE fraction is expected for forward-looking "
                    "next-token and cognition claims and is reported, not treated "
                    "as a failure."
                ),
                "cost": {
                    "total": _decimal_string(total_cost),
                    "attempt_count": len(_attempt_costs(client, "label")),
                    "billing_basis": (
                        "OpenRouter response usage.cost when present, otherwise the "
                        "selected model's listed per-token pricing multiplied by "
                        "response token usage"
                    ),
                },
                "output": str(LABELED_CLAIMS_PATH),
                "predecessor_split_status": split_evidence.get("status"),
            }
        )
        if not gate_pass:
            evidence["examples_for_gate_failure"] = [
                {
                    "context_id": row["context_id"],
                    "claim_id": row["claim_id"],
                    "claim_text": row["claim_text"],
                    "label": row["label"],
                    "justification": row["justification"],
                }
                for row in labeled_rows[:10]
            ]
        _atomic_json(LABEL_EVIDENCE_PATH, evidence)
        if not gate_pass:
            raise Phase3Error(
                f"RELATED_FALSE context fraction below 5 percent: {related_fraction}"
            )
        if not guard_written and len(_attempt_costs(client, "label")) >= 50:
            _write_cost_guard(
                client=client,
                step="label",
                planned_calls=len(claims_sorted),
                phase3_completed_costs=[
                    _completed_step_cost(SPLIT_EVIDENCE_PATH) or Decimal("0"),
                    total_cost,
                ],
                recurrence_planned_calls=RECURRENCE_COUNT,
            )
    except Exception as exc:
        evidence["error"] = _error_text(exc)
        if client is not None:
            evidence["cost"] = {
                "total": _decimal_string(
                    _sum_costs(_attempt_costs(client, "label"))
                ),
                "billing_basis": (
                    "OpenRouter response usage.cost when present, otherwise the "
                    "selected model's listed per-token pricing multiplied by "
                    "response token usage"
                ),
            }
        _atomic_json(LABEL_EVIDENCE_PATH, evidence)
        raise


def _recurrence_prompt(
    context_text: str,
    primary_claims: list[dict[str, Any]],
    sibling_rows: list[dict[str, Any]],
    extra_primary_rows: list[dict[str, Any]],
) -> str:
    primary_block = "\n".join(
        f"{row['claim_id']}\t{row['claim_text']}" for row in primary_claims
    )
    sibling_block = "\n".join(
        f"OFFSET {row['position_offset']}:\n{row['text']}"
        for row in sorted(sibling_rows, key=lambda row: int(row["position_offset"]))
    )
    extra_block = "\n".join(
        f"SAMPLE {row['sample_idx']}:\n{row['text']}"
        for row in sorted(extra_primary_rows, key=lambda row: int(row["sample_idx"]))
    )
    return f"""You are checking recurrence of claims in descriptions generated from the same language model state.
For every PRIMARY CLAIM below, count how many of the nine sibling-position explanations assert the same claim and how many of the three extra primary-sample explanations assert the same claim.
Return exactly a JSON object with key "claims". Each item must contain the original claim_id, recurrence_positions as an integer from 0 through 9, and recurrence_samples as an integer from 0 through 3. Do not omit or add claim IDs.
CONTEXT:
{context_text}
PRIMARY CLAIMS:
{primary_block}
SIBLING-POSITION EXPLANATIONS:
{sibling_block}
EXTRA PRIMARY-SAMPLE EXPLANATIONS:
{extra_block}"""


def _recurrence_checkpoint() -> dict[str, dict[str, Any]]:
    if not RECURRENCE_CHECKPOINT_PATH.exists():
        return {}
    payload = _read_json(RECURRENCE_CHECKPOINT_PATH)
    values = payload.get("values", {})
    if not isinstance(values, dict):
        raise Phase3Error("recurrence checkpoint values are not an object")
    return values


def run_recurrence() -> None:
    """Run one recurrence call per context and join its counts."""

    evidence: dict[str, Any] = {
        "status": "failed",
        "created_at": _now(),
        "step": "phase3_recurrence",
    }
    client: OpenRouterClient | None = None
    try:
        preflight = _assert_runtime_preflight()
        _assert_predecessor(LABEL_EVIDENCE_PATH)
        if RECURRENCE_EVIDENCE_PATH.exists() and LABELED_CLAIMS_PATH.exists():
            existing = _read_json(RECURRENCE_EVIDENCE_PATH)
            if existing.get("status") == "passed":
                return
        client = _client_from_preflight(preflight)
        labeled_rows = _read_rows(LABELED_CLAIMS_PATH)
        contexts = _read_rows(CONTEXTS_PATH)
        explanations = _read_rows(EXPLANATIONS_PATH)
        context_by_id = {str(row["context_id"]): row for row in contexts}
        if len(context_by_id) != PRIMARY_COUNT:
            raise Phase3Error("recurrence context lookup is not exactly 300 rows")
        claims_by_context: dict[str, list[dict[str, Any]]] = {}
        for row in labeled_rows:
            claims_by_context.setdefault(str(row["context_id"]), []).append(row)
        explanation_by_context: dict[str, list[dict[str, Any]]] = {}
        for row in explanations:
            explanation_by_context.setdefault(str(row["context_id"]), []).append(row)
        checkpoint = _recurrence_checkpoint()
        recurrence_by_claim: dict[str, dict[str, Any]] = {}
        for value in checkpoint.values():
            if not isinstance(value, dict) or not isinstance(value.get("claim_id"), str):
                raise Phase3Error("recurrence checkpoint item is invalid")
            recurrence_by_claim[value["claim_id"]] = value
        guard_written = False
        for context_id in sorted(context_by_id):
            primary_claims = sorted(
                claims_by_context.get(context_id, []),
                key=lambda row: str(row["claim_id"]),
            )
            context_explanations = explanation_by_context.get(context_id, [])
            primary_rows = [
                row
                for row in context_explanations
                if int(row["position_offset"]) == 0
            ]
            sibling_rows = [
                row
                for row in context_explanations
                if 1 <= int(row["position_offset"]) <= 9
                and int(row["sample_idx"]) == 0
            ]
            extra_primary_rows = [
                row
                for row in context_explanations
                if int(row["position_offset"]) == 0
                and 1 <= int(row["sample_idx"]) <= 3
            ]
            if (
                len(primary_claims) == 0
                or len([row for row in primary_rows if int(row["sample_idx"]) == 0]) != 1
                or len(sibling_rows) != 9
                or len(extra_primary_rows) != 3
            ):
                raise Phase3Error(
                    f"recurrence inputs incomplete for {context_id}: "
                    f"claims={len(primary_claims)}, primary={len(primary_rows)}, "
                    f"siblings={len(sibling_rows)}, extras={len(extra_primary_rows)}"
                )
            if all(row["claim_id"] in recurrence_by_claim for row in primary_claims):
                continue
            parsed, _ = client.call(
                step="recurrence",
                call_id=context_id,
                role="labeler",
                prompt=_recurrence_prompt(
                    str(context_by_id[context_id]["text"]),
                    primary_claims,
                    sibling_rows,
                    extra_primary_rows,
                ),
                parser=parse_recurrence_response,
                max_tokens=1536,
            )
            expected_ids = {str(row["claim_id"]) for row in primary_claims}
            returned_ids = {str(item["claim_id"]) for item in parsed}
            if returned_ids != expected_ids:
                raise Phase3Error(
                    f"recurrence claim IDs mismatch for {context_id}: "
                    f"missing={sorted(expected_ids - returned_ids)}, "
                    f"extra={sorted(returned_ids - expected_ids)}"
                )
            for item in parsed:
                positions = int(item["recurrence_positions"])
                samples = int(item["recurrence_samples"])
                assert 0 <= positions <= 9
                assert 0 <= samples <= 3
                if not 0 <= positions <= 9 or not 0 <= samples <= 3:
                    raise Phase3Error(
                        f"recurrence count out of bounds for {item['claim_id']}"
                    )
                recurrence_by_claim[str(item["claim_id"])] = {
                    "claim_id": str(item["claim_id"]),
                    "recurrence_positions": positions,
                    "recurrence_samples": samples,
                }
            _atomic_json(
                RECURRENCE_CHECKPOINT_PATH,
                {
                    "status": "running",
                    "created_at": _now(),
                    "completed_contexts": sum(
                        1
                        for cid in context_by_id
                        if all(
                            row["claim_id"] in recurrence_by_claim
                            for row in claims_by_context.get(cid, [])
                        )
                    ),
                    "values": {
                        item["claim_id"]: item
                        for item in recurrence_by_claim.values()
                    },
                },
            )
            if not guard_written and len(_attempt_costs(client, "recurrence")) >= 50:
                _write_cost_guard(
                    client=client,
                    step="recurrence",
                    planned_calls=RECURRENCE_COUNT,
                    phase3_completed_costs=[
                        _completed_step_cost(SPLIT_EVIDENCE_PATH) or Decimal("0"),
                        _completed_step_cost(LABEL_EVIDENCE_PATH) or Decimal("0"),
                    ],
                    recurrence_planned_calls=RECURRENCE_COUNT,
                )
                guard_written = True

        if len(recurrence_by_claim) != len(labeled_rows):
            raise Phase3Error(
                f"recurrence coverage mismatch: {len(recurrence_by_claim)} "
                f"!= {len(labeled_rows)}"
            )
        joined_rows: list[dict[str, Any]] = []
        for row in labeled_rows:
            joined = dict(row)
            recurrence = recurrence_by_claim[str(row["claim_id"])]
            joined["recurrence_positions"] = int(recurrence["recurrence_positions"])
            joined["recurrence_samples"] = int(recurrence["recurrence_samples"])
            assert 0 <= joined["recurrence_positions"] <= 9
            assert 0 <= joined["recurrence_samples"] <= 3
            joined_rows.append(joined)
        _atomic_parquet(LABELED_CLAIMS_PATH, joined_rows)
        rng = random.Random(0)
        spot_rows = sorted(joined_rows, key=lambda row: str(row["claim_id"]))
        sample = rng.sample(spot_rows, min(10, len(spot_rows)))
        spot_checks = [
            {
                "context_id": row["context_id"],
                "claim_id": row["claim_id"],
                "claim_text": row["claim_text"],
                "recurrence_positions": row["recurrence_positions"],
                "recurrence_samples": row["recurrence_samples"],
            }
            for row in sample
        ]
        _atomic_json(
            RECURRENCE_SPOT_CHECK_PATH,
            {
                "status": "passed",
                "created_at": _now(),
                "seed": 0,
                "count": len(spot_checks),
                "examples": spot_checks,
            },
        )
        total_cost = _sum_costs(_attempt_costs(client, "recurrence")) or Decimal("0")
        evidence.update(
            {
                "status": "passed",
                "models": {
                    "requested": REQUESTED_LABELER_MODEL,
                    "selected": client.selected_models["labeler"],
                    "temperature": TEMPERATURE,
                    "substitution": preflight["models"]["labeler"].get("substitution"),
                },
                "contexts_processed": PRIMARY_COUNT,
                "claims_joined": len(joined_rows),
                "count_bounds": {
                    "recurrence_positions": [0, 9],
                    "recurrence_samples": [0, 3],
                    "observed_min_positions": min(
                        row["recurrence_positions"] for row in joined_rows
                    ),
                    "observed_max_positions": max(
                        row["recurrence_positions"] for row in joined_rows
                    ),
                    "observed_min_samples": min(
                        row["recurrence_samples"] for row in joined_rows
                    ),
                    "observed_max_samples": max(
                        row["recurrence_samples"] for row in joined_rows
                    ),
                    "all_in_bounds": all(
                        0 <= row["recurrence_positions"] <= 9
                        and 0 <= row["recurrence_samples"] <= 3
                        for row in joined_rows
                    ),
                },
                "spot_check_path": str(RECURRENCE_SPOT_CHECK_PATH),
                "cost": {
                    "total": _decimal_string(total_cost),
                    "attempt_count": len(_attempt_costs(client, "recurrence")),
                    "billing_basis": (
                        "OpenRouter response usage.cost when present, otherwise the "
                        "selected model's listed per-token pricing multiplied by "
                        "response token usage"
                    ),
                },
                "output": str(LABELED_CLAIMS_PATH),
            }
        )
        _atomic_json(RECURRENCE_EVIDENCE_PATH, evidence)
        if not guard_written and len(_attempt_costs(client, "recurrence")) >= 50:
            _write_cost_guard(
                client=client,
                step="recurrence",
                planned_calls=RECURRENCE_COUNT,
                phase3_completed_costs=[
                    _completed_step_cost(SPLIT_EVIDENCE_PATH) or Decimal("0"),
                    _completed_step_cost(LABEL_EVIDENCE_PATH) or Decimal("0"),
                    total_cost,
                ],
                recurrence_planned_calls=RECURRENCE_COUNT,
            )
    except Exception as exc:
        evidence["error"] = _error_text(exc)
        if client is not None:
            evidence["cost"] = {
                "total": _decimal_string(
                    _sum_costs(_attempt_costs(client, "recurrence"))
                ),
                "billing_basis": (
                    "OpenRouter response usage.cost when present, otherwise the "
                    "selected model's listed per-token pricing multiplied by "
                    "response token usage"
                ),
            }
        _atomic_json(RECURRENCE_EVIDENCE_PATH, evidence)
        raise


def run_human_sample() -> None:
    """Write the blind 50-claim sample and its hidden answer key."""

    evidence: dict[str, Any] = {
        "status": "failed",
        "created_at": _now(),
        "step": "phase3_human_sample",
    }
    try:
        _assert_runtime_preflight()
        _assert_predecessor(SPLIT_EVIDENCE_PATH)
        _assert_predecessor(LABEL_EVIDENCE_PATH)
        _assert_predecessor(RECURRENCE_EVIDENCE_PATH)
        rows = _read_rows(LABELED_CLAIMS_PATH)
        contexts = {str(row["context_id"]): row for row in _read_rows(CONTEXTS_PATH)}
        if len(rows) < 50:
            raise Phase3Error(f"fewer than 50 labeled claims: {len(rows)}")
        ordered = sorted(rows, key=lambda row: str(row["claim_id"]))
        sample = random.Random(0).sample(ordered, 50)
        sample.sort(key=lambda row: str(row["claim_id"]))
        parts = [
            "# Phase 3 blind human-label sample",
            "",
            "Seed: 0. Complete the HUMAN LABEL and HUMAN NOTES fields for all 50 entries before opening the answer key.",
            "",
        ]
        for index, row in enumerate(sample, start=1):
            context = contexts[str(row["context_id"])]
            parts.extend(
                [
                    f"## Sample {index}",
                    "",
                    f"- context_id: {row['context_id']}",
                    f"- stratum: {row['stratum']}",
                    f"- claim_id: {row['claim_id']}",
                    "",
                    "### ORIGINAL TEXT",
                    "",
                    str(context["text"]),
                    "",
                    "### CLAIM",
                    "",
                    str(row["claim_text"]),
                    "",
                    "### HUMAN LABEL",
                    "",
                    "Write TRUE, RELATED_FALSE, UNRELATED_FALSE, or UNVERIFIABLE.",
                    "",
                    "### HUMAN NOTES",
                    "",
                    "Optional.",
                    "",
                ]
            )
        parts.extend(
            [
                "<details>",
                "<summary>Answer key, open only after the blind pass</summary>",
                "",
                "The answer key below is generated from the Phase 3 label output.",
                "",
            ]
        )
        for index, row in enumerate(sample, start=1):
            parts.extend(
                [
                    f"{index}. {row['claim_id']}: {row['label']} "
                    f"({row['claim_type']}) - {row['justification']}",
                    "",
                ]
            )
        parts.extend(["</details>", ""])
        _atomic_text(HUMAN_SAMPLE_PATH, "\n".join(parts))
        evidence.update(
            {
                "status": "passed",
                "seed": 0,
                "count": len(sample),
                "claim_ids": [row["claim_id"] for row in sample],
                "path": str(HUMAN_SAMPLE_PATH),
                "answer_key_location": "bottom details block",
                "phase4_started": False,
            }
        )
        _atomic_json(HUMAN_SAMPLE_EVIDENCE_PATH, evidence)
    except Exception as exc:
        evidence["error"] = _error_text(exc)
        _atomic_json(HUMAN_SAMPLE_EVIDENCE_PATH, evidence)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "step",
        choices=("startup", "preflight", "split", "label", "recurrence", "human-sample"),
    )
    args = parser.parse_args()
    if args.step == "startup":
        run_startup()
    elif args.step == "preflight":
        run_preflight()
    elif args.step == "split":
        run_split()
    elif args.step == "label":
        run_label()
    elif args.step == "recurrence":
        run_recurrence()
    elif args.step == "human-sample":
        run_human_sample()


if __name__ == "__main__":
    main()
