from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from urllib import error, request

from ..common.models import utc_now_iso
from ..config.runtime_config import clamp_deepseek_max_tokens

# ---------------------------------------------------------------------------
# review_note merge: nested validation_center.{mode}
# ---------------------------------------------------------------------------


def merge_validation_center_into_review_note(existing_note: str, mode: str, run_payload: Dict[str, Any]) -> str:
    base: Dict[str, Any] = {}
    if existing_note:
        try:
            base = json.loads(existing_note)
            if not isinstance(base, dict):
                base = {"_legacy_text": existing_note}
        except json.JSONDecodeError:
            base = {"_legacy_text": existing_note}
    vc = base.get("validation_center")
    if not isinstance(vc, dict):
        vc = {}
    entry = dict(run_payload)
    entry["at"] = utc_now_iso()
    vc[mode] = entry
    base["validation_center"] = vc
    return json.dumps(base, ensure_ascii=False)


# ---------------------------------------------------------------------------
# OpenAI-compatible chat (DeepSeek / Moonshot)
# ---------------------------------------------------------------------------


def _parse_chat_content(body: str) -> str:
    payload = json.loads(body)
    choices = payload.get("choices", [])
    if not choices:
        return ""
    return (choices[0].get("message", {}) or {}).get("content", "") or ""


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
    return None


def _openai_base_url(llm_cfg: Dict[str, Any], *, label: str) -> str:
    """空 base_url 时按厂商默认，避免误用 DeepSeek 域名导致「Kimi 未扣费」实为请求发错端点。"""
    raw = str(llm_cfg.get("base_url") or "").strip()
    if raw:
        return raw
    return "https://api.moonshot.cn" if (label or "").lower() == "kimi" else "https://api.deepseek.com"


def _openai_force_json(llm_cfg: Dict[str, Any], *, label: str) -> bool:
    """Moonshot(Kimi) 兼容接口不支持 response_format=json_object，传了常返回 400，请求失败则不会计费。"""
    if (label or "").lower() == "kimi":
        return False
    return bool(llm_cfg.get("force_json_output", True))


