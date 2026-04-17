"""
三层脑区颗粒度（major / sub / allen）固定规则、统一输出 schema、校验与 LLM 提示模板。

说明：Allen 在本系统中作为 **fine-resolution 标签**，表示「采用 Allen 来源的标准细粒度节点」，
不代表生物学上全局最细或唯一最细层级。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# ── 常量 ───────────────────────────────────────────────────────────────────

GRANULARITY_MAJOR = "major"
GRANULARITY_SUB = "sub"
GRANULARITY_ALLEN = "allen"
GRANULARITIES: Tuple[str, ...] = (GRANULARITY_MAJOR, GRANULARITY_SUB, GRANULARITY_ALLEN)

LATERALITY_LEFT = "left"
LATERALITY_RIGHT = "right"
LATERALITY_BILATERAL = "bilateral"
LATERALITY_MIDLINE = "midline"
LATERALITY_UNKNOWN = "unknown"
LATERALITIES: Tuple[str, ...] = (
    LATERALITY_LEFT,
    LATERALITY_RIGHT,
    LATERALITY_BILATERAL,
    LATERALITY_MIDLINE,
    LATERALITY_UNKNOWN,
)

PRIMARY_PARENT_GRANULARITY_ROOT = "root"
PRIMARY_PARENT_GRANULARITY_MAJOR = "major"
PRIMARY_PARENT_GRANULARITY_SUB = "sub"
PRIMARY_PARENT_GRANULARITIES: Tuple[str, ...] = (
    PRIMARY_PARENT_GRANULARITY_ROOT,
    PRIMARY_PARENT_GRANULARITY_MAJOR,
    PRIMARY_PARENT_GRANULARITY_SUB,
)

ENTITY_BRAIN_REGION = "brain_region"

ALLEN_TAG_DISCLAIMER_ZH = (
    "Allen 是系统中的 fine-resolution 标签，不代表生物学上绝对最细层级，"
    "只代表当前系统采用的 Allen 来源标准细粒度节点。"
)

# 非脑区实体：关键词（小写）→ 拒绝原因码
NON_BRAIN_EXCLUSION_PATTERNS: List[Tuple[str, str]] = [
    (r"\bfunctional\s+network\b", "functional_network"),
    (r"\bdefault\s+mode\s+network\b", "functional_network"),
    (r"\bcircuit\b", "circuit"),
    (r"回路", "circuit"),
    (r"\bfiber\s+tract\b", "fiber_tract"),
    (r"\bwhite\s+matter\s+tract\b", "fiber_tract"),
    (r"白质", "fiber_tract"),
    (r"纤维束", "fiber_tract"),
    (r"\bventricle\b", "ventricle"),
    (r"脑室", "ventricle"),
    (r"\bvessel\b", "vessel"),
    (r"血管", "vessel"),
    (r"\bcell\s+type\b", "cell_type"),
    (r"细胞类型", "cell_type"),
    (r"\bgene\b", "gene"),
    (r"基因", "gene"),
    (r"\breceptor\b", "receptor"),
    (r"受体", "receptor"),
    (r"\bdisease\b", "disease"),
    (r"疾病", "disease"),
    (r"\bsymptom\b", "symptom"),
    (r"症状", "symptom"),
]

# ── 名称侧化后缀剥离（canonical 名不带左右）──────────────────────────────────

_SIDE_SUFFIX_EN = re.compile(
    r"\s*,?\s*(left|right|bilateral|ipsilateral|contralateral)\s*$",
    re.IGNORECASE,
)
_SIDE_SUFFIX_CN = re.compile(r"[(（]?\s*(左|右|双侧)\s*[)）]?\s*$")
_PAREN_SIDE_EN = re.compile(r"\s*[(（]\s*(left|right|bilateral)\s*[)）]\s*$", re.IGNORECASE)


def strip_laterality_from_name(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""
    s = _PAREN_SIDE_EN.sub("", s).strip()
    s = _SIDE_SUFFIX_CN.sub("", s).strip()
    s = _SIDE_SUFFIX_EN.sub("", s).strip()
    return s


# ── 统一输出 schema（字典形态，与 JSON 一致）──────────────────────────────

def empty_unified_record() -> Dict[str, Any]:
    return {
        "entity_type": ENTITY_BRAIN_REGION,
        "granularity": GRANULARITY_MAJOR,
        "canonical_name_en": "",
        "canonical_name_cn": "",
        "alias": [],
        "description": "",
        "laterality": LATERALITY_UNKNOWN,
        "source": "",
        "source_id": "",
        "source_acronym": "",
        "primary_parent_name": "",
        "primary_parent_granularity": PRIMARY_PARENT_GRANULARITY_ROOT,
        "confidence": 0.0,
        "review_required": False,
        "review_reason": "",
        "status": "candidate",
    }


def _coerce_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _coerce_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _coerce_alias(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        parts = re.split(r"[,;，；\s]+", v)
        return [p.strip() for p in parts if p.strip()]
    return [str(v).strip()] if str(v).strip() else []


def row_to_unified_schema(row: Dict[str, Any]) -> Dict[str, Any]:
    """将 LLM 行（新 schema 或旧 CandidateRegion 键）归一为统一结构。"""
    r = row
    u = empty_unified_record()
    u["entity_type"] = _coerce_str(r.get("entity_type")) or ENTITY_BRAIN_REGION
    g = _coerce_str(r.get("granularity_candidate") or r.get("granularity")).lower()
    if g in GRANULARITIES:
        u["granularity"] = g
    elif g in {"", "unknown"}:
        u["granularity"] = GRANULARITY_MAJOR
    else:
        u["granularity"] = GRANULARITY_MAJOR

    u["canonical_name_en"] = strip_laterality_from_name(
        _coerce_str(r.get("canonical_name_en") or r.get("en_name_candidate") or r.get("en_name"))
    )
    u["canonical_name_cn"] = strip_laterality_from_name(
        _coerce_str(r.get("canonical_name_cn") or r.get("cn_name_candidate") or r.get("cn_name"))
    )
    u["alias"] = _coerce_alias(r.get("alias") if r.get("alias") is not None else r.get("alias_candidates"))
    u["description"] = _coerce_str(r.get("description"))
    lat = _coerce_str(r.get("laterality_candidate") or r.get("laterality")).lower()
    if lat in LATERALITIES:
        u["laterality"] = lat
    else:
        u["laterality"] = LATERALITY_UNKNOWN

    u["source"] = _coerce_str(r.get("source"))
    u["source_id"] = _coerce_str(r.get("source_id"))
    u["source_acronym"] = _coerce_str(r.get("source_acronym"))
    u["primary_parent_name"] = strip_laterality_from_name(_coerce_str(r.get("primary_parent_name") or r.get("parent_region_candidate") or r.get("parent_region")))
    ppg = _coerce_str(r.get("primary_parent_granularity")).lower()
    if ppg in PRIMARY_PARENT_GRANULARITIES:
        u["primary_parent_granularity"] = ppg
    else:
        # 从颗粒度推断默认父级类型
        if u["granularity"] == GRANULARITY_MAJOR:
            u["primary_parent_granularity"] = PRIMARY_PARENT_GRANULARITY_ROOT
        elif u["granularity"] == GRANULARITY_SUB:
            u["primary_parent_granularity"] = PRIMARY_PARENT_GRANULARITY_MAJOR
        else:
            u["primary_parent_granularity"] = PRIMARY_PARENT_GRANULARITY_SUB

    u["confidence"] = max(0.0, min(1.0, _coerce_float(r.get("confidence"), 0.7)))
    u["review_required"] = bool(r.get("review_required", False))
    u["review_reason"] = _coerce_str(r.get("review_reason"))
    st = _coerce_str(r.get("status")).lower()
    if st in {"candidate", "reviewed", "approved"}:
        u["status"] = st
    else:
        u["status"] = "candidate"
    return u


def match_non_brain_exclusion(text: str) -> Optional[str]:
    """若命中排除项，返回 reason code，否则 None。"""
    t = (text or "").strip().lower()
    if not t:
        return None
    for pat, code in NON_BRAIN_EXCLUSION_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            return code
    return None


def detect_non_brain_entity(u: Dict[str, Any]) -> Optional[str]:
    """综合名称、别名、描述、entity_type 检测是否应排除在非脑区体系之外。"""
    if (u.get("entity_type") or "").strip().lower() not in {"", ENTITY_BRAIN_REGION}:
        return "entity_type_not_brain_region"
    blob = " ".join(
        [
            u.get("canonical_name_en", ""),
            u.get("canonical_name_cn", ""),
            " ".join(u.get("alias") or []),
            u.get("description", ""),
        ]
    )
    return match_non_brain_exclusion(blob)


def validate_hierarchy(u: Dict[str, Any]) -> List[str]:
    """主层级 root→major→sub→allen 与单父语义（由字段表达）。"""
    err: List[str] = []
    g = u.get("granularity")
    ppg = u.get("primary_parent_granularity")
    parent_name = (u.get("primary_parent_name") or "").strip()

    if g == GRANULARITY_MAJOR:
        if ppg != PRIMARY_PARENT_GRANULARITY_ROOT:
            err.append("major_parent_must_be_root")
        if parent_name:
            err.append("major_must_not_have_named_parent")
    elif g == GRANULARITY_SUB:
        if ppg != PRIMARY_PARENT_GRANULARITY_MAJOR:
            err.append("sub_parent_granularity_must_be_major")
        if not parent_name:
            err.append("sub_requires_primary_parent_name")
    elif g == GRANULARITY_ALLEN:
        if ppg != PRIMARY_PARENT_GRANULARITY_SUB:
            err.append("allen_primary_parent_granularity_must_be_sub")
        if not parent_name:
            err.append("allen_requires_sub_parent_name")
    return err


def validate_allen_hard_constraints(u: Dict[str, Any]) -> Tuple[List[str], bool]:
    """Allen 硬约束；返回 (errors, review_required)。找不到合法 sub 父时强制 review。"""
    err: List[str] = []
    review = bool(u.get("review_required", False))
    if u.get("granularity") != GRANULARITY_ALLEN:
        return err, review

    src = (u.get("source") or "").strip()
    if src.lower() != "allen":
        err.append("allen_source_must_be_allen")
        review = True
    if not (u.get("source_id") or "").strip():
        err.append("allen_source_id_required")
        review = True
    if not (u.get("source_acronym") or "").strip():
        # 建议必填 → 不硬失败，但标 review
        review = True
    if u.get("primary_parent_granularity") != PRIMARY_PARENT_GRANULARITY_SUB:
        err.append("allen_parent_granularity_must_be_sub")
        review = True
    if not (u.get("primary_parent_name") or "").strip():
        err.append("allen_requires_sub_parent")
        review = True

    return err, review


def validate_unified_record(u: Dict[str, Any]) -> List[str]:
    """完整校验列表（不含排除项，排除请单独调用 detect_non_brain_entity）。"""
    errors: List[str] = []
    if u.get("granularity") not in GRANULARITIES:
        errors.append("invalid_granularity")

    lat = u.get("laterality")
    if lat not in LATERALITIES:
        errors.append("invalid_laterality")

    errors.extend(validate_hierarchy(u))
    allen_err, _ = validate_allen_hard_constraints(u)
    errors.extend(allen_err)
    return errors


def finalize_review_flags(u: Dict[str, Any], validation_errors: List[str], exclusion: Optional[str]) -> None:
    if exclusion:
        u["review_required"] = True
        u["review_reason"] = f"excluded_non_brain:{exclusion}"
        return
    if validation_errors:
        u["review_required"] = True
        u["review_reason"] = ";".join(validation_errors)[:500]
    if u.get("granularity") == GRANULARITY_ALLEN and not (u.get("source_id") or "").strip():
        u["review_required"] = True


def unified_to_candidate_fields(u: Dict[str, Any]) -> Dict[str, Any]:
    """映射为 normalize_region_llm_row 使用的扁平字段 + review 片段。"""
    return {
        "en_name_candidate": u["canonical_name_en"],
        "cn_name_candidate": u["canonical_name_cn"],
        "alias_candidates": u["alias"],
        "laterality_candidate": u["laterality"],
        "region_category_candidate": ENTITY_BRAIN_REGION,
        "granularity_candidate": u["granularity"],
        "parent_region_candidate": u["primary_parent_name"],
        "ontology_source_candidate": u["source"] or "brain_region_policy",
        "confidence": u["confidence"],
        "source_text": (u.get("description") or "")[:400],
    }


def staging_gate_reason(review_note: str) -> Optional[str]:
    """若 brain_region_classification 要求复核或已排除，返回原因码，否则 None。"""
    try:
        n = json.loads(review_note or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(n, dict):
        return None
    br = n.get("brain_region_classification")
    if not isinstance(br, dict):
        return None
    rr = str(br.get("review_reason") or "")
    if rr.startswith("excluded_non_brain"):
        return "excluded_non_brain_entity"
    if br.get("review_required"):
        return "granularity_review_required"
    return None


def merge_unified_into_review_note(existing_note: str, unified: Dict[str, Any]) -> str:
    try:
        base = json.loads(existing_note or "{}")
    except json.JSONDecodeError:
        base = {}
    if not isinstance(base, dict):
        base = {}
    base["brain_region_classification"] = unified
    base["wb_granularity_policy_version"] = "1"
    return json.dumps(base, ensure_ascii=False)


def dedupe_key(unified: Dict[str, Any]) -> str:
    """canonical_name_en + granularity + laterality 唯一组合（小写）。"""
    en = (unified.get("canonical_name_en") or "").strip().lower()
    g = (unified.get("granularity") or "").strip().lower()
    lat = (unified.get("laterality") or "").strip().lower()
    return f"{en}|{g}|{lat}"


# ── LLM 提示：可复用模板 ─────────────────────────────────────────────────────

LLM_CLASSIFICATION_PRIORITY_ZH = """
【分类优先级 — 必须严格遵守】
1) 先判断是否为「脑解剖脑区」实体；以下类型**不得**作为 brain_region：功能网络、circuit、白质纤维束、脑室、血管、细胞类型、基因、受体、疾病、症状等。
2) 再判断是否应为 Allen 图谱原生节点：仅当可对应 Allen 结构 ID 且来源为 Allen 时，granularity 才可为 allen。
3) 若非 Allen，再判断 major（宏观稳定分区）与 sub（经典解剖亚区）；禁止跳过 sub 直接将非 Allen 标为 allen。
4) 存在歧义时**保守处理**：review_required=true，**不要**自动下沉为 allen。
5) 只输出 JSON，不要输出解释性散文。
6) """ + ALLEN_TAG_DISCLAIMER_ZH

REGIONS_ARRAY_ITEM_SCHEMA_ZH = """
每个数组元素必须为对象，**仅**使用下列键（可省略空字符串字段，但 granularity、entity_type、laterality 建议始终给出）：
  entity_type           string  固定 "brain_region"（非脑区则不要输出该条，或 entity_type 填其它并设 review_required=true）
  granularity           string  仅 major | sub | allen
  canonical_name_en     string  标准英文名，**不含**左右侧后缀
  canonical_name_cn     string  标准中文名，**不含**左右侧后缀
  alias                 array   字符串别名缩写
  description           string  简短描述或证据短语
  laterality            string  仅 left | right | bilateral | midline | unknown
  source                string  来源；allen 节点必须为 "Allen"
  source_id               string  Allen 结构 ID；非 allen 可为空
  source_acronym        string  Allen 缩写；allen 时强烈建议填写
  primary_parent_name   string  主父节点显示名；major 留空
  primary_parent_granularity  string  root | major | sub — major 用 root；sub 的父为 major；allen 的父必须为 sub
  confidence            number  0~1
  review_required       boolean
  review_reason         string
  status                string  candidate | reviewed | approved
