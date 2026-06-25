"""Laterality inference for Macro96 standard pool region names.

Deterministic rules only — no LLM. Returns unknown when uncertain.
"""

from __future__ import annotations

_MIDLINE_KEYWORDS_EN = (
    "vermis",
    "brain stem",
    "brainstem",
    "3rd ventricle",
    "4th ventricle",
    "corpus callosum",
    "white matter",
    "csf",
    "cerebrospinal fluid",
)


def infer_macro96_laterality(en_name: str | None, cn_name: str | None) -> str:
    """Infer laterality from Macro96 en_name / cn_name.

    Returns one of: left, right, bilateral, midline, unknown.
    """
    en = (en_name or "").strip().lower()
    cn = (cn_name or "").strip()

    if en.startswith("left "):
        return "left"
    if en.startswith("right "):
        return "right"

    if "bilateral" in en:
        return "bilateral"

    if cn and "左" in cn:
        return "left"
    if cn and "右" in cn:
        return "right"
    if cn and "双侧" in cn:
        return "bilateral"

    for kw in _MIDLINE_KEYWORDS_EN:
        if kw in en:
            return "midline"

    if cn and any(k in cn for k in ("脑干", "小脑蚓部", "胼胝体", "脑白质")):
        return "midline"

    return "unknown"
