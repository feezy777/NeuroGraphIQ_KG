from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib import error, request

from ..common.id_utils import make_id
from ..common.models import CandidateCircuit, CandidateConnection, CandidateRegion, utc_now_iso


# ---------------------------------------------------------------------------
# 脑区知识库 (KB)
# 每条记录: (en, cn, abbrevs, granularity, parent, category)
#   granularity : "major" | "sub" | "allen"
#   category    : cortex | hippocampal | amygdala | thalamus | basal_ganglia |
#                 hypothalamus | brainstem | cerebellum | olfactory | septal |
#                 white_matter | other
# ---------------------------------------------------------------------------
_KB_RAW: List[tuple] = [
    # ── 大脑皮层 ─────────────────────────────────────────────────────────────
    ("Cerebral Cortex", "大脑皮层", ["Cortex", "CTX"], "major", "", "cortex"),
    ("Prefrontal Cortex", "前额叶皮层", ["PFC"], "major", "Cerebral Cortex", "cortex"),
    ("Medial Prefrontal Cortex", "内侧前额叶皮层", ["mPFC", "medPFC"], "sub", "Prefrontal Cortex", "cortex"),
    ("Prelimbic Cortex", "边缘前皮层", ["PL", "PrL"], "sub", "Medial Prefrontal Cortex", "cortex"),
    ("Infralimbic Cortex", "边缘下皮层", ["IL"], "sub", "Medial Prefrontal Cortex", "cortex"),
    ("Orbitofrontal Cortex", "眶额皮层", ["OFC"], "major", "Prefrontal Cortex", "cortex"),
    ("Anterior Cingulate Cortex", "前扣带皮层", ["ACC", "ACCx"], "major", "Cerebral Cortex", "cortex"),
    ("Posterior Cingulate Cortex", "后扣带皮层", ["PCC"], "major", "Cerebral Cortex", "cortex"),
    ("Retrosplenial Cortex", "压后皮层", ["RSC", "RSP"], "major", "Cerebral Cortex", "cortex"),
    ("Insular Cortex", "岛叶皮层", ["Insula", "IC", "INS"], "major", "Cerebral Cortex", "cortex"),
    ("Motor Cortex", "运动皮层", ["MC", "M1", "M2"], "major", "Cerebral Cortex", "cortex"),
    ("Primary Motor Cortex", "初级运动皮层", ["M1"], "sub", "Motor Cortex", "cortex"),
    ("Secondary Motor Cortex", "次级运动皮层", ["M2"], "sub", "Motor Cortex", "cortex"),
    ("Somatosensory Cortex", "躯体感觉皮层", ["SSC", "S1", "S2", "SI", "SII"], "major", "Cerebral Cortex", "cortex"),
    ("Primary Somatosensory Cortex", "初级躯体感觉皮层", ["S1", "SI"], "sub", "Somatosensory Cortex", "cortex"),
    ("Visual Cortex", "视觉皮层", ["VC", "V1", "V2"], "major", "Cerebral Cortex", "cortex"),
    ("Primary Visual Cortex", "初级视觉皮层", ["V1", "Vi1"], "sub", "Visual Cortex", "cortex"),
    ("Auditory Cortex", "听觉皮层", ["AC", "AuC", "Au"], "major", "Cerebral Cortex", "cortex"),
    ("Perirhinal Cortex", "鼻周皮层", ["PRh", "PRC"], "major", "Cerebral Cortex", "cortex"),
    ("Entorhinal Cortex", "嗅内皮层", ["EC", "Ent"], "major", "Cerebral Cortex", "cortex"),
    ("Piriform Cortex", "梨状皮层", ["Pir"], "major", "Cerebral Cortex", "cortex"),
    ("Barrel Cortex", "桶状皮层", ["BC", "S1BF"], "sub", "Somatosensory Cortex", "cortex"),
    # ── 海马结构 ──────────────────────────────────────────────────────────────
    ("Hippocampus", "海马", ["HPC", "HC", "HIP", "Hip"], "major", "", "hippocampal"),
    ("Hippocampal Formation", "海马结构", ["HF"], "major", "", "hippocampal"),
    ("CA1", "海马CA1区", ["CA1"], "sub", "Hippocampus", "hippocampal"),
    ("CA2", "海马CA2区", ["CA2"], "sub", "Hippocampus", "hippocampal"),
    ("CA3", "海马CA3区", ["CA3"], "sub", "Hippocampus", "hippocampal"),
    ("Dentate Gyrus", "齿状回", ["DG", "DentateGyrus"], "sub", "Hippocampus", "hippocampal"),
    ("Subiculum", "下托", ["Sub", "SUB"], "sub", "Hippocampus", "hippocampal"),
    ("Presubiculum", "前下托", ["PreSub"], "sub", "Hippocampus", "hippocampal"),
    ("Entorhinal Cortex", "内嗅皮层", ["EC"], "major", "Hippocampal Formation", "hippocampal"),
    ("Dorsal Hippocampus", "背侧海马", ["dHPC", "dHC"], "sub", "Hippocampus", "hippocampal"),
    ("Ventral Hippocampus", "腹侧海马", ["vHPC", "vHC"], "sub", "Hippocampus", "hippocampal"),
    # ── 杏仁核 ───────────────────────────────────────────────────────────────
    ("Amygdala", "杏仁核", ["Amy", "AMY", "Amygdaloid"], "major", "", "amygdala"),
    ("Basolateral Amygdala", "基底外侧杏仁核", ["BLA", "BLAmy"], "sub", "Amygdala", "amygdala"),
    ("Basal Amygdala", "基底杏仁核", ["BA", "BA_amyg"], "sub", "Amygdala", "amygdala"),
    ("Lateral Amygdala", "外侧杏仁核", ["LA", "LAmyg"], "sub", "Amygdala", "amygdala"),
    ("Central Amygdala", "中央杏仁核", ["CeA", "CeAmy", "CeM", "CeL"], "sub", "Amygdala", "amygdala"),
    ("Medial Amygdala", "内侧杏仁核", ["MeA", "MeAmy"], "sub", "Amygdala", "amygdala"),
    ("Intercalated Cells", "嵌入细胞团", ["ITC"], "sub", "Amygdala", "amygdala"),
    # ── 丘脑 ─────────────────────────────────────────────────────────────────
    ("Thalamus", "丘脑", ["Thal", "TH"], "major", "", "thalamus"),
    ("Mediodorsal Thalamus", "背内侧丘脑核", ["MD", "MDT", "MDThal"], "sub", "Thalamus", "thalamus"),
    ("Anterior Thalamic Nucleus", "前丘脑核", ["ATN", "AD", "AV", "AM"], "sub", "Thalamus", "thalamus"),
    ("Reuniens Nucleus", "团核", ["RE", "Rh"], "sub", "Thalamus", "thalamus"),
    ("Lateral Geniculate Nucleus", "外侧膝状体核", ["LGN", "LGd", "LGv"], "sub", "Thalamus", "thalamus"),
    ("Medial Geniculate Nucleus", "内侧膝状体核", ["MGN", "MGv", "MGd"], "sub", "Thalamus", "thalamus"),
    ("Pulvinar", "丘脑枕", ["Pul"], "sub", "Thalamus", "thalamus"),
    ("Ventral Posteromedial Nucleus", "腹后内侧核", ["VPM"], "sub", "Thalamus", "thalamus"),
    ("Ventral Posterolateral Nucleus", "腹后外侧核", ["VPL"], "sub", "Thalamus", "thalamus"),
    ("Centromedian Nucleus", "中央内侧核", ["CM"], "sub", "Thalamus", "thalamus"),
    ("Paraventricular Thalamic Nucleus", "室旁丘脑核", ["PVT"], "sub", "Thalamus", "thalamus"),
    ("Reticular Thalamic Nucleus", "网状丘脑核", ["nRT", "TRN"], "sub", "Thalamus", "thalamus"),
    # ── 基底节 ───────────────────────────────────────────────────────────────
    ("Basal Ganglia", "基底节", ["BG"], "major", "", "basal_ganglia"),
    ("Striatum", "纹状体", ["STR", "Str", "CPu", "Cpu"], "major", "Basal Ganglia", "basal_ganglia"),
    ("Caudate Nucleus", "尾状核", ["Caud", "CP", "CN"], "sub", "Striatum", "basal_ganglia"),
    ("Putamen", "壳核", ["Put"], "sub", "Striatum", "basal_ganglia"),
    ("Caudate Putamen", "尾壳核", ["CPu", "CP", "Cpu"], "sub", "Striatum", "basal_ganglia"),
    ("Nucleus Accumbens", "伏隔核", ["NAc", "NAcc", "Acb", "ACB"], "sub", "Striatum", "basal_ganglia"),
    ("Nucleus Accumbens Core", "伏隔核核部", ["NAcC", "AcbC"], "sub", "Nucleus Accumbens", "basal_ganglia"),
    ("Nucleus Accumbens Shell", "伏隔核壳部", ["NAcSh", "AcbSh"], "sub", "Nucleus Accumbens", "basal_ganglia"),
    ("Globus Pallidus", "苍白球", ["GP"], "sub", "Basal Ganglia", "basal_ganglia"),
    ("Internal Globus Pallidus", "内侧苍白球", ["GPi", "GPint", "EntoPed"], "sub", "Globus Pallidus", "basal_ganglia"),
    ("External Globus Pallidus", "外侧苍白球", ["GPe", "GPext"], "sub", "Globus Pallidus", "basal_ganglia"),
    ("Substantia Nigra", "黑质", ["SN", "SNr", "SNc"], "sub", "Basal Ganglia", "basal_ganglia"),
    ("Substantia Nigra Pars Reticulata", "黑质网状部", ["SNr", "SNpr"], "sub", "Substantia Nigra", "basal_ganglia"),
    ("Substantia Nigra Pars Compacta", "黑质致密部", ["SNc", "SNpc"], "sub", "Substantia Nigra", "basal_ganglia"),
    ("Ventral Tegmental Area", "腹侧被盖区", ["VTA"], "sub", "Basal Ganglia", "basal_ganglia"),
    ("Subthalamic Nucleus", "丘脑底核", ["STN", "SubThal"], "sub", "Basal Ganglia", "basal_ganglia"),
    # ── 下丘脑 ───────────────────────────────────────────────────────────────
    ("Hypothalamus", "下丘脑", ["HYP", "Hyp", "HTH"], "major", "", "hypothalamus"),
    ("Lateral Hypothalamus", "外侧下丘脑", ["LH", "LHA"], "sub", "Hypothalamus", "hypothalamus"),
    ("Paraventricular Hypothalamic Nucleus", "下丘脑室旁核", ["PVN", "PVH"], "sub", "Hypothalamus", "hypothalamus"),
    ("Arcuate Nucleus", "弓状核", ["ARC", "ARH"], "sub", "Hypothalamus", "hypothalamus"),
    ("Ventromedial Hypothalamus", "腹内侧下丘脑", ["VMH", "VMHyp"], "sub", "Hypothalamus", "hypothalamus"),
    ("Dorsomedial Hypothalamus", "背内侧下丘脑", ["DMH", "DMHyp"], "sub", "Hypothalamus", "hypothalamus"),
    ("Suprachiasmatic Nucleus", "视交叉上核", ["SCN"], "sub", "Hypothalamus", "hypothalamus"),
    ("Supraoptic Nucleus", "视上核", ["SON"], "sub", "Hypothalamus", "hypothalamus"),
    # ── 脑干 ─────────────────────────────────────────────────────────────────
    ("Brainstem", "脑干", ["BS"], "major", "", "brainstem"),
    ("Midbrain", "中脑", ["MB", "Mid"], "major", "Brainstem", "brainstem"),
    ("Pons", "脑桥", ["Pons"], "major", "Brainstem", "brainstem"),
    ("Medulla", "延髓", ["Med", "Medulla Oblongata", "MO"], "major", "Brainstem", "brainstem"),
    ("Periaqueductal Gray", "导水管周围灰质", ["PAG", "DPAG", "VPAG", "LPAG"], "sub", "Midbrain", "brainstem"),
    ("Locus Coeruleus", "蓝斑", ["LC"], "sub", "Pons", "brainstem"),
    ("Dorsal Raphe Nucleus", "背缝核", ["DR", "DRN"], "sub", "Midbrain", "brainstem"),
    ("Median Raphe Nucleus", "中缝核", ["MnR", "MRN"], "sub", "Brainstem", "brainstem"),
    ("Superior Colliculus", "上丘", ["SC", "SUP"], "sub", "Midbrain", "brainstem"),
    ("Inferior Colliculus", "下丘", ["IC_col", "ICC", "ICx"], "sub", "Midbrain", "brainstem"),
    ("Nucleus of the Solitary Tract", "孤束核", ["NTS", "NST"], "sub", "Medulla", "brainstem"),
    ("Pedunculopontine Nucleus", "脑桥脚核", ["PPN", "PPT"], "sub", "Pons", "brainstem"),
    ("Parabrachial Nucleus", "臂旁核", ["PBN", "PB"], "sub", "Pons", "brainstem"),
    # ── 小脑 ─────────────────────────────────────────────────────────────────
    ("Cerebellum", "小脑", ["CB", "Cer", "CRB"], "major", "", "cerebellum"),
    ("Cerebellar Cortex", "小脑皮层", ["CbCx"], "sub", "Cerebellum", "cerebellum"),
    ("Deep Cerebellar Nuclei", "深小脑核", ["DCN"], "sub", "Cerebellum", "cerebellum"),
    ("Dentate Nucleus", "小脑齿状核", ["DentN", "DN_cer"], "sub", "Deep Cerebellar Nuclei", "cerebellum"),
    ("Purkinje Cell Layer", "浦肯野细胞层", ["PCL"], "sub", "Cerebellar Cortex", "cerebellum"),
    # ── 嗅觉系统 ─────────────────────────────────────────────────────────────
    ("Olfactory Bulb", "嗅球", ["OB", "MOB", "AOB"], "major", "", "olfactory"),
    ("Main Olfactory Bulb", "主嗅球", ["MOB"], "sub", "Olfactory Bulb", "olfactory"),
    ("Olfactory Cortex", "嗅皮层", ["OC"], "major", "", "olfactory"),
    ("Anterior Olfactory Nucleus", "前嗅核", ["AON", "AOB_n"], "sub", "Olfactory Bulb", "olfactory"),
    # ── 隔区 & 边缘系统 ───────────────────────────────────────────────────────
    ("Septum", "隔区", ["Sep", "Septa"], "major", "", "septal"),
    ("Lateral Septum", "外侧隔区", ["LS"], "sub", "Septum", "septal"),
    ("Medial Septum", "内侧隔区", ["MS"], "sub", "Septum", "septal"),
    ("Diagonal Band of Broca", "布罗卡斜角带", ["DBB", "HDB", "VDB"], "sub", "Septum", "septal"),
    ("Bed Nucleus of Stria Terminalis", "终纹床核", ["BNST", "BST"], "sub", "", "septal"),
    ("Habenula", "缰核", ["Hab", "Hb"], "sub", "", "other"),
    ("Lateral Habenula", "外侧缰核", ["LHb"], "sub", "Habenula", "other"),
    ("Medial Habenula", "内侧缰核", ["MHb"], "sub", "Habenula", "other"),
    ("Claustrum", "屏状核", ["CL", "Cl"], "sub", "", "other"),
    # ── 白质/纤维束 ───────────────────────────────────────────────────────────
    ("Corpus Callosum", "胼胝体", ["CC"], "major", "", "white_matter"),
    ("Fornix", "穹窿", ["Fx", "FX"], "major", "", "white_matter"),
    ("Fimbria", "伞", ["Fi"], "sub", "Hippocampus", "white_matter"),
    ("Internal Capsule", "内囊", ["IC_cap"], "major", "", "white_matter"),
    ("Anterior Commissure", "前连合", ["AC_com"], "sub", "", "white_matter"),
    # ── 脑室相关 ─────────────────────────────────────────────────────────────
    ("Lateral Ventricle", "侧脑室", ["LV"], "major", "", "other"),
    ("Third Ventricle", "第三脑室", ["3V"], "sub", "", "other"),
]

