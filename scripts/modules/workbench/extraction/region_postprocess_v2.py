"""第 4 层：去重、状态分类（confirmed / review_needed / unresolved / rejected）。

所有提取路径共用 derive_region_extract_status() 统一打标：
  - confirmed      高置信 + 命中精确/KB            绿色
  - review_needed  中置信 / LLM 输出 / 模糊匹配   橙色
  - unresolved     无法映射到标准脑区               红色
  - rejected       明确黑名单词                    灰色
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

# ────────────────────────────────────────────────────────────────────
# 统一打标（所有提取路径调用）
# ────────────────────────────────────────────────────────────────────
_CONFIRM_THRESHOLD = 0.78   # 置信度 >= 此值 + 可靠来源 → confirmed
_REVIEW_THRESHOLD  = 0.45   # 置信度 >= 此值 → review_needed，否则 unresolved


def derive_region_extract_status(
    *,
    extraction_method: str,
    match_type: str,
    confidence: float,
    en_name: str,
    cn_name: str,
) -> str:
    """
    统一规则：根据提取方法、命中类型、置信度判定 extract_status。
    所有路径（deepseek / local_rule / region_v2_local）都使用此函数。
    """
    en = (en_name or "").strip()
    cn = (cn_name or "").strip()
    mt = (match_type or "").strip()

    if mt == "rejected_blacklist":
        return "rejected"

    if not en and not cn:
        return "unresolved"

    method = (extraction_method or "").lower()

    if method == "deepseek" or method.startswith("deepseek"):
        # LLM 输出：高置信认为确认，中置信需复核，低置信待解决
        if confidence >= _CONFIRM_THRESHOLD:
            return "confirmed"
        if confidence >= _REVIEW_THRESHOLD:
            return "review_needed"
        return "unresolved"

    if method == "local_rule":
        if mt == "exact" and confidence >= _CONFIRM_THRESHOLD:
            return "confirmed"
        if mt in ("fuzzy", "whitelist_unknown"):
            return "review_needed"
        if mt == "unresolved_oov":
            return "unresolved"
        return "review_needed" if confidence >= _REVIEW_THRESHOLD else "unresolved"

    if method.startswith("region_v2"):
        if mt == "exact" and confidence >= _CONFIRM_THRESHOLD:
            return "confirmed"
        if mt in ("fuzzy", "whitelist_unknown"):
            return "review_needed"
        if mt == "unresolved_oov":
            return "unresolved"
        return "review_needed" if confidence >= _REVIEW_THRESHOLD else "unresolved"

    if method == "allen_api":
        if confidence >= _CONFIRM_THRESHOLD and mt == "exact":
            return "confirmed"
        return "review_needed"

    # 兜底
    return "review_needed"


def assign_extract_status(candidate: Dict[str, Any]) -> str:
    """v2 召回候选专用（保持旧签名）。"""
    return derive_region_extract_status(
        extraction_method="region_v2_local",
        match_type=candidate.get("match_type") or "",
        confidence=float(candidate.get("confidence_base", 0.5)),
        en_name=candidate.get("canonical_en") or "",
        cn_name=candidate.get("canonical_cn") or "",
    )


def dedupe_candidates(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for c in cands:
        en = (c.get("canonical_en") or "").strip().lower()
        cn = (c.get("canonical_cn") or "").strip()
        mt = c.get("match_type")
        key = f"{en}|{cn}|{mt}|{c.get('evidence_span', {}).get('row')}|{c.get('evidence_span', {}).get('col')}"
        if key in seen:
            continue
        seen.add(key)
        c["extract_status"] = assign_extract_status(c)
        out.append(c)
    return out


def to_candidate_region_payload(
    c: Dict[str, Any],
    *,
    file_id: str,
    parsed_document_id: str,
    extraction_method: str,
) -> Tuple[Dict[str, Any], str]:
    """返回 (candidate_dict_for_state_store, review_note_json_str)。"""
    en = c.get("canonical_en") or ""
    cn = c.get("canonical_cn") or ""
    aliases = list(c.get("canonical_aliases") or [])
    conf = float(c.get("confidence_base", 0.5))
    meta = {
        "pipeline": "region_extraction_v2",
        "extract_status": c.get("extract_status", "review_needed"),
        "match_type": c.get("match_type"),
        "evidence_span": c.get("evidence_span"),
        "normalization_trace": c.get("normalization_trace"),
    }
    note = json.dumps({"wb_v2": meta}, ensure_ascii=False)
    row = {
        "id": None,  # filled by caller
        "file_id": file_id,
        "parsed_document_id": parsed_document_id,
        "chunk_id": "",
        "source_text": (c.get("matched_text") or "")[:400],
        "en_name_candidate": en,
        "cn_name_candidate": cn,
        "alias_candidates": aliases,
        "laterality_candidate": c.get("laterality") or "unknown",
        "region_category_candidate": c.get("region_category") or "brain_region",
        "granularity_candidate": c.get("granularity") or "unknown",
        "parent_region_candidate": c.get("parent_region") or "",
        "ontology_source_candidate": "region_pipeline_v2",
        "confidence": conf,
        "extraction_method": extraction_method,
        "llm_model": "",
        "status": "pending_review",
        "review_note": note,
    }
    return row, note
