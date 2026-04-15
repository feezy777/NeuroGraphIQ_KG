"""第 2 层：高召回候选（依赖内置 KB + registry 黑名单/白名单）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .region_registry_config import overlay_sets
from .region_text_normalize import normalize_cell_text


def _kb_lookup(text: str):
    from . import extraction_service as es

    return es._lookup_kb(text)


def _kb_partial(text: str):
    from . import extraction_service as es

    return es._partial_kb_match(text)


def _split_compound(text: str) -> List[str]:
    """多脑区串联粗切分。"""
    if not text:
        return []
    parts = []
    for seg in text.replace("；", ";").replace("、", ",").split(","):
        for s2 in seg.split(";"):
            t = s2.strip()
            if t:
                parts.append(t)
    return parts if parts else [text.strip()]


def recall_from_cell(
    raw_cell: str,
    *,
    overlay: Dict[str, Any],
    sheet: str,
    row_idx: int,
    col_idx: int,
    column_role: str,
) -> List[Dict[str, Any]]:
    """单单元格召回 0..n 个候选。"""
    sets = overlay_sets(overlay)
    blacklist = sets["blacklist"]
    whitelist = sets["whitelist"]

    norm = normalize_cell_text(raw_cell)
    nt = norm["normalized_text"]
    if not nt:
        return []

    if nt.lower() in blacklist:
        return [
            {
                "canonical_en": "",
                "canonical_cn": "",
                "matched_text": raw_cell,
                "match_type": "rejected_blacklist",
                "granularity": "unknown",
                "laterality": "unknown",
                "parent_region": "",
                "confidence_base": 0.0,
                "evidence_span": {"sheet": sheet, "row": row_idx, "col": col_idx, "role": column_role},
                "normalization_trace": norm["normalization_trace"],
            }
        ]

    out: List[Dict[str, Any]] = []
    pieces = _split_compound(nt)
    weight = 1.0
    if column_role in ("remark", "method"):
        weight = 0.55
    if column_role == "circuit":
        weight = 0.65

    for piece in pieces:
        if piece.lower() in blacklist:
            continue
        entry: Optional[Tuple] = _kb_lookup(piece) or _kb_partial(piece)
        if entry:
            en, cn, abbrevs, gran, parent, cat = entry
            mt = "exact" if _kb_lookup(piece) else "fuzzy"
            out.append(
                {
                    "canonical_en": en,
                    "canonical_cn": cn,
                    "canonical_aliases": list(abbrevs),
                    "matched_text": piece,
                    "match_type": mt,
                    "granularity": gran,
                    "laterality": "unknown",
                    "parent_region": parent,
                    "region_category": cat,
                    "confidence_base": min(0.95 * weight, 0.95),
                    "evidence_span": {
                        "sheet": sheet,
                        "row": row_idx,
                        "col": col_idx,
                        "role": column_role,
                        "raw_fragment": piece,
                    },
                    "normalization_trace": norm["normalization_trace"],
                }
            )
        elif piece.lower() in whitelist:
            out.append(
                {
                    "canonical_en": "",
                    "canonical_cn": "",
                    "matched_text": piece,
                    "match_type": "whitelist_unknown",
                    "granularity": "unknown",
                    "laterality": "unknown",
                    "parent_region": "",
                    "region_category": "brain_region",
                    "confidence_base": 0.45 * weight,
                    "evidence_span": {"sheet": sheet, "row": row_idx, "col": col_idx, "role": column_role},
                    "normalization_trace": norm["normalization_trace"],
                }
            )
        else:
            # 未命中 KB：保留 unresolved 占位
            if len(piece) >= 2 and not piece.isdigit():
                out.append(
                    {
                        "canonical_en": "",
                        "canonical_cn": "",
                        "matched_text": piece,
                        "match_type": "unresolved_oov",
                        "granularity": "unknown",
                        "laterality": "unknown",
                        "parent_region": "",
                        "region_category": "unknown",
                        "confidence_base": 0.25 * weight,
                        "evidence_span": {"sheet": sheet, "row": row_idx, "col": col_idx, "role": column_role},
                        "normalization_trace": norm["normalization_trace"],
                    }
                )
    return out