顶层必须为 {"regions":[ ... ]} ，不得其它顶层键。
"""


def build_three_tier_system_prompt() -> str:
    return (
        "你是神经解剖与脑图谱结构化分类助手。你必须只输出一个 JSON 对象，且仅含键 \"regions\"。"
        + LLM_CLASSIFICATION_PRIORITY_ZH
        + "\n"
        + REGIONS_ARRAY_ITEM_SCHEMA_ZH
    )


THREE_TIER_FILE_USER_TEMPLATE = (
    "从以下文本抽取**脑解剖脑区**候选，并严格按三层颗粒度规则分类。\n"
    + LLM_CLASSIFICATION_PRIORITY_ZH
    + "\n"
    + REGIONS_ARRAY_ITEM_SCHEMA_ZH
    + "\nTEXT:\n{TEXT}"
)


def build_three_tier_user_prompt_file_or_text(sample_text: str) -> str:
    return THREE_TIER_FILE_USER_TEMPLATE.replace("{TEXT}", sample_text)


def build_three_tier_user_prompt_direct(
    topic: str,
    species: str,
    granularity_hint: str,
    extra: str,
    atlas_block: str,
) -> str:
    return (
        f"请列出 {species} 与「{topic}」相关的脑区，粒度参考：{granularity_hint}。\n"
        f"{ALLEN_TAG_DISCLAIMER_ZH}\n"
        + REGIONS_ARRAY_ITEM_SCHEMA_ZH
        + (f"\n【补充说明】\n{extra}\n" if extra else "")
        + (atlas_block if atlas_block else "")
        + "\n只输出 JSON 对象 {\"regions\":[...]}，不要 Markdown 围栏。\n"
    )
