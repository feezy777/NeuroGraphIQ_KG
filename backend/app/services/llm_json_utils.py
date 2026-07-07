"""Pure helpers for LLM JSON parsing and normalization (no DB / no HTTP)."""

from __future__ import annotations

import json
import re
from typing import Any

RAW_PREVIEW_MAX_CHARS = 2000

_SCHEMA_HINT_KEYS = frozenset({
    "projections",
    "projection",
    "connections",
    "edges",
    "relations",
    "links",
    "no_connections",
    "no_connection",
    "no_edges",
    "no_relations",
    "projection_functions",
    "field_updates",
    "circuit_functions",
    "circuits",
    "circuit_steps",
    "functions",
    "verification",
    "inferred_circuits",
    "bundle_consistency",
    "cross_validation_results",
})


class LlmJsonParseError(json.JSONDecodeError):
    """Raised when a model response cannot be parsed into JSON.

    Subclasses ``json.JSONDecodeError`` (itself a ``ValueError``) so existing
    callers that catch either still work. Carries a bounded ``preview`` of the
    raw text and an ``error_type`` for diagnostics.
    """

    def __init__(
        self,
        message: str,
        *,
        preview: str = "",
        error_type: str = "json_decode_error",
        doc: str = "",
        pos: int = 0,
    ):
        super().__init__(message, doc or " ", pos)
        self.preview = preview
        self.error_type = error_type


def raw_response_preview(raw: Any, *, limit: int = RAW_PREVIEW_MAX_CHARS) -> str:
    """Bounded, key-safe preview of a raw model response for diagnostics."""
    if raw is None:
        return ""
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, default=str)
    text = text.strip()
    if len(text) > limit:
        return text[:limit] + f"…[truncated {len(text) - limit} chars]"
    return text


def _clean_input_text(text: str) -> str:
    """Strip BOM and other leading control chars that break json.loads."""
    if not text:
        return ""
    cleaned = text.lstrip("\ufeff\u200b\u200c\u200d\ufeff")
    # Drop other C0 controls except tab/newline/carriage-return.
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cleaned)
    return cleaned.strip()