def openai_compatible_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 2048,
    force_json: bool = True,
    timeout_sec: int = 120,
    retries: int = 2,
    backoff_sec: float = 1.2,
) -> str:
    bu = (base_url or "https://api.deepseek.com").rstrip("/")
    if bu.endswith("/v1"):
        bu = bu[:-3].rstrip("/")
    url = bu + "/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }
    mt = clamp_deepseek_max_tokens(max_tokens)
    if mt > 0:
        payload["max_tokens"] = mt
    if force_json:
        payload["response_format"] = {"type": "json_object"}
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    last_exc: Optional[Exception] = None
    body = ""
    for attempt in range(max(0, retries) + 1):
        try:
            with request.urlopen(req, timeout=max(10, int(timeout_sec))) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
            last_exc = None
            break
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            last_exc = RuntimeError(f"http_{exc.code}:{detail[:400]}")
            if exc.code in (400, 401, 403, 404):
                break
        except Exception as exc:
            last_exc = RuntimeError(f"request_failed:{exc}")
        if attempt < retries:
            time.sleep(backoff_sec * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    return _parse_chat_content(body)


REGION_VALIDATE_SYSTEM = (
    "你是神经解剖与知识图谱助手。用户给出原文片段与已抽取的脑区候选字段，"
    "请判断中英名称与别名是否与原文一致、命名是否合理。只输出一个 JSON 对象，不要其它文字。"
)

REGION_VALIDATE_USER_TEMPLATE = """请校验下列脑区候选是否与 source_text 一致、命名是否可接受。

candidate_id: {candidate_id}
source_text:
{source_text}

当前字段:
- en_name_candidate: {en}
- cn_name_candidate: {cn}
- alias_candidates (JSON): {aliases}

请输出 JSON，键为:
- verdict: 字符串，取 pass / warn / fail 之一
- confidence: 0 到 1 的小数
- issues: 字符串数组（问题说明，中文）
- suggested_en: 字符串，若无修改建议则空字符串
- suggested_cn: 字符串，若无修改建议则空字符串
- rationale: 简短中文理由
"""


def build_region_validation_user_message(row: Dict[str, Any]) -> str:
    aliases = row.get("alias_candidates")
    if isinstance(aliases, list):
        aliases_str = json.dumps(aliases, ensure_ascii=False)
    else:
        aliases_str = json.dumps(aliases or [], ensure_ascii=False)
    return REGION_VALIDATE_USER_TEMPLATE.format(
        candidate_id=str(row.get("id", "")),
        source_text=str(row.get("source_text", "") or ""),
        en=str(row.get("en_name_candidate", "") or ""),
        cn=str(row.get("cn_name_candidate", "") or ""),
        aliases=aliases_str,
    )


def run_local_region_validation(engine: Any, row: Dict[str, Any]) -> Dict[str, Any]:
    if not engine or not getattr(engine, "enabled", False):
        return {
            "ok": True,
            "skipped": True,
            "reason": "ontology_rules_disabled",
            "evaluation": {},
        }
    ev = engine.evaluate_region(row)
    issues = ev.get("issues") or []
    hard = any((i.get("severity") == "hard") for i in issues if isinstance(i, dict))
    verdict = "pass"
    if issues:
        verdict = "fail" if hard else "warn"
    return {
        "ok": True,
        "skipped": False,
        "verdict": verdict,
        "evaluation": ev,
        "rules_version": getattr(engine, "rules_version", ""),
    }


def run_llm_region_validation(
    *,
    row: Dict[str, Any],
    llm_cfg: Dict[str, Any],
    label: str,
) -> Dict[str, Any]:
    if not llm_cfg.get("api_key"):
        return {"ok": False, "error": f"{label}_api_key_missing"}
    user_msg = build_region_validation_user_message(row)
    content = openai_compatible_chat(
        base_url=_openai_base_url(llm_cfg, label=label),
        api_key=str(llm_cfg.get("api_key", "")),
        model=str(llm_cfg.get("model", "deepseek-chat")),
        messages=[
            {"role": "system", "content": REGION_VALIDATE_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=float(llm_cfg.get("temperature", 0.2)),
        max_tokens=int(llm_cfg.get("max_tokens", 2048) or 2048),
        force_json=_openai_force_json(llm_cfg, label=label),
        timeout_sec=int(llm_cfg.get("request_timeout_sec", 120)),
        retries=int(llm_cfg.get("request_retries", 2)),
        backoff_sec=float(llm_cfg.get("retry_backoff_sec", 1.2)),
    )
    parsed = _extract_json_object(content)
    if not parsed:
        return {
            "ok": False,
            "error": f"{label}_json_parse_failed",
            "raw_content_preview": (content or "")[:500],
        }
    return {"ok": True, "parsed": parsed, "raw_content_preview": (content or "")[:500]}


def consensus_verdict(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> str:
    if not a or not b:
        return "unknown"
    va = (a.get("verdict") or "").strip().lower()
    vb = (b.get("verdict") or "").strip().lower()
    if va and vb and va == vb:
        return "agree"
    return "disagree"


# ---------------------------------------------------------------------------
# 流水线：完整性检查 + LLM 纠偏/补全（不写库，由上层 apply）
# ---------------------------------------------------------------------------

_PATCH_KEYS = {
    "source_text",
    "en_name_candidate",
    "cn_name_candidate",
    "alias_candidates",
    "laterality_candidate",
    "granularity_candidate",
    "parent_region_candidate",
    "region_category_candidate",
    "ontology_source_candidate",
    "confidence",
}


def check_region_candidate_completeness(row: Dict[str, Any]) -> Dict[str, Any]:
    missing: List[str] = []
    if not str(row.get("source_text", "") or "").strip():
        missing.append("source_text")
    if not str(row.get("en_name_candidate", "") or "").strip():
        missing.append("en_name_candidate")
    if not str(row.get("cn_name_candidate", "") or "").strip():
        missing.append("cn_name_candidate")
    g = str(row.get("granularity_candidate", "") or "").strip().lower()
    if not g or g == "unknown":
        missing.append("granularity_candidate")
    return {"ok": len(missing) == 0, "missing_fields": missing}


def needs_llm_fix_after_checks(local_out: Dict[str, Any], comp: Dict[str, Any]) -> bool:
    """仅规则/完整性启发式：不完整或本地 verdict 为 warn/fail 时认为「需要纠偏」。
    本地 pass 且字段齐时为 False；本体引擎关闭 (skipped) 且字段齐时也为 False。
    是否在流水线中实际调用 LLM 由 WorkbenchService 根据 llm_mode（deepseek/multi 则始终调用）决定。"""
    if not comp.get("ok"):
        return True
    if local_out.get("skipped"):
        return False
    v = str(local_out.get("verdict") or "").strip().lower()
    return v in ("fail", "warn")


def normalize_llm_fix_patch(parsed: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not isinstance(parsed, dict):
        return out
    for k in _PATCH_KEYS:
        if k not in parsed:
            continue
        val = parsed[k]
        if k == "alias_candidates":
            if isinstance(val, list):
                out[k] = val
            elif isinstance(val, str):
                try:
                    out[k] = json.loads(val)
                except json.JSONDecodeError:
                    out[k] = []
            continue
        if k == "confidence":
            try:
                out[k] = float(val)
            except (TypeError, ValueError):
                pass
            continue
        if val is not None:
            out[k] = val
    return out


REGION_FIX_SYSTEM = (
    "你是神经解剖与知识图谱助手。根据原文与「本地规则问题/缺失字段」提示，对候选字段做纠偏与补全。"
    "只输出一个 JSON 对象；键名必须包含："
    "source_text, en_name_candidate, cn_name_candidate, alias_candidates (字符串数组), "
    "laterality_candidate, granularity_candidate, parent_region_candidate, region_category_candidate, "
    "ontology_source_candidate, confidence (0-1 数字), rationale (中文简短说明修改原因)。"
    "无问题的字段可原样抄回当前值。"
)


def build_region_fix_user_payload(row: Dict[str, Any], local_out: Dict[str, Any], comp: Dict[str, Any]) -> str:
    aliases = row.get("alias_candidates")
    if not isinstance(aliases, list):
        aliases = []
    payload = {
        "candidate_id": row.get("id", ""),
        "source_text": row.get("source_text", ""),
        "en_name_candidate": row.get("en_name_candidate", ""),
        "cn_name_candidate": row.get("cn_name_candidate", ""),
        "alias_candidates": aliases,
        "laterality_candidate": row.get("laterality_candidate", "unknown"),
        "granularity_candidate": row.get("granularity_candidate", "unknown"),
        "parent_region_candidate": row.get("parent_region_candidate", ""),
        "region_category_candidate": row.get("region_category_candidate", "brain_region"),
        "ontology_source_candidate": row.get("ontology_source_candidate", "workbench"),
        "confidence": float(row.get("confidence") or 0),
        "local_rules": {
            "verdict": local_out.get("verdict"),
            "skipped": local_out.get("skipped"),
            "issues_preview": (local_out.get("evaluation") or {}).get("issues", [])[:12],
        },
        "missing_fields": comp.get("missing_fields", []),
    }
    return json.dumps(payload, ensure_ascii=False)


def run_llm_region_fix_and_complete(
    row: Dict[str, Any],
    local_out: Dict[str, Any],
    comp: Dict[str, Any],
    llm_cfg: Dict[str, Any],
    *,
    label: str = "deepseek",
) -> Dict[str, Any]:
    if not llm_cfg.get("api_key"):
        return {"ok": False, "error": f"{label}_api_key_missing"}
    user_msg = build_region_fix_user_payload(row, local_out, comp)
    content = openai_compatible_chat(
        base_url=_openai_base_url(llm_cfg, label=label),
        api_key=str(llm_cfg.get("api_key", "")),
        model=str(llm_cfg.get("model", "deepseek-chat")),
        messages=[
            {"role": "system", "content": REGION_FIX_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=float(llm_cfg.get("temperature", 0.2)),
        max_tokens=int(llm_cfg.get("max_tokens", 4096) or 4096),
        force_json=_openai_force_json(llm_cfg, label=label),
        timeout_sec=int(llm_cfg.get("request_timeout_sec", 120)),
        retries=int(llm_cfg.get("request_retries", 2)),
        backoff_sec=float(llm_cfg.get("retry_backoff_sec", 1.2)),
    )
    parsed = _extract_json_object(content)
    if not parsed:
        return {
            "ok": False,
            "error": f"{label}_json_parse_failed",
            "raw_content_preview": (content or "")[:500],
        }
    patch = normalize_llm_fix_patch(parsed)
    rationale = parsed.get("rationale", "") if isinstance(parsed.get("rationale"), str) else ""
    return {"ok": True, "patch": patch, "rationale": rationale, "raw_content_preview": (content or "")[:500]}


def merge_patch_prefer_non_empty(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if k not in _PATCH_KEYS:
            continue
        if v is None:
            continue
        if k == "alias_candidates":
            if isinstance(v, list) and len(v) > 0:
                out[k] = v
            continue
        if isinstance(v, str) and str(v).strip() == "":
            continue
        if k not in out or out[k] in (None, "", []):
            out[k] = v
    return out


def run_llm_region_fix_and_complete_multi(
    row: Dict[str, Any],
    local_out: Dict[str, Any],
    comp: Dict[str, Any],
    moon_cfg: Dict[str, Any],
    deep_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    km = run_llm_region_fix_and_complete(row, local_out, comp, moon_cfg, label="kimi")
    ds = run_llm_region_fix_and_complete(row, local_out, comp, deep_cfg, label="deepseek")
    pm = {"kimi": km, "deepseek": ds}
    kimi_ok = bool(km.get("ok"))
    deepseek_ok = bool(ds.get("ok"))
    if ds.get("ok") and km.get("ok"):
        merged = merge_patch_prefer_non_empty(ds.get("patch") or {}, km.get("patch") or {})
        return {
            "ok": True,
            "patch": merged,
            "per_model": pm,
            "kimi_ok": True,
            "deepseek_ok": True,
            "rationale": f"kimi:{km.get('rationale','')} | deepseek:{ds.get('rationale','')}",
        }
    if ds.get("ok"):
        return {
            **ds,
            "per_model": pm,
            "kimi_ok": kimi_ok,
            "deepseek_ok": True,
            "partial": True,
            "partial_note": "kimi_failed_deepseek_ok",
        }
    if km.get("ok"):
        return {
            **km,
            "per_model": pm,
            "kimi_ok": True,
            "deepseek_ok": deepseek_ok,
            "partial": True,
            "partial_note": "deepseek_failed_kimi_ok",
        }
    err = ds.get("error") or km.get("error") or "multi_llm_failed"
    return {
        "ok": False,
        "error": err,
        "per_model": pm,
        "kimi_ok": kimi_ok,
        "deepseek_ok": deepseek_ok,
    }