# ── 构建查找索引 ─────────────────────────────────────────────────────────────
# key(小写) → (en, cn, abbrevs, granularity, parent, category)
_KB: Dict[str, tuple] = {}
for _entry in _KB_RAW:
    _en, _cn, _abbrevs, _gran, _parent, _cat = _entry
    for _k in [_en, _cn] + list(_abbrevs):
        _k_lo = _k.strip().lower()
        if _k_lo and _k_lo not in _KB:
            _KB[_k_lo] = _entry

# 全量 hints（用于快速跳过不含任何脑区词的行）
_ALL_HINTS: List[str] = sorted({k for k in _KB}, key=len, reverse=True)

# 用于文本内段落级别的正则提取：匹配常见脑区名称模式
_REGION_INLINE_RE = re.compile(
    r"\b("
    + "|".join(
        re.escape(k)
        for k in sorted(_KB, key=len, reverse=True)
        if len(k) >= 2
    )
    + r")\b",
    re.IGNORECASE,
)

# 表头关键词 → 含义
_HEADER_COL_MAP = {
    "region": "name",
    "name": "name",
    "脑区": "name",
    "区域": "name",
    "名称": "name",
    "en": "en",
    "en_name": "en",
    "english": "en",
    "english name": "en",
    "英文": "en",
    "英文名": "en",
    "cn": "cn",
    "cn_name": "cn",
    "chinese": "cn",
    "chinese name": "cn",
    "中文": "cn",
    "中文名": "cn",
    "abbrev": "abbrev",
    "abbreviation": "abbrev",
    "abbr": "abbrev",
    "缩写": "abbrev",
    "granularity": "granularity",
    "粒度": "granularity",
    "level": "granularity",
    "parent": "parent",
    "父区": "parent",
    "laterality": "laterality",
    "侧向": "laterality",
    "side": "laterality",
    "category": "category",
    "类别": "category",
    "confidence": "confidence",
    "置信度": "confidence",
}