def _strip_code_fences(text: str) -> str:
    """Return the inner body of the first markdown code fence, else the text."""
    fence = re.search(r"```(?:json|JSON)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    # Unterminated fence (e.g. truncated): drop the opening fence line.
    if text.lstrip().startswith("```"):
        body = text.lstrip()[3:]
        if body[:4].lower() == "json":
            body = body[4:]
        return body.strip().strip("`").strip()
    return text


def _repair_json_text(text: str) -> str:
    """Low-cost deterministic repairs. No second LLM call, no aggressive rewrites."""
    repaired = text
    # Normalize a few common full-width punctuation marks that break JSON.
    repaired = (
        repaired.replace("：", ":")
        .replace("，", ",")
        .replace("“", '"')
        .replace("”", '"')
        .replace("【", "[")
        .replace("】", "]")
    )
    # Remove trailing commas before } or ].
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    return repaired


def _balanced_span(text: str, open_ch: str, close_ch: str, *, start: int = 0) -> str | None:
    """Return the first balanced ``open_ch..close_ch`` span from ``start``, ignoring strings."""
    pos = text.find(open_ch, start)
    if pos == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(pos, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[pos : i + 1]
    return None


def _close_truncated(text: str, open_ch: str, close_ch: str) -> str | None:
    """Salvage a truncated object/array by trimming to the last complete element
    and closing open structures. Returns a parseable string or None."""
    start = text.find(open_ch)
    if start == -1:
        return None
    body = text[start:]
    # Trim to the last position that closes a top-level element, then balance.
    last_complete = max(body.rfind("}"), body.rfind("]"))
    if last_complete == -1:
        return None
    candidate = body[: last_complete + 1]
    # Drop a dangling trailing comma if present.
    candidate = re.sub(r",\s*$", "", candidate)
    # Count unbalanced openers (ignoring strings) and append closers.
    depth_curly = 0
    depth_square = 0
    in_str = False
    escape = False
    for ch in candidate:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth_curly += 1
        elif ch == "}":
            depth_curly -= 1
        elif ch == "[":
            depth_square += 1
        elif ch == "]":
            depth_square -= 1
    if in_str or depth_curly < 0 or depth_square < 0:
        return None
    # Typical truncated shape is {"projections": [ {..}, {..  with the array
    # nested inside the object, so close the inner array first (LIFO), then the
    # outer object.
    repaired = candidate + ("]" * depth_square) + ("}" * depth_curly)
    # For connection extraction format, if the object is missing no_connections
    # or warnings keys, inject them with empty values so the schema passes.
    if open_ch == "{" and depth_curly == 0 and depth_square == 0:
        try:
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                parts = []
                if "projections" in parsed and "no_connections" not in parsed:
                    parts.append('"no_connections": []')
                if "warnings" not in parsed:
                    parts.append('"warnings": []')
                if parts:
                    # Insert before the closing brace
                    repaired = repaired.rstrip("}").rstrip() + "," + ",".join(parts) + "}"
        except json.JSONDecodeError:
            pass
    return repaired


def _score_parsed_value(value: Any) -> int:
    if isinstance(value, dict):
        score = 0
        for key in value:
            if key in _SCHEMA_HINT_KEYS:
                score += 10
        if "projections" in value or "no_connections" in value or "circuits" in value:
            score += 25
        if "projection_functions" in value:
            score += 25
        if value:
            score += min(len(value), 5)  # more keys = richer object = higher score
        return score
    if isinstance(value, list) and value:
        if isinstance(value[0], dict) and any(
            k in value[0]
            for k in ("pair_id", "source_region_candidate_id", "projection_id", "projection_type")
        ):
            return 8
        return 2
    return 0


def _iter_balanced_spans(text: str) -> list[str]:
    spans: list[str] = []
    seen: set[str] = set()
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        idx = 0
        while idx < len(text):
            span = _balanced_span(text, open_ch, close_ch, start=idx)
            if span is None:
                break
            if span not in seen:
                seen.add(span)
                spans.append(span)
            next_idx = text.find(open_ch, idx + 1)
            if next_idx == -1:
                break
            idx = next_idx
    return spans


def _try_load_json_candidates(
    candidates: list[str],
    *,
    primary_text: str | None = None,
) -> tuple[Any | None, str | None]:
    last_err: str | None = None
    scored: list[tuple[int, int, Any]] = []  # (score, index, parsed)

    for idx, cand in enumerate(candidates):
        if not cand or not cand.strip():
            continue
        for attempt in (cand, _repair_json_text(cand)):
            try:
                parsed = json.loads(attempt)
                score = _score_parsed_value(parsed)
                # Tiebreaker: prefer candidates that appear earlier in the list
                # (raw/fenced text comes before extracted spans).
                tiebreaker = max(0, 10000 - idx * 100)
                if primary_text and attempt == primary_text.strip():
                    tiebreaker += 5000
                scored.append((score, tiebreaker, parsed))
                break
            except json.JSONDecodeError as exc:
                last_err = str(exc)
    if scored:
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return scored[0][2], None
    return None, last_err


def extract_json_object_from_text(text: str) -> tuple[Any, str | None]:
    """Extract a JSON value from arbitrary text.

    Strategy: fenced block → all balanced spans (prefer schema-like objects) →
    truncation repair.
    Returns ``(parsed, None)`` on success or ``(None, error_message)`` on failure.
    """
    text = _clean_input_text(text)
    if not text:
        return None, "empty text"

    candidates: list[str] = []
    fenced = _strip_code_fences(text)
    candidates.append(fenced)
    candidates.extend(_iter_balanced_spans(fenced))
    candidates.extend(_iter_balanced_spans(text))

    parsed, err = _try_load_json_candidates(candidates, primary_text=fenced)
    if parsed is not None:
        return parsed, None

    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        salvaged = _close_truncated(fenced, open_ch, close_ch)
        if salvaged:
            parsed, err = _try_load_json_candidates(
                [salvaged, _repair_json_text(salvaged)],
                primary_text=salvaged,
            )
            if parsed is not None:
                return parsed, None

    return None, err or "no JSON object/array found"


def normalize_connection_completion_payload(parsed: Any) -> dict[str, Any]:
    """Normalize parsed JSON to canonical connection extraction object shape."""
    if isinstance(parsed, list):
        return {"projections": parsed, "no_connections": [], "warnings": []}
    if isinstance(parsed, dict) and isinstance(parsed.get("_array"), list):
        return {"projections": parsed["_array"], "no_connections": [], "warnings": []}
    if not isinstance(parsed, dict):
        raise LlmJsonParseError(
            "parsed JSON is not an object or array",
            error_type="schema_error",
        )

    projections: list[Any] | None = None
    for key in ("projections", "projection", "connections", "edges", "relations", "links"):
        val = parsed.get(key)
        if isinstance(val, list):
            projections = val
            break

    no_connections: list[Any] = []
    for key in ("no_connections", "no_connection", "no_edges", "no_relations"):
        val = parsed.get(key)
        if isinstance(val, list):
            no_connections = val
            break

    warnings = parsed.get("warnings")
    return {
        "projections": projections if projections is not None else [],
        "no_connections": no_connections,
        "warnings": warnings if isinstance(warnings, list) else [],
    }


def parse_connection_completion_response(raw: Any) -> dict[str, Any]:
    """Parse model output for same-granularity connection / projection extraction."""
    parsed = parse_llm_json_response(raw)
    return normalize_connection_completion_payload(parsed)


def parse_llm_json_response(raw: Any) -> dict[str, Any]:
    """Parse a model response into a JSON object.

    Accepts dict, list, provider message objects, or strings (plain JSON,
    fenced JSON, or JSON embedded in explanatory text). Raises
    ``LlmJsonParseError`` (a ValueError subclass) with a bounded preview when
    the content cannot be parsed.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {"_array": raw}

    # Provider message-like object: {"content": "..."} or {"message": {...}}.
    if hasattr(raw, "get") and not isinstance(raw, str):
        for key in ("content", "text", "raw_text"):
            inner = raw.get(key)
            if isinstance(inner, str):
                raw = inner
                break

    if not isinstance(raw, str):
        raw = str(raw)

    parsed, err = extract_json_object_from_text(raw)
    if parsed is None:
        raise LlmJsonParseError(
            f"could not parse JSON from model response: {err}",
            preview=raw_response_preview(raw),
            error_type="json_decode_error",
        )
    if isinstance(parsed, list):
        return {"_array": parsed}
    if not isinstance(parsed, dict):
        raise LlmJsonParseError(
            "parsed JSON is not an object or array",
            preview=raw_response_preview(raw),
            error_type="schema_error",
        )
    return parsed


def normalize_region_field_completion_output(parsed: dict[str, Any]) -> dict[str, Any]:
    """Map provider JSON to internal region_field_completion schema."""
    confidence = parsed.get("confidence")
    if confidence is not None:
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = None

    aliases = parsed.get("aliases")
    if aliases is None:
        aliases = parsed.get("suggested_aliases")
    if not isinstance(aliases, list):
        aliases = []

    return {
        "cn_name_suggestion": parsed.get("cn_name_suggestion") or parsed.get("suggested_cn_name"),
        "en_name_suggestion": parsed.get("en_name_suggestion") or parsed.get("suggested_en_name"),
        "aliases": aliases,
        "description": parsed.get("description") or parsed.get("suggested_description"),
        "confidence": confidence,
        "evidence_text": parsed.get("evidence_text") or parsed.get("evidence_summary"),
        "uncertainty_reason": parsed.get("uncertainty_reason"),
        "region_base_name": parsed.get("region_base_name") or parsed.get("suggested_region_base_name"),
        "laterality_suggestion": parsed.get("laterality_suggestion") or parsed.get("suggested_laterality"),
    }


def normalized_to_legacy_structured(normalized: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    """Convert normalized output to legacy LlmSuggestion shape for candidate_llm_extractions."""
    return {
        "candidate_id": candidate_id,
        "suggested_cn_name": normalized.get("cn_name_suggestion"),
        "suggested_en_name": normalized.get("en_name_suggestion"),
        "suggested_aliases": normalized.get("aliases") or [],
        "suggested_description": normalized.get("description"),
        "suggested_region_base_name": normalized.get("region_base_name"),
        "suggested_laterality": normalized.get("laterality_suggestion"),
        "confidence": normalized.get("confidence"),
        "evidence_summary": normalized.get("evidence_text"),
        "risk_flags": [],
        "needs_human_review": True,
    }
