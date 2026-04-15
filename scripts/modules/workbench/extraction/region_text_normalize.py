"""第 1 层：单元格/片段文本预标准化（最小侵入，可追踪）。"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List


def normalize_cell_text(raw: str) -> Dict[str, Any]:
    """保留 raw_text，生成 normalized_text 与 normalization_trace。"""
    trace: List[str] = []
    if raw is None:
        return {"raw_text": "", "normalized_text": "", "normalization_trace": ["empty"]}
    s = str(raw)
    trace.append("unicode_nfkc")
    s = unicodedata.normalize("NFKC", s)
    trace.append("fullwidth_punct_halfwidth_common")
    s = s.replace("，", ",").replace("；", ";").replace("（", "(").replace("）", ")")
    s = s.replace("－", "-").replace("–", "-").replace("—", "-")
    trace.append("collapse_whitespace")
    s = re.sub(r"\s+", " ", s).strip()
    trace.append("lower_for_ascii_tokens")
    # 仅对明显英文 token 做小写，避免破坏中文
    parts = re.split(r"(\s+|[,;|/])", s)
    out_parts: List[str] = []
    for p in parts:
        if not p or p.isspace() or p in ",;|/":
            out_parts.append(p)
            continue
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9\-_.]*", p):
            out_parts.append(p.lower())
        else:
            out_parts.append(p)
    s2 = "".join(out_parts)
    trace.append("laterality_tokens")
    lat_map = [
        (r"\bl\b", "left"),
        (r"\br\b", "right"),
        (r"\bbilateral\b", "bilateral"),
        (r"双侧", "bilateral"),
        (r"左侧", "left"),
        (r"右侧", "right"),
    ]
    s3 = s2
    for pat, rep in lat_map:
        s3 = re.sub(pat, rep, s3, flags=re.IGNORECASE)
    if s3 != s2:
        trace.append("laterality_normalized")
    return {"raw_text": str(raw), "normalized_text": s3.strip(), "normalization_trace": trace}