def _lookup_kb(text: str) -> tuple | None:
    """精确查找 KB；返回 entry tuple 或 None。"""
    t = (text or "").strip().lower()
    if not t:
        return None
    return _KB.get(t)


def _partial_kb_match(text: str) -> tuple | None:
    """在 text 中搜索最长 KB key，返回首个最长命中的 entry。"""
    best: tuple | None = None
    best_len = 0
    tl = text.lower()
    for k, v in _KB.items():
        if len(k) > best_len and k in tl:
            best = v
            best_len = len(k)
    return best


def _guess_laterality(text: str) -> str:
    s = (text or "").lower()
    if any(k in s for k in ["left", "左侧", "左"]):
        return "left"
    if any(k in s for k in ["right", "右侧", "右"]):
        return "right"
    if any(k in s for k in ["bilateral", "双侧", "两侧"]):
        return "bilateral"
    if any(k in s for k in ["midline", "中线", "中央"]):
        return "midline"
    return "unknown"


def _is_ascii_only(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


def _make_candidate(
    file_id: str,
    parsed_document_id: str,
    chunk_id: str,
    source_text: str,
    en: str,
    cn: str,
    abbrevs: list,
    granularity: str,
    parent: str,
    category: str,
    laterality: str,
    confidence: float,
) -> CandidateRegion:
    return CandidateRegion(
        id=make_id("cr"),
        file_id=file_id,
        parsed_document_id=parsed_document_id,
        chunk_id=chunk_id,
        source_text=(source_text or "")[:400],
        en_name_candidate=en,
        cn_name_candidate=cn,
        alias_candidates=[a for a in abbrevs if a],
        laterality_candidate=laterality,
        region_category_candidate=category or "brain_region",
        granularity_candidate=granularity or "unknown",
        parent_region_candidate=parent or "",
        ontology_source_candidate="local_rule_kb",
        confidence=confidence,
        extraction_method="local_rule",
        llm_model="",
        status="pending_review",
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )


# DeepSeek 脑区抽取：规划好的 user prompt（需含 {TEXT}）
REGION_USER_PROMPT_PRESETS: Dict[str, str] = {
    "default": (
        "你是脑区知识图谱抽取专家。请从以下文本中完整抽取所有脑区名称候选。\n"
        "返回JSON数组，每项字段：\n"
        "  en_name_candidate      （英文名，如无则空字符串）\n"
        "  cn_name_candidate      （中文名，如无则空字符串）\n"
        "  alias_candidates       （别名/缩写列表，如 [\"PFC\",\"mPFC\"]）\n"
        "  laterality_candidate   （left/right/bilateral/midline/unknown）\n"
        "  region_category_candidate （如 cortex/hippocampus/amygdala 等）\n"
        "  granularity_candidate  （major/sub/allen/unknown）\n"
        "  parent_region_candidate（父区名，如无则空字符串）\n"
        "  confidence             （0-1 浮点数）\n"
        "  source_text            （原文引用，不超过100字）\n"
        "只返回JSON数组，不要有其他内容。\n\n"
        "TEXT:\n{TEXT}"
    ),
    "detailed": (
        "你是神经解剖与脑图谱专家。请从以下文本中「穷尽」抽取所有脑区候选（含缩写、别名、英文/中文）。\n"
        "同一脑区多种写法合并为一条；尽量给出 laterality 与合理 confidence。\n"
        "返回JSON数组，字段与 default 预设相同。\n\n"
        "TEXT:\n{TEXT}"
    ),
    "minimal": (
        "从下列文本抽取脑区名称，只输出 JSON 数组。"
        "字段：en_name_candidate,cn_name_candidate,alias_candidates,laterality_candidate,"
        "region_category_candidate,granularity_candidate,parent_region_candidate,confidence,source_text。"
        "granularity_candidate ∈ major/sub/allen/unknown。\n\nTEXT:\n{TEXT}"
    ),
}

DEFAULT_DEEPSEEK_SYSTEM = "你是脑区知识图谱抽取助手，只返回 JSON 数组，不要 Markdown 代码围栏。"


def compose_region_file_user_prompt(sample_text: str, cfg: Dict[str, Any]) -> str:
    """根据配置组合文件/文本脑区抽取的 user 消息正文。"""
    custom = (cfg.get("region_user_prompt_template") or "").strip()
    if custom:
        body = custom.replace("{TEXT}", sample_text)
    else:
        pid = (cfg.get("region_prompt_preset") or "default").strip()
        template = REGION_USER_PROMPT_PRESETS.get(pid, REGION_USER_PROMPT_PRESETS["default"])
        body = template.replace("{TEXT}", sample_text)
    prefix = (cfg.get("user_prompt_prefix") or "").strip()
    if prefix:
        body = prefix + "\n\n" + body
    return body


def compose_direct_region_user_prompt(params: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    """根据配置组合「直接生成」脑区的 user 消息；模板可用占位符 TOPIC/SPECIES/GRANULARITY/EXTRA。"""
    topic = (params.get("topic") or "脑区").strip()
    species = (params.get("species") or "小鼠").strip()
    granularity = (params.get("granularity") or "major").strip()
    extra = (params.get("extra_instructions") or "").strip()
    custom = (cfg.get("direct_region_user_prompt_template") or "").strip()
    if custom:
        return (
            custom.replace("{TOPIC}", topic)
            .replace("{SPECIES}", species)
            .replace("{GRANULARITY}", granularity)
            .replace("{EXTRA}", extra)
        )
    pid = (cfg.get("direct_region_prompt_preset") or "default").strip()
    if pid == "detailed":
        return (
            f"请系统、完整地列出{species}与「{topic}」相关的脑区名称（中英文），粒度参考为{granularity}。"
            "需兼顾皮层、皮层下、脑干、小脑等常见分区；若有缩写请列入 alias_candidates。"
            "返回JSON数组，每项字段："
            "en_name_candidate,cn_name_candidate,alias_candidates,laterality_candidate,"
            "region_category_candidate,granularity_candidate,parent_region_candidate,confidence,source_text。"
            "granularity_candidate只允许major/sub/allen/unknown。\n"
            f"{extra}"
        )
    if pid == "minimal":
        return (
            f"列出{species}与「{topic}」相关的脑区（粒度 {granularity}）。"
            "返回JSON数组，字段：en_name_candidate,cn_name_candidate,alias_candidates,laterality_candidate,"
            "region_category_candidate,granularity_candidate,parent_region_candidate,confidence,source_text。\n"
            f"{extra}"
        )
    return ExtractionService.build_region_prompt("direct_generate", params)


def deepseek_system_content(cfg: Dict[str, Any]) -> str:
    s = (cfg.get("system_prompt") or "").strip()
    return s if s else DEFAULT_DEEPSEEK_SYSTEM


def _detect_header_col_types(header_values: List[str]) -> Dict[int, str]:
    """根据 Excel 表头行推断各列的语义（选最长匹配模式）。"""
    col_types: Dict[int, str] = {}
    for idx, cell in enumerate(header_values):
        key = (cell or "").strip().lower()
        best_pattern = ""
        best_ctype = ""
        for pattern, ctype in _HEADER_COL_MAP.items():
            if pattern in key and len(pattern) > len(best_pattern):
                best_pattern = pattern
                best_ctype = ctype
        if best_ctype:
            col_types[idx] = best_ctype
    return col_types


class ExtractionService:
    def run_region_extraction(
        self,
        file_payload: Dict[str, Any],
        parsed_payload: Dict[str, Any],
        mode: str,
        deepseek_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        chunks = parsed_payload.get("chunks", [])
        parsed_doc = parsed_payload.get("document", {})
        parsed_document_id = parsed_doc.get("parsed_document_id", "")

        table_rows: List[Dict[str, Any]] = list(
            parsed_doc.get("table_rows") or []
            if isinstance(parsed_doc, dict)
            else getattr(parsed_doc, "table_rows", []) or []
        )
        fp_with_raw = dict(file_payload)
        fp_with_raw.setdefault("raw_text", parsed_doc.get("raw_text", "") if isinstance(parsed_doc, dict) else "")

        if mode == "deepseek":
            candidates = self._extract_by_deepseek(file_payload, chunks, parsed_document_id, deepseek_cfg, table_rows=table_rows)
            return {"method": "deepseek", "llm_model": deepseek_cfg.get("model", ""), "candidates": candidates}

        candidates = self._extract_by_local_rules(fp_with_raw, chunks, parsed_document_id, table_rows=table_rows)
        return {"method": "local_rule", "llm_model": "", "candidates": candidates}

    def _extract_by_local_rules(
        self,
        file_payload: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        parsed_document_id: str,
        table_rows: Optional[List[Dict[str, Any]]] = None,
    ) -> List[CandidateRegion]:
        file_id = file_payload.get("file_id", "")
        rows: List[CandidateRegion] = []
        seen: set = set()

        def _add(en: str, cn: str, abbrevs: list, gran: str, parent: str, cat: str,
                 lat: str, conf: float, src: str, cid: str) -> None:
            key = (en.strip().lower() if en else cn.strip().lower() if cn else "")
            if not key or key in seen:
                return
            seen.add(key)
            rows.append(_make_candidate(
                file_id, parsed_document_id, cid, src,
                en, cn, abbrevs, gran, parent, cat, lat, conf,
            ))

        # ── 路径0：结构化 table_rows（带表头语义映射，最精准）───────────────────
        if table_rows:
            header_col_types: Dict[int, str] = {}
            data_rows: List[Dict[str, Any]] = []
            for tr in table_rows[:10000]:
                vals: List[str] = tr.get("values") or tr.get("cells") or []
                row_idx: int = tr.get("row", -1)
                if row_idx == 0:
                    # treat as header row
                    header_col_types = _detect_header_col_types(vals)
                    continue
                if not header_col_types and row_idx == 1:
                    # attempt header on first data row when row 0 missing
                    header_col_types = _detect_header_col_types(vals)
                    continue
                data_rows.append({"vals": vals, "row": row_idx, "sheet": tr.get("sheet", "")})

            if header_col_types:
                # Structured extraction: fill fields from mapped columns
                for dr in data_rows:
                    vals = dr["vals"]
                    field_map: Dict[str, str] = {}
                    for col_idx, ctype in header_col_types.items():
                        if col_idx < len(vals):
                            field_map[ctype] = (vals[col_idx] or "").strip()

                    # Resolve en/cn/name
                    raw_name = field_map.get("name", "")
                    raw_en = field_map.get("en", "")
                    raw_cn = field_map.get("cn", "")

                    # Try KB lookup in priority order
                    entry: Optional[tuple] = (
                        _lookup_kb(raw_en) or _lookup_kb(raw_cn) or
                        _lookup_kb(raw_name) or _partial_kb_match(raw_en or raw_cn or raw_name)
                    )
                    if entry:
                        kb_en, kb_cn, kb_abbrevs, kb_gran, kb_parent, kb_cat = entry
                        en = raw_en or kb_en
                        cn = raw_cn or kb_cn
                        abbrevs = [a for a in field_map.get("abbrev", "").split(",") if a.strip()] or list(kb_abbrevs)
                        gran = field_map.get("granularity") or kb_gran
                        parent = field_map.get("parent") or kb_parent
                        cat = field_map.get("category") or kb_cat
                        lat = field_map.get("laterality") or _guess_laterality(" ".join(vals))
                        conf = float(field_map.get("confidence") or 0) or 0.95
                        src = " | ".join(v for v in vals if v)[:300]
                        _add(en, cn, abbrevs, gran, parent, cat, lat, conf, src, f"row_{dr['row']}")
                    elif raw_name or raw_en or raw_cn:
                        # No KB match but has explicit name columns → keep with lower confidence
                        name = raw_en or raw_cn or raw_name
                        abbrevs = [a.strip() for a in field_map.get("abbrev", "").split(",") if a.strip()]
                        gran = field_map.get("granularity") or "unknown"
                        parent = field_map.get("parent") or ""
                        cat = field_map.get("category") or "brain_region"
                        lat = field_map.get("laterality") or _guess_laterality(" ".join(vals))
                        conf = float(field_map.get("confidence") or 0) or 0.60
                        src = " | ".join(v for v in vals if v)[:300]
                        en_out = raw_en if raw_en else (name if _is_ascii_only(name) else "")
                        cn_out = raw_cn if raw_cn else (name if not _is_ascii_only(name) else "")
                        _add(en_out, cn_out, abbrevs, gran, parent, cat, lat, conf, src, f"row_{dr['row']}")
            else:
                # No header detected: fall through to cell-chunk processing below
                for dr in data_rows:
                    vals = dr["vals"]
                    for v in vals:
                        v = (v or "").strip()
                        if not v or len(v) > 200:
                            continue
                        entry = _lookup_kb(v) or _partial_kb_match(v)
                        if entry:
                            en, cn, abbrevs, gran, parent, cat = entry
                            _add(en, cn, list(abbrevs), gran, parent, cat,
                                 _guess_laterality(v), 0.80, v, f"row_{dr['row']}")

        # ── 路径1：逐格 table_cell chunk（Excel cell → 精确查 KB）────────────
        cell_chunks = [c for c in chunks if c.get("chunk_type") == "table_cell"]
        para_chunks = [c for c in chunks if c.get("chunk_type") != "table_cell"]

        for ch in cell_chunks[:8000]:
            text = (ch.get("text_content") or "").strip()
            if not text or len(text) > 200:
                continue
            entry = _lookup_kb(text)
            if entry:
                en, cn, abbrevs, gran, parent, cat = entry
                _add(en, cn, list(abbrevs), gran, parent, cat,
                     _guess_laterality(text), 0.92, text, ch.get("chunk_id", ""))
            else:
                entry2 = _partial_kb_match(text)
                if entry2:
                    en, cn, abbrevs, gran, parent, cat = entry2
                    _add(en, cn, list(abbrevs), gran, parent, cat,
                         _guess_laterality(text), 0.78, text, ch.get("chunk_id", ""))

        # ── 路径2：paragraph chunk（文本段落 → 正则扫描内联 region 词）─────────
        for ch in para_chunks[:2000]:
            text = (ch.get("text_content") or "").strip()
            if not text:
                continue
            for m in _REGION_INLINE_RE.finditer(text):
                matched_word = m.group(0)
                entry = _lookup_kb(matched_word)
                if not entry:
                    continue
                en, cn, abbrevs, gran, parent, cat = entry
                _add(en, cn, list(abbrevs), gran, parent, cat,
                     _guess_laterality(text), 0.82, text[:300], ch.get("chunk_id", ""))

        if not rows:
            # 兜底：对整个 raw_text 做一次全量正则扫描
            raw = (file_payload.get("raw_text") or "")[:80000]
            for m in _REGION_INLINE_RE.finditer(raw):
                entry = _lookup_kb(m.group(0))
                if not entry:
                    continue
                en, cn, abbrevs, gran, parent, cat = entry
                ctx = raw[max(0, m.start() - 60): m.end() + 60]
                _add(en, cn, list(abbrevs), gran, parent, cat,
                     _guess_laterality(ctx), 0.65, ctx, "")

        if not rows:
            rows.append(_make_candidate(
                file_id, parsed_document_id, "", file_payload.get("filename", ""),
                "", "", [], "unknown", "", "brain_region", "unknown", 0.3,
            ))
        return rows

    def _extract_by_deepseek(
        self,
        file_payload: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        parsed_document_id: str,
        deepseek_cfg: Dict[str, Any],
        table_rows: Optional[List[Dict[str, Any]]] = None,
    ) -> List[CandidateRegion]:
        # Prefer structured table rows as text (better signal for LLM)
        if table_rows:
            lines = [
                tr.get("joined_text") or " | ".join(str(v) for v in (tr.get("values") or []))
                for tr in table_rows[:200]
            ]
            sample = "\n".join(l for l in lines if l)[:8000]
        else:
            sample = "\n".join((ch.get("text_content") or "")[:300] for ch in chunks[:40])
        if not sample:
            sample = file_payload.get("filename", "")
        prompt = compose_region_file_user_prompt(sample, deepseek_cfg)
        return self._deepseek_prompt_to_regions(
            prompt,
            file_payload,
            parsed_document_id,
            deepseek_cfg,
            extraction_method="deepseek",
            ontology_source="deepseek_extract",
        )

    def _deepseek_prompt_to_regions(
        self,
        prompt: str,
        file_payload: Dict[str, Any],
        parsed_document_id: str,
        deepseek_cfg: Dict[str, Any],
        *,
        extraction_method: str = "deepseek",
        ontology_source: str = "deepseek_extract",
    ) -> List[CandidateRegion]:
        if not deepseek_cfg.get("enabled"):
            raise RuntimeError("deepseek_disabled")
        if not deepseek_cfg.get("api_key"):
            raise RuntimeError("deepseek_api_key_missing")

        url = deepseek_cfg.get("base_url", "https://api.deepseek.com").rstrip("/") + "/v1/chat/completions"
        payload = {
            "model": deepseek_cfg.get("model", "deepseek-chat"),
            "temperature": deepseek_cfg.get("temperature", 0.2),
            "messages": [
                {"role": "system", "content": deepseek_system_content(deepseek_cfg)},
                {"role": "user", "content": prompt},
            ],
        }
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {deepseek_cfg.get('api_key', '')}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
        except error.HTTPError as exc:  # pragma: no cover
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"deepseek_http_{exc.code}:{detail[:300]}") from exc
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"deepseek_request_failed:{exc}") from exc

        msg = self._parse_chat_text(body)
        parsed_rows = self._parse_json_rows(msg)
        out: List[CandidateRegion] = []
        for row in parsed_rows:
            out.append(
                CandidateRegion(
                    id=make_id("cr"),
                    file_id=file_payload.get("file_id", ""),
                    parsed_document_id=parsed_document_id,
                    chunk_id="",
                    source_text=str(row.get("source_text", "")),
                    en_name_candidate=str(row.get("en_name_candidate", "")),
                    cn_name_candidate=str(row.get("cn_name_candidate", "")),
                    alias_candidates=list(row.get("alias_candidates", [])),
                    laterality_candidate=str(row.get("laterality_candidate", "unknown")),
                    region_category_candidate=str(row.get("region_category_candidate", "brain_region")),
                    granularity_candidate=str(row.get("granularity_candidate", "unknown")),
                    parent_region_candidate=str(row.get("parent_region_candidate", "")),
                    ontology_source_candidate=ontology_source,
                    confidence=float(row.get("confidence", 0.7)),
                    extraction_method=extraction_method,
                    llm_model=deepseek_cfg.get("model", ""),
                    status="pending_review",
                    created_at=utc_now_iso(),
                    updated_at=utc_now_iso(),
                )
            )
        if not out:
            raise RuntimeError("deepseek_empty_result")
        return out

    @staticmethod
    def build_region_prompt(mode: str, params: Dict[str, Any]) -> str:
        topic = (params.get("topic") or "脑区").strip()
        species = (params.get("species") or "小鼠").strip()
        granularity = (params.get("granularity") or "major").strip()
        extra = (params.get("extra_instructions") or "").strip()
        _ = mode
        return (
            f"请列出{species}与「{topic}」相关的脑区名称（中英文），粒度参考为{granularity}。"
            "返回JSON数组，每项字段："
            "en_name_candidate,cn_name_candidate,alias_candidates,laterality_candidate,"
            "region_category_candidate,granularity_candidate,parent_region_candidate,confidence,source_text。"
            "granularity_candidate只允许major/sub/allen/unknown。\n"
            f"{extra}"
        )

    @staticmethod
    def build_synthetic_parsed_from_text(text: str, file_id: str) -> Dict[str, Any]:
        pd_id = make_id("pd")
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        chunks: List[Dict[str, Any]] = []
        for i, line in enumerate(lines[:500]):
            chunks.append({"chunk_id": make_id("ch"), "text_content": line, "order": i})
        if not chunks:
            chunks.append({"chunk_id": make_id("ch"), "text_content": (text or "")[:12000], "order": 0})
        doc = {
            "parsed_document_id": pd_id,
            "file_id": file_id,
            "parse_status": "parsed_success",
            "raw_text": (text or "")[:50000],
            "table_rows": [],
        }
        return {"document": doc, "chunks": chunks}

    def run_direct_deepseek_regions(
        self,
        file_payload: Dict[str, Any],
        parsed_document_id: str,
        params: Dict[str, Any],
        deepseek_cfg: Dict[str, Any],
    ) -> List[CandidateRegion]:
        prompt = compose_direct_region_user_prompt(params, deepseek_cfg)
        return self._deepseek_prompt_to_regions(
            prompt,
            file_payload,
            parsed_document_id,
            deepseek_cfg,
            extraction_method="direct_deepseek",
            ontology_source="direct_deepseek",
        )

    @staticmethod
    def _parse_chat_text(body: str) -> str:
        payload = json.loads(body)
        choices = payload.get("choices", [])
        if not choices:
            return "[]"
        content = choices[0].get("message", {}).get("content", "")
        return content or "[]"

    @staticmethod
    def _parse_json_rows(text: str) -> List[Dict[str, Any]]:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.replace("json", "", 1).strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("regions", [])
        if not isinstance(data, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in data:
            if isinstance(row, dict):
                out.append(row)
        return out

    def run_circuit_extraction(
        self,
        file_payload: Dict[str, Any],
        parsed_payload: Dict[str, Any],
        mode: str,
        deepseek_cfg: Dict[str, Any],
        region_candidates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if mode == "deepseek":
            # phase-1 minimal: keep mode tag but reuse deterministic local build
            rows = self._extract_circuit_by_local_rules(file_payload, parsed_payload, region_candidates, extraction_method="deepseek_placeholder")
            return {"method": "deepseek_placeholder", "llm_model": deepseek_cfg.get("model", ""), "candidates": rows}
        rows = self._extract_circuit_by_local_rules(file_payload, parsed_payload, region_candidates, extraction_method="local_rule")
        return {"method": "local_rule", "llm_model": "", "candidates": rows}

    def _extract_circuit_by_local_rules(
        self,
        file_payload: Dict[str, Any],
        parsed_payload: Dict[str, Any],
        region_candidates: List[Dict[str, Any]],
        extraction_method: str,
    ) -> List[CandidateCircuit]:
        parsed_doc = parsed_payload.get("document", {})
        parsed_document_id = parsed_doc.get("parsed_document_id", "")
        reviewed_regions = [r for r in (region_candidates or []) if r.get("status") in {"reviewed", "approved", "staged", "committed"}]
        granularity = "major"
        if reviewed_regions:
            granularity = (reviewed_regions[0].get("granularity_candidate") or "major").strip().lower()
        nodes: List[Dict[str, Any]] = []
        max_nodes = max(1, min(3, len(reviewed_regions)))
        for idx, region in enumerate(reviewed_regions[:max_nodes], start=1):
            nodes.append(
                {
                    "id": make_id("ccn"),
                    "region_id_candidate": (region.get("parent_region_candidate") or "").strip(),
                    "granularity_candidate": (region.get("granularity_candidate") or granularity).strip().lower(),
                    "node_order": idx,
                    "role_label": "relay",
                }
            )
        if not nodes:
            nodes = [
                {
                    "id": make_id("ccn"),
                    "region_id_candidate": "",
                    "granularity_candidate": granularity,
                    "node_order": 1,
                    "role_label": "seed",
                }
            ]

        row = CandidateCircuit(
            id=make_id("cc"),
            file_id=file_payload.get("file_id", ""),
            parsed_document_id=parsed_document_id,
            source_text=(parsed_doc.get("raw_text") or file_payload.get("filename", ""))[:300],
            en_name_candidate=f"Circuit from {file_payload.get('filename', 'file')}",
            cn_name_candidate="",
            alias_candidates=[],
            description_candidate="auto extracted candidate circuit",
            circuit_kind_candidate="inferred",
            loop_type_candidate="inferred",
            cycle_verified_candidate=False,
            confidence_circuit=0.55,
            granularity_candidate=granularity if granularity in {"major", "sub", "allen"} else "major",
            extraction_method=extraction_method,
            llm_model="",
            status="pending_review",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        payload = row.__dict__.copy()
        payload["nodes"] = nodes
        return [payload]

    def run_connection_extraction(
        self,
        file_payload: Dict[str, Any],
        parsed_payload: Dict[str, Any],
        mode: str,
        deepseek_cfg: Dict[str, Any],
        region_candidates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if mode == "deepseek":
            rows = self._extract_connection_by_local_rules(
                file_payload,
                parsed_payload,
                region_candidates,
                extraction_method="deepseek_placeholder",
                llm_model=deepseek_cfg.get("model", ""),
            )
            return {"method": "deepseek_placeholder", "llm_model": deepseek_cfg.get("model", ""), "candidates": rows}
        rows = self._extract_connection_by_local_rules(
            file_payload,
            parsed_payload,
            region_candidates,
            extraction_method="local_rule",
            llm_model="",
        )
        return {"method": "local_rule", "llm_model": "", "candidates": rows}

    def _extract_connection_by_local_rules(
        self,
        file_payload: Dict[str, Any],
        parsed_payload: Dict[str, Any],
        region_candidates: List[Dict[str, Any]],
        extraction_method: str,
        llm_model: str,
    ) -> List[Dict[str, Any]]:
        parsed_doc = parsed_payload.get("document", {})
        parsed_document_id = parsed_doc.get("parsed_document_id", "")
        reviewed_regions = [r for r in (region_candidates or []) if r.get("status") in {"reviewed", "approved", "staged", "committed"}]
        granularity = "major"
        if reviewed_regions:
            granularity = (reviewed_regions[0].get("granularity_candidate") or "major").strip().lower()
            if granularity not in {"major", "sub", "allen"}:
                granularity = "major"

        src_ref = ""
        tgt_ref = ""
        for region in reviewed_regions:
            rid = (region.get("parent_region_candidate") or "").strip()
            if not src_ref and rid:
                src_ref = rid
            elif not tgt_ref and rid and rid != src_ref:
                tgt_ref = rid
            if src_ref and tgt_ref:
                break

        row = CandidateConnection(
            id=make_id("ccn"),
            file_id=file_payload.get("file_id", ""),
            parsed_document_id=parsed_document_id,
            source_text=(parsed_doc.get("raw_text") or file_payload.get("filename", ""))[:300],
            en_name_candidate=f"Connection from {file_payload.get('filename', 'file')}",
            cn_name_candidate="",
            alias_candidates=[],
            description_candidate="auto extracted candidate connection",
            granularity_candidate=granularity,
            connection_modality_candidate="unknown",
            source_region_ref_candidate=src_ref,
            target_region_ref_candidate=tgt_ref,
            confidence=0.55,
            direction_label="bidirectional",
            extraction_method=extraction_method,
            llm_model=llm_model,
            status="pending_review",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        return [row.__dict__.copy()]
