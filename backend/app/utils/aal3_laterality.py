"""AAL3 laterality normalization and region base name extraction for raw parsing."""

from __future__ import annotations

import re

_HEMI_SUFFIX = re.compile(r"_(L|R|Bi|Bilateral)$", re.IGNORECASE)
_MIDLINE_TERMS = frozenset({"vermis", "cerebellar_vermis", "midline"})


def infer_laterality(raw_name: str, parser_hemisphere: str | None = None) -> str:
    """Map parser/XML hemisphere hints and name patterns to DB laterality enum."""
    if parser_hemisphere:
        mapped = {
            "L": "left",
            "l": "left",
            "R": "right",
            "r": "right",
            "BI": "bilateral",
            "bi": "bilateral",
            "bilateral": "bilateral",
        }.get(parser_hemisphere)
        if mapped:
            return mapped

    name = raw_name or ""
    lower = name.lower()

    if any(t in lower for t in _MIDLINE_TERMS) or "midline" in lower:
        return "midline"
    if "bilateral" in lower or "双侧" in name or "_bi" in lower:
        return "bilateral"
    if (
        lower.endswith("_l")
        or lower.endswith("-l")
        or " left" in lower
        or lower.startswith("left ")
        or "左" in name
        or "左侧" in name
    ):
        return "left"
    if (
        lower.endswith("_r")
        or lower.endswith("-r")
        or " right" in lower
        or lower.startswith("right ")
        or "右" in name
        or "右侧" in name
    ):
        return "right"
    return "unknown"


def extract_region_base_name(raw_name: str) -> str | None:
    """Strip laterality suffix from atlas label name."""
    if not raw_name:
        return None
    base = _HEMI_SUFFIX.sub("", raw_name.strip())
    return base if base != raw_name.strip() else raw_name.strip()
