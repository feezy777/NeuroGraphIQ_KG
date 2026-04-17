from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request

from ..common.id_utils import make_id, make_region_candidate_id
from ..common.models import CandidateCircuit, CandidateConnection, CandidateRegion, utc_now_iso
from ..config.runtime_config import clamp_deepseek_max_tokens
from ..validation.ontology_rules import (
    apply_ontology_binding_gate_to_review_note,
    load_ruleset_dict,
    merge_ontology_binding_into_review_note,
    resolve_term_binding,
)
from .region_postprocess_v2 import derive_region_extract_status


# ---------------------------------------------------------------------------
# DeepSeek「直接生成」粗颗粒度权威参考（major）——默认面向人类知识图谱
# 以人类大体解剖与临床常用分区为主（额/顶/颞/枕叶、岛叶、扣带回、边缘系统、基底节、
# 丘脑/下丘脑、脑干、小脑等，命名可对齐 Terminologia Anatomica 与本科教材）；
# Allen / Paxinos 图谱作跨物种对照。granularity_candidate 应填 major。
# ---------------------------------------------------------------------------
_DIRECT_COARSE_MAJOR: List[Tuple[str, str, str]] = [
    ("Frontal lobe", "额叶", "cortex"),
    ("Parietal lobe", "顶叶", "cortex"),
    ("Temporal lobe", "颞叶", "cortex"),
    ("Occipital lobe", "枕叶", "cortex"),
    ("Insular cortex", "岛叶皮层", "cortex"),
    ("Cingulate gyrus", "扣带回", "cortex"),
    ("Hippocampal formation", "海马结构", "hippocampal"),
    ("Amygdala", "杏仁核", "amygdala"),
    ("Dorsal striatum (caudate and putamen)", "背侧纹状体（尾状核与壳核）", "basal_ganglia"),
    ("Nucleus accumbens", "伏隔核（腹侧纹状体）", "basal_ganglia"),
    ("Globus pallidus", "苍白球", "basal_ganglia"),
    ("Subthalamic nucleus", "丘脑底核", "basal_ganglia"),
    ("Thalamus", "丘脑", "thalamus"),
    ("Hypothalamus", "下丘脑", "hypothalamus"),
    ("Epithalamus (habenula)", "上丘脑（缰核）", "thalamus"),
    ("Substantia nigra", "黑质", "brainstem"),
    ("Ventral tegmental area", "腹侧被盖区", "brainstem"),
    ("Superior colliculus", "上丘", "brainstem"),
    ("Inferior colliculus", "下丘", "brainstem"),
    ("Periaqueductal gray", "中脑导水管周围灰质", "brainstem"),
    ("Pons", "脑桥", "brainstem"),
    ("Medulla oblongata", "延髓", "brainstem"),
    ("Cerebellum", "小脑", "cerebellum"),
    ("Main olfactory bulb", "主嗅球", "olfactory"),
    ("Septal nuclei", "隔核", "septal"),
    ("Mammillary bodies", "乳头体", "hypothalamus"),
    ("Piriform cortex", "梨状皮层", "olfactory"),
    ("Entorhinal cortex", "内嗅皮层", "hippocampal"),
]


def _is_rodent_species(species: str) -> bool:
    s = (species or "").strip().lower()
    return any(x in s for x in ("鼠", "mouse", "rat", "rodent", "hamster", "豚鼠"))


def _direct_major_atlas_prompt_block(species: str) -> str:
    """注入 user 消息：粗颗粒度权威清单 + 物种说明。"""
    lines = [
        f"{i}. {en} / {cn}（region_category_candidate 建议: {cat}）"
        for i, (en, cn, cat) in enumerate(_DIRECT_COARSE_MAJOR, 1)
    ]
    rodent = _is_rodent_species(species)
    species_note = ""
    if rodent:
        species_note = (
            "【物种注·啮齿类】四叶划分在人类解剖中最常用；啮齿类新皮质在图谱中常统称 Isocortex。"
            "若你认为四叶不便一一对应，可额外增加一条 en_name_candidate=Isocortex / 新皮质，"
            "并在 alias_candidates 中注明与感觉/运动/视觉等粗功能模块相关的常用缩写，"
            "但四叶条目仍应尽量给出（可作功能同源近似），不得整张表只输出皮层一条替代全部。\n\n"
        )
    else:
        species_note = (
            "【物种注·人类（默认）】本清单按人类大体脑区分区列出，适用于知识图谱顶层实体；"
            "四叶模型与皮层下/脑干/小脑分区与临床及教材常用命名一致，请逐项给出中英文标准名。\n\n"
        )
    return (
        "\n【粗颗粒度·权威大体分区】下列以人类神经解剖学常用「大分区」为主（中英文对照见下），"
        "并辅以图谱学通用结构名；用于知识图谱时建议与顶层 ontology 节点对齐。\n"
        "请**按清单逐项**各输出 **1 条** regions 元素（同一解剖实体不要重复两条）；"
        "granularity_candidate 一律填 **major**；laterality_candidate 无侧化信息时填 unknown。\n"
        "若某物种确缺某结构，可省略该条或输出最近似同源结构并在 confidence 中给较低分、source_text 简短说明。\n\n"
        f"{species_note}"
        + "\n".join(lines)
        + f"\n\n【数量】regions 数组长度应 **≥ {max(24, len(_DIRECT_COARSE_MAJOR) - 4)}**（目标约 **{len(_DIRECT_COARSE_MAJOR)}** 条粗分区）；"
        "明显偏少视为不完整输出。\n"
    )


def _should_inject_direct_major_atlas(granularity: str) -> bool:
    g = (granularity or "").strip().lower()
    if not g:
        return True
    if g in ("major", "coarse", "macro", "large", "rough"):
        return True
    if "粗" in granularity:
        return True
    return False


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
    *,
    ontology_ruleset: Optional[Dict[str, Any]] = None,
    ontology_bind_on: bool = False,
    ontology_require_binding: bool = False,
    batch_index: int = 0,
) -> CandidateRegion:
    lat = (laterality or "").strip() or "unknown"
    gran = (granularity or "").strip().lower() or "unknown"
    if gran not in {"major", "sub", "allen", "unknown"}:
        gran = "unknown"
    cat = (category or "").strip() or "brain_region"
    _en = (en or "").strip()
    _cn = (cn or "").strip()
    _conf = float(confidence)
    binding: Dict[str, Any] = {}
    if ontology_bind_on and ontology_ruleset is not None:
        binding = resolve_term_binding(ontology_ruleset, _en, _cn)
    term_key = str(binding.get("term_key") or "") if binding else ""
    canonical = str(binding.get("canonical") or "") if binding else ""
    _estatus = derive_region_extract_status(
        extraction_method="local_rule",
        match_type="exact" if _conf >= 0.75 else "fuzzy",
        confidence=_conf,
        en_name=_en,
        cn_name=_cn,
    )
    _note = json.dumps(
        {"local_rule": {"extract_status": _estatus, "confidence": _conf}},
        ensure_ascii=False,
    )
    if ontology_bind_on and ontology_ruleset is not None:
        _note = merge_ontology_binding_into_review_note(_note, binding)
    _note = apply_ontology_binding_gate_to_review_note(
        _note,
        bind_on_extract=ontology_bind_on,
        require_binding_for_confirmed=ontology_require_binding,
    )
    _src = (source_text or "")[:400]
    cid = make_region_candidate_id(
        file_id=file_id,
        en_name=_en,
        cn_name=_cn,
        source_text=_src,
        batch_index=batch_index,
        term_key=term_key,
        canonical=canonical,
    )
    return CandidateRegion(
        id=cid,
        file_id=file_id,
        parsed_document_id=parsed_document_id,
        chunk_id=chunk_id,
        source_text=_src,
        en_name_candidate=_en,
        cn_name_candidate=_cn,
        alias_candidates=[a for a in abbrevs if a],
        laterality_candidate=lat,
        region_category_candidate=cat,
        granularity_candidate=gran,
        parent_region_candidate=(parent or "").strip(),
        ontology_source_candidate="local_rule_kb",
        confidence=_conf,
        extraction_method="local_rule",
        llm_model="",
        status="pending_review",
        review_note=_note,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )


def _enrich_names_from_kb(en: str, cn: str) -> tuple[str, str, list[str]]:
    """若仅有一侧语言，尝试用内置 KB 补全另一侧与标准别名。"""
    en = (en or "").strip()
    cn = (cn or "").strip()
    entry = _lookup_kb(en) or _lookup_kb(cn) or (_partial_kb_match(en) if en else None) or (_partial_kb_match(cn) if cn else None)
    if not entry:
        return en, cn, []
    kb_en, kb_cn, kb_abbrevs, _, _, _ = entry
    out_en = en or kb_en
    out_cn = cn or kb_cn
    return out_en, out_cn, list(kb_abbrevs)


def _normalize_laterality(val: Any) -> str:
    s = str(val or "").strip().lower()
    if s in {"", "na", "n/a", "none"}:
        return "unknown"
    if s in {"left", "right", "bilateral", "midline", "unknown"}:
        return s
    if "左" in s or s in {"l", "lhs"}:
        return "left"
    if "右" in s or s in {"r", "rhs"}:
        return "right"
    if "双" in s or "两侧" in s:
        return "bilateral"
    if "中" in s and "线" in s:
        return "midline"
    return "unknown"


def _normalize_granularity(val: Any) -> str:
    s = str(val or "").strip().lower()
    if s in {"major", "sub", "allen", "unknown"}:
        return s
    if s in {"", "na"}:
        return "unknown"
    return "unknown"


def _coerce_alias_list(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        parts = re.split(r"[,;，；\s]+", val)
        return [p.strip() for p in parts if p.strip()]
    return [str(val).strip()] if str(val).strip() else []


def _extract_regions_array_objects(raw: str) -> List[Dict[str, Any]]:
    """当模型输出被 max_tokens 截断导致整体 JSON 非法时，从 ``regions`` 数组中扫描**已闭合**的对象并逐个 json.loads。

    忽略字符串字面量内的 ``{`` ``}``，避免误切分。
    """
    m = re.search(r'"regions"\s*:\s*\[', raw, re.IGNORECASE)
    if not m:
        return []
    items: List[Dict[str, Any]] = []
    depth = 0
    start: Optional[int] = None
    in_str = False
    esc = False
    j = m.end()
    n = len(raw)
    while j < n:
        c = raw[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            j += 1
            continue
        if c == '"':
            in_str = True
            j += 1
            continue
        if c == "{":
            if depth == 0:
                start = j
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                chunk = raw[start : j + 1]
                try:
                    obj = json.loads(chunk)
                    if isinstance(obj, dict):
                        items.append(obj)
                except json.JSONDecodeError:
                    pass
                start = None
        elif c == "]" and depth == 0:
            break
        j += 1
    return items


def normalize_region_llm_row(
    row: Dict[str, Any],
    *,
    ontology_default: str,
    enrich_from_kb: bool = True,
) -> Dict[str, Any]:
    """将模型返回的任意键名归一为工作台统一中间态（与 CandidateRegion / 入库字段对应）。"""
    r = {k: v for k, v in row.items() if isinstance(k, str)}
    en = (
        r.get("en_name_candidate")
        or r.get("en_name")
        or r.get("english_name")
        or r.get("name_en")
        or r.get("en")
        or r.get("name_english")
        or r.get("name")
        or ""
    )
    cn = (
        r.get("cn_name_candidate")
        or r.get("cn_name")
        or r.get("chinese_name")
        or r.get("name_cn")
        or r.get("cn")
        or r.get("name_chinese")
        or r.get("zh_name")
        or r.get("name_zh")
        or ""
    )
    en, cn = str(en).strip(), str(cn).strip()
    aliases = _coerce_alias_list(
        r.get("alias_candidates")
        if r.get("alias_candidates") is not None
        else r.get("aliases") or r.get("abbreviations") or r.get("abbr")
    )
    ab1 = r.get("abbreviation")
    if isinstance(ab1, str) and ab1.strip():
        aliases = list(dict.fromkeys(list(aliases) + [ab1.strip()]))
    later = _normalize_laterality(
        r.get("laterality_candidate") if r.get("laterality_candidate") is not None else r.get("laterality")
    )
    cat = str(
        r.get("region_category_candidate")
        if r.get("region_category_candidate") is not None
        else r.get("region_category") or r.get("category") or "brain_region"
    ).strip() or "brain_region"
    gran = _normalize_granularity(
        r.get("granularity_candidate") if r.get("granularity_candidate") is not None else r.get("granularity")
    )
    parent = str(
        r.get("parent_region_candidate")
        if r.get("parent_region_candidate") is not None
        else r.get("parent_region") or r.get("parent") or ""
    ).strip()
    onto = str(
        r.get("ontology_source_candidate")
        if r.get("ontology_source_candidate") is not None
        else r.get("ontology_source") or ontology_default
    ).strip() or ontology_default
    try:
        conf = float(r.get("confidence", 0.7))
    except (TypeError, ValueError):
        conf = 0.7
    conf = max(0.0, min(1.0, conf))
    src = str(
        r.get("source_text") if r.get("source_text") is not None else r.get("evidence") or r.get("quote") or ""
    ).strip()
    if enrich_from_kb:
        en2, cn2, kb_aliases = _enrich_names_from_kb(en, cn)
        merged_aliases = list(dict.fromkeys(aliases + kb_aliases))
    else:
        en2, cn2 = en, cn
        merged_aliases = list(dict.fromkeys(aliases))
    return {
        "en_name_candidate": en2,
        "cn_name_candidate": cn2,
        "alias_candidates": merged_aliases,
        "laterality_candidate": later,
        "region_category_candidate": cat,
        "granularity_candidate": gran,
        "parent_region_candidate": parent,
        "ontology_source_candidate": onto,
        "confidence": conf,
        "source_text": (src or "")[:400],
    }


# DeepSeek 脑区抽取：规划好的 user prompt（需含 {TEXT}）
# 三种方式（文件/文本/直接生成）最终都落同一套 CandidateRegion 中间态字段。
REGION_USER_PROMPT_PRESETS: Dict[str, str] = {
    "default": (
        "你是脑区知识图谱抽取专家。请从以下文本中**完整、穷尽**抽取所有脑区实体。\n"
        "【表格/多行】若 TEXT 为带「行N:」前缀的表格行或多行列表：每一行对应**独立**解剖条目，"
        "`regions` 中条目数应**不少于**本批有效行数（除非某行明确无脑区）；"
        "禁止将不同行合并为一条；仅当**同一行内**出现同义重复才可合并。\n"
        "【非表格】同一解剖结构的不同表述可合并为一条。\n"
        "输出必须是 **一个 JSON 对象**，且**仅含一个键** `regions`，值为数组；数组元素对象**仅使用下列键名**"
        "（与数据库候选/入库 staging 对齐，勿发明新键）：\n"
        "  en_name_candidate       string  标准英文解剖名（拉丁/英文文献常用）；无则 \"\"\n"
        "  cn_name_candidate       string  中文通用译名；无则 \"\"\n"
        "  alias_candidates        array   缩写与其它别名，如 [\"PFC\",\"mPFC\"]\n"
        "  laterality_candidate    string  仅允许: left | right | bilateral | midline | unknown\n"
        "  region_category_candidate string 解剖大类/分区标签，如 cortex | hippocampal | amygdala | thalamus | brainstem | cerebellum | other | brain_region\n"
        "  granularity_candidate   string  仅允许: major | sub | allen | unknown\n"
        "  parent_region_candidate string  父级脑区英文名；无则 \"\"\n"
        "  ontology_source_candidate string 固定填 \"deepseek_extract\"（除非文本另有明确本体来源可写简短标识）\n"
        "  confidence              number  0~1\n"
        "  source_text             string  支持该条目的原文短语（≤120字）\n"
        "要求：在能确定时**同时给出中英文**；缩写放入 alias_candidates。\n"
        "只输出 JSON 对象本身，形如 {\"regions\":[...]} ，不要 Markdown 代码围栏，不要解释文字。\n\n"
        "TEXT:\n{TEXT}"
    ),
    "detailed": (
        "你是神经解剖与脑图谱专家。请从以下文本中「穷尽」抽取脑区候选：含中英文全称、常见缩写、层级（父区）与侧化。\n"
        "合并同义重复项；对不确定侧化用 unknown。\n"
        "输出格式：与 default 预设**完全相同**（`regions` 数组 + 相同键名与取值约束）。\n\n"
        "TEXT:\n{TEXT}"
    ),
    "minimal": (
        "从下列文本抽取脑区，只输出 JSON 对象，且仅含键 `regions`，值为数组；数组元素键名固定为："
        "en_name_candidate,cn_name_candidate,alias_candidates,laterality_candidate,"
        "region_category_candidate,granularity_candidate,parent_region_candidate,"
        "ontology_source_candidate,confidence,source_text。"
        "granularity_candidate ∈ major/sub/allen/unknown；laterality_candidate ∈ left/right/bilateral/midline/unknown；"
        "ontology_source_candidate 填 deepseek_extract。\n\nTEXT:\n{TEXT}"
    ),
}

DEFAULT_DEEPSEEK_SYSTEM = (
    "你是脑区知识图谱抽取助手。你必须只输出一个 JSON 对象，且仅含键 \"regions\"；"
    "其值为数组，数组元素字段名固定为："
    "en_name_candidate, cn_name_candidate, alias_candidates, laterality_candidate, "
    "region_category_candidate, granularity_candidate, parent_region_candidate, "
    "ontology_source_candidate, confidence, source_text。"
    "不要输出 Markdown 代码围栏或任何非 JSON 内容。"
)

# 文件表格 DeepSeek：每批用户文本字符上限（与 deepseek_batch_max_chars 配置一致；默认可整表）
DEEPSEEK_TABLE_BATCH_MAX_CHARS = 500000
# 非表格 chunk 文本分批
DEEPSEEK_CHUNK_BATCH_MAX_CHARS = 500000


def _table_row_to_line(tr: Dict[str, Any]) -> str:
    raw = tr.get("joined_text") or " | ".join(str(v) for v in (tr.get("values") or []))
    return (raw or "").strip()


def _batch_joined_lines(lines: List[str], max_chars: int) -> List[str]:
    """按字符预算将多行文本切成若干批，顺序遍历整张表。"""
    if not lines:
        return []
    if max_chars < 500:
        max_chars = 500
    batches: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for line in lines:
        if len(line) > max_chars:
            if cur:
                batches.append("\n".join(cur))
                cur = []
                cur_len = 0
            for i in range(0, len(line), max_chars):
                batches.append(line[i : i + max_chars])
            continue
        add_len = len(line) if not cur else 1 + len(line)
        if cur and cur_len + add_len > max_chars:
            batches.append("\n".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += add_len
    if cur:
        batches.append("\n".join(cur))
    return batches


def _batch_table_lines(lines: List[str], max_chars: int, rows_per_batch: int) -> List[str]:
    """表格行分批：rows_per_batch>0 时先按固定行数切段，再对每段做字符预算切分（防单行超长）。"""
    if not lines:
        return []
    if rows_per_batch <= 0:
        return _batch_joined_lines(lines, max_chars)
    if max_chars < 500:
        max_chars = 500
    batches: List[str] = []
    for i in range(0, len(lines), rows_per_batch):
        chunk = lines[i : i + rows_per_batch]
        batches.extend(_batch_joined_lines(chunk, max_chars))
    return batches


def _merge_deepseek_region_candidates(
    dst: CandidateRegion,
    src: CandidateRegion,
    *,
    bind_on_extract: bool = True,
    require_binding_for_confirmed: bool = True,
) -> None:
    """多批次合并去重时保留各批次的溯源与证据，不修改模型给出的中英文名。"""
    def _loads(rn: str) -> Dict[str, Any]:
        if not rn:
            return {}
        try:
            return json.loads(rn) if isinstance(rn, str) else {}
        except Exception:
            return {"_unparsed_review_note": rn}

    def _dumps(d: Dict[str, Any]) -> str:
        return json.dumps(d, ensure_ascii=False)

    a = _loads(dst.review_note)
    b = _loads(src.review_note)
    da = a.get("deepseek") if isinstance(a.get("deepseek"), dict) else {}
    db = b.get("deepseek") if isinstance(b.get("deepseek"), dict) else {}
    ba = da.get("batches", [])
    bb = db.get("batches", [])
    if not isinstance(ba, list):
        ba = []
    if not isinstance(bb, list):
        bb = []
    da["batches"] = ba + bb
    a["deepseek"] = da
    ob_a = a.get("ontology_binding") if isinstance(a.get("ontology_binding"), dict) else {}
    ob_b = b.get("ontology_binding") if isinstance(b.get("ontology_binding"), dict) else {}
    if (ob_b.get("term_key") or "").strip():
        a["ontology_binding"] = ob_b
    elif (ob_a.get("term_key") or "").strip():
        a["ontology_binding"] = ob_a
    elif ob_b:
        a["ontology_binding"] = ob_b
    elif ob_a:
        a["ontology_binding"] = ob_a
    dst.review_note = _dumps(a)
    dst.review_note = apply_ontology_binding_gate_to_review_note(
        dst.review_note,
        bind_on_extract=bind_on_extract,
        require_binding_for_confirmed=require_binding_for_confirmed,
    )
    s1 = (dst.source_text or "").strip()
    s2 = (src.source_text or "").strip()
    if s2 and s2 not in s1:
        sep = " | " if s1 else ""
        dst.source_text = (s1 + sep + s2)[:400]


def _network_error_hint(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "unexpected_eof_while_reading" in low or "ssl" in low:
        return "hint=ssl_handshake_or_proxy_issue"
    if "timed out" in low or "timeout" in low:
        return "hint=request_timeout"
    if "name or service not known" in low or "nodename nor servname provided" in low:
        return "hint=dns_resolution_failed"
    return "hint=network_or_transport_error"


def compose_region_file_user_prompt(sample_text: str, cfg: Dict[str, Any]) -> str:
    """根据配置组合文件/文本脑区抽取的 user 消息正文。"""
    custom = (cfg.get("region_user_prompt_template") or "").strip()
    if custom:
        body = custom.replace("{TEXT}", sample_text)
        if cfg.get("force_json_output", True) and "regions" not in body:
            body += (
                "\n\n【输出约束】必须使用 JSON 对象，且仅含键 \"regions\"，值为脑区对象数组；"
                "不要输出裸数组，不要 Markdown 围栏。"
            )
    else:
        pid = (cfg.get("region_prompt_preset") or "default").strip()
        template = REGION_USER_PROMPT_PRESETS.get(pid, REGION_USER_PROMPT_PRESETS["default"])
        body = template.replace("{TEXT}", sample_text)
    prefix = (cfg.get("user_prompt_prefix") or "").strip()
    if prefix:
        body = prefix + "\n\n" + body
    return body


def compose_direct_region_user_prompt(params: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    """根据配置组合「直接生成」脑区的 user 消息；模板可用占位符 TOPIC/SPECIES/GRANULARITY/EXTRA/ATLAS。"""
    topic = (params.get("topic") or "脑区").strip()
    species = (params.get("species") or "人类").strip()
    granularity = (params.get("granularity") or "major").strip()
    extra = (params.get("extra_instructions") or "").strip()
    atlas = _direct_major_atlas_prompt_block(species) if _should_inject_direct_major_atlas(granularity) else ""
    custom = (cfg.get("direct_region_user_prompt_template") or "").strip()
    if custom:
        body = (
            custom.replace("{TOPIC}", topic)
            .replace("{SPECIES}", species)
            .replace("{GRANULARITY}", granularity)
            .replace("{EXTRA}", extra)
            .replace("{ATLAS}", atlas)
        )
        if "{ATLAS}" not in custom and atlas:
            body += atlas
        if cfg.get("force_json_output", True) and "regions" not in body:
            body += (
                "\n\n【输出约束】必须使用 JSON 对象，且仅含键 \"regions\"，值为脑区对象数组；"
                "不要输出裸数组，不要 Markdown 围栏。"
            )
        return body
    pid = (cfg.get("direct_region_prompt_preset") or "default").strip()
    if pid == "detailed":
        body = (
            f"请系统、完整地列出{species}与「{topic}」相关的脑区（中英文标准名），粒度参考为{granularity}。"
            "需兼顾皮层、皮层下、脑干、小脑等常见分区；缩写放入 alias_candidates。"
            "输出 JSON 对象，且仅含键 \"regions\"，值为数组；数组元素键名固定为："
            "en_name_candidate,cn_name_candidate,alias_candidates,laterality_candidate,"
            "region_category_candidate,granularity_candidate,parent_region_candidate,"
            "ontology_source_candidate,confidence,source_text。"
            "granularity_candidate 仅 major/sub/allen/unknown；laterality_candidate 仅 left/right/bilateral/midline/unknown；"
            "ontology_source_candidate 填 direct_deepseek。\n"
            f"{extra}"
        )
        return body + atlas if atlas else body
    if pid == "minimal":
        body = (
            f"列出{species}与「{topic}」相关的脑区（粒度 {granularity}）。"
            "返回 JSON 对象，且仅含键 \"regions\"，值为数组；数组元素字段："
            "en_name_candidate,cn_name_candidate,alias_candidates,laterality_candidate,"
            "region_category_candidate,granularity_candidate,parent_region_candidate,"
            "ontology_source_candidate,confidence,source_text。"
            "ontology_source_candidate 填 direct_deepseek。\n"
            f"{extra}"
        )
        return body + atlas if atlas else body
    base = ExtractionService.build_region_prompt("direct_generate", params)
    return base + atlas if atlas else base


_JSON_INSTRUCTION_SUFFIX = (
    "\n\n【输出约束 / Output constraint】"
    "你必须只输出一个合法的 JSON 对象，且仅含键 \"regions\"，值为脑区对象数组。"
    "严禁输出任何 Markdown 代码围栏或非 JSON 内容。"
    " You MUST output valid JSON only."
)


def deepseek_system_content(cfg: Dict[str, Any]) -> str:
    """当 force_json_output 开启时，保证 system_prompt 中含有 'json' 关键字（DeepSeek API 强制要求）。"""
    s = (cfg.get("system_prompt") or "").strip()
    base = s if s else DEFAULT_DEEPSEEK_SYSTEM
    if cfg.get("force_json_output", True):
        if "json" not in base.lower():
            base = base + _JSON_INSTRUCTION_SUFFIX
    return base


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
        *,
        moonshot_cfg: Optional[Dict[str, Any]] = None,
        pipeline_config: Optional[Dict[str, Any]] = None,
        root_dir: Optional[str] = None,
        log_emit: Optional[Any] = None,
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

        pc = pipeline_config or {}
        moonshot_cfg = moonshot_cfg or {}
        # v2 仅用于「本地高召回 + 规则/后处理」；若用户选择大模型分批抽取，必须走下方 API，
        # 否则会出现 extraction_method=region_v2_deepseek 但实际未调用 API、仅靠 KB 模糊匹配的假结果。
        v2_on = bool(pc.get("region_extraction_v2", {}).get("enabled")) and bool(root_dir)
        if v2_on and mode not in ("deepseek", "kimi", "multi"):
            from .region_pipeline_v2 import run_region_extraction_v2

            return run_region_extraction_v2(
                fp_with_raw,
                parsed_payload,
                mode,
                deepseek_cfg,
                root_dir=root_dir,
                pipeline_config=pc,
                log_emit=log_emit,
            )
        if v2_on and mode == "deepseek" and log_emit:
            try:
                log_emit(
                    "[REGION_V2] skipped_for_deepseek",
                    {"reason": "region_extraction_v2 is local-only; DeepSeek mode uses batched API extraction"},
                )
            except Exception:
                pass

        if mode == "deepseek":
            # 原则：DeepSeek 失败时不降级本地规则，直接抛出明确失败原因。
            candidates, batch_summary = self._extract_by_deepseek(
                fp_with_raw,
                chunks,
                parsed_document_id,
                deepseek_cfg,
                table_rows=table_rows,
                log_emit=log_emit,
                pipeline_config=pc,
                root_dir=root_dir,
            )
            return {
                "method": "deepseek",
                "llm_model": deepseek_cfg.get("model", ""),
                "candidates": candidates,
                "deepseek_batch_summary": batch_summary,
            }

        if mode == "kimi":
            ms = dict(moonshot_cfg)
            if not ms.get("api_key"):
                raise RuntimeError("moonshot_api_key_missing")
            ms.setdefault("enabled", True)
            ms.setdefault("base_url", "https://api.moonshot.cn")
            ms.setdefault("model", "moonshot-v1-8k")
            ms["force_json_output"] = False
            candidates, batch_summary = self._extract_by_deepseek(
                fp_with_raw,
                chunks,
                parsed_document_id,
                ms,
                table_rows=table_rows,
                log_emit=log_emit,
                pipeline_config=pc,
                root_dir=root_dir,
                error_prefix="kimi",
                extraction_method="kimi",
                ontology_source="kimi_extract",
                log_emit_prefix="[KIMI]",
            )
            return {
                "method": "kimi",
                "llm_model": ms.get("model", ""),
                "candidates": candidates,
                "moonshot_batch_summary": batch_summary,
            }

        if mode == "multi":
            if not deepseek_cfg.get("api_key"):
                raise RuntimeError("deepseek_api_key_missing")
            if not moonshot_cfg.get("api_key"):
                raise RuntimeError("moonshot_api_key_missing")
            ms = dict(moonshot_cfg)
            ms.setdefault("enabled", True)
            ms.setdefault("base_url", "https://api.moonshot.cn")
            ms.setdefault("model", "moonshot-v1-8k")
            ms["force_json_output"] = False
            km, km_sum = self._extract_by_deepseek(
                fp_with_raw,
                chunks,
                parsed_document_id,
                ms,
                table_rows=table_rows,
                log_emit=log_emit,
                pipeline_config=pc,
                root_dir=root_dir,
                error_prefix="kimi",
                extraction_method="kimi",
                ontology_source="kimi_extract",
                log_emit_prefix="[KIMI]",
            )
            ds, ds_sum = self._extract_by_deepseek(
                fp_with_raw,
                chunks,
                parsed_document_id,
                deepseek_cfg,
                table_rows=table_rows,
                log_emit=log_emit,
                pipeline_config=pc,
                root_dir=root_dir,
                error_prefix="deepseek",
                extraction_method="deepseek",
                ontology_source="deepseek_extract",
                log_emit_prefix="[DEEPSEEK]",
            )
            candidates = self._merge_region_candidate_lists(km, ds)
            return {
                "method": "multi",
                "llm_model": f"{ms.get('model', '')}+{deepseek_cfg.get('model', '')}",
                "candidates": candidates,
                "deepseek_batch_summary": ds_sum,
                "moonshot_batch_summary": km_sum,
            }

        candidates = self._extract_by_local_rules(
            fp_with_raw,
            chunks,
            parsed_document_id,
            table_rows=table_rows,
            pipeline_config=pc,
            root_dir=root_dir,
        )
        return {"method": "local_rule", "llm_model": "", "candidates": candidates}

    def _extract_by_local_rules(
        self,
        file_payload: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        parsed_document_id: str,
        table_rows: Optional[List[Dict[str, Any]]] = None,
        pipeline_config: Optional[Dict[str, Any]] = None,
        root_dir: Optional[str] = None,
    ) -> List[CandidateRegion]:
        file_id = file_payload.get("file_id", "")
        rows: List[CandidateRegion] = []
        seen: set = set()
        orc = (pipeline_config or {}).get("ontology_rules") or {}
        ontology_bind_on = bool(orc.get("bind_on_extract", True))
        ontology_require_binding = bool(orc.get("require_binding_for_confirmed", True))
        ontology_ruleset: Optional[Dict[str, Any]] = None
        if ontology_bind_on and root_dir:
            rules_path = str(orc.get("path") or "artifacts/ontology/ruleset.json").replace("\\", "/")
            ontology_ruleset, _ = load_ruleset_dict(root_dir, rules_path)

        def _add(en: str, cn: str, abbrevs: list, gran: str, parent: str, cat: str,
                 lat: str, conf: float, src: str, cid: str) -> None:
            key = (en.strip().lower() if en else cn.strip().lower() if cn else "")
            if not key or key in seen:
                return
            seen.add(key)
            rows.append(_make_candidate(
                file_id, parsed_document_id, cid, src,
                en, cn, abbrevs, gran, parent, cat, lat, conf,
                ontology_ruleset=ontology_ruleset,
                ontology_bind_on=ontology_bind_on,
                ontology_require_binding=ontology_require_binding,
                batch_index=len(rows),
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
                ontology_ruleset=ontology_ruleset,
                ontology_bind_on=ontology_bind_on,
                ontology_require_binding=ontology_require_binding,
                batch_index=0,
            ))
        return rows

    def _extract_by_deepseek(
        self,
        file_payload: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        parsed_document_id: str,
        deepseek_cfg: Dict[str, Any],
        table_rows: Optional[List[Dict[str, Any]]] = None,
        log_emit: Optional[Any] = None,
        pipeline_config: Optional[Dict[str, Any]] = None,
        root_dir: Optional[str] = None,
        *,
        error_prefix: str = "deepseek",
        extraction_method: str = "deepseek",
        ontology_source: str = "deepseek_extract",
        log_emit_prefix: str = "[DEEPSEEK]",
    ) -> Tuple[List[CandidateRegion], Dict[str, Any]]:
        """整表遍历：按行顺序分批调用模型，合并去重，避免单次截断导致失败或漏抽。"""
        max_chars = int(deepseek_cfg.get("deepseek_batch_max_chars", DEEPSEEK_TABLE_BATCH_MAX_CHARS) or DEEPSEEK_TABLE_BATCH_MAX_CHARS)
        if max_chars < 800:
            max_chars = 800
        rows_per_batch = int(deepseek_cfg.get("deepseek_rows_per_batch", 0) or 0)

        batches_text: List[str] = []
        if table_rows:
            lines: List[str] = []
            for ri, tr in enumerate(table_rows):
                raw = _table_row_to_line(tr)
                if not raw:
                    continue
                lines.append(f"行{ri + 1}\t{raw}")
            batches_text = _batch_table_lines(lines, max_chars, rows_per_batch)
        if not batches_text and chunks:
            chunk_lines = []
            for ch in chunks:
                t = (ch.get("text_content") or "").strip()
                if t:
                    chunk_lines.append(t[:4000])
            batches_text = _batch_joined_lines(chunk_lines, max_chars)
        if not batches_text:
            raw = (file_payload.get("raw_text") or "").strip()
            if raw:
                raw_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                batches_text = _batch_joined_lines(raw_lines, max_chars)
        if not batches_text:
            raise RuntimeError(
                f"{error_prefix}_no_input_content: 无 table_rows、无 chunk 正文、无 raw_text，无法调用模型做真实抽取。"
            )

        orc_merge = (pipeline_config or {}).get("ontology_rules") or {}
        merge_bind_on = bool(orc_merge.get("bind_on_extract", True))
        merge_require_binding = bool(orc_merge.get("require_binding_for_confirmed", True))

        merged: List[CandidateRegion] = []
        merged_by_key: Dict[str, CandidateRegion] = {}
        merge_order: List[str] = []
        batch_errors: List[str] = []
        total = len(batches_text)
        empty_batches = 0
        ok_batches = 0
        if log_emit:
            try:
                log_emit(
                    f"{log_emit_prefix} batched_extract_start",
                    {
                        "total_batches": total,
                        "source": "table_rows" if table_rows else "chunks_or_raw",
                        "max_chars": max_chars,
                        "rows_per_batch": rows_per_batch if table_rows else 0,
                        "input_lines": len(lines) if table_rows else 0,
                    },
                )
            except Exception:
                pass
        batch_delay = float(deepseek_cfg.get("batch_delay_sec", 0) or 0)

        table_row_guard = ""
        if table_rows:
            table_row_guard = (
                "【表格行级约束】以下文本每行以「行N:」开头，N 为原表行号；"
                "每一行对应 Excel 中一行数据，须为该行输出 regions 中至少一条独立对象（该行无脑区时除外）；"
                "禁止将多行合并为一条；禁止仅因共享词根将不同行误归为同一脑区；"
                "每条 source_text 必须摘自该行原文。\n\n"
            )

        for bi, batch in enumerate(batches_text):
            if bi > 0 and batch_delay > 0:
                time.sleep(batch_delay)
            prefix = table_row_guard
            if total > 1:
                prefix += (
                    f"【表格/正文 第 {bi + 1}/{total} 批】以下片段按原始顺序给出，"
                    f"请穷尽本批中出现的全部脑区实体（中英文、缩写进 alias_candidates），不要遗漏；"
                    f"仅输出与本批内容相关的 JSON 对象 {{\"regions\":[...]}} 。\n\n"
                )
            sample = prefix + batch
            prompt = compose_region_file_user_prompt(sample, deepseek_cfg)
            try:
                part = self._deepseek_prompt_to_regions(
                    prompt,
                    file_payload,
                    parsed_document_id,
                    deepseek_cfg,
                    error_prefix=error_prefix,
                    extraction_method=extraction_method,
                    ontology_source=ontology_source,
                    allow_empty=True,
                    batch_meta={"index": bi + 1, "total": total, "max_chars": max_chars},
                    pipeline_config=pipeline_config,
                    root_dir=root_dir,
                )
            except Exception as exc:
                emsg = str(exc)
                # 配置类/鉴权类错误直接失败，不进入“空结果”汇总，避免掩盖根因。
                if emsg.startswith(f"{error_prefix}_disabled") or emsg.startswith(f"{error_prefix}_api_key_missing"):
                    raise
                if emsg.startswith(f"{error_prefix}_http_401") or emsg.startswith(f"{error_prefix}_http_403"):
                    raise
                batch_errors.append(f"batch_{bi + 1}:{emsg}")
                if log_emit:
                    try:
                        log_emit(
                            f"{log_emit_prefix} batch_failed",
                            {"batch_idx": bi + 1, "total_batches": total, "reason": str(exc)[:500]},
                        )
                    except Exception:
                        pass
                continue
            if not part:
                empty_batches += 1
                if log_emit:
                    try:
                        log_emit(
                            f"{log_emit_prefix} batch_empty",
                            {"batch_idx": bi + 1, "total_batches": total},
                        )
                    except Exception:
                        pass
                continue
            ok_batches += 1
            if log_emit:
                try:
                    log_emit(
                        f"{log_emit_prefix} batch_succeeded",
                        {"batch_idx": bi + 1, "total_batches": total, "candidates": len(part)},
                    )
                except Exception:
                    pass
            for c in part:
                en = (c.en_name_candidate or "").strip()
                cn = (c.cn_name_candidate or "").strip()
                if not en and not cn:
                    continue
                key = f"{en.lower()}|{cn}"
                if key not in merged_by_key:
                    merged_by_key[key] = c
                    merge_order.append(key)
                else:
                    _merge_deepseek_region_candidates(
                        merged_by_key[key],
                        c,
                        bind_on_extract=merge_bind_on,
                        require_binding_for_confirmed=merge_require_binding,
                    )

        merged = [merged_by_key[k] for k in merge_order]

        if not merged:
            err_tail = ("; ".join(batch_errors[:5])) if batch_errors else ""
            if batch_errors and empty_batches == 0:
                raise RuntimeError(
                    f"{error_prefix}_all_batches_failed:"
                    f" batch_total={total}, batch_failed={len(batch_errors)}, batch_empty={empty_batches}"
                    + (f" details={err_tail}" if err_tail else "")
                )
            if empty_batches == total and not batch_errors:
                raise RuntimeError(
                    f"{error_prefix}_empty_result:"
                    f" batch_total={total}, batch_empty={empty_batches}, batch_failed={len(batch_errors)}"
                )
            raise RuntimeError(
                f"{error_prefix}_no_valid_candidates:"
                f" batch_total={total}, batch_empty={empty_batches}, batch_failed={len(batch_errors)}"
                + (f" details={err_tail}" if err_tail else "")
            )
        summary = {
            "batched": True,
            "total_batches": total,
            "successful_batches": ok_batches,
            "failed_batches": len(batch_errors),
            "empty_batches": empty_batches,
            "merged_candidate_count": len(merged),
        }
        if log_emit:
            try:
                log_emit(
                    f"{log_emit_prefix} batched_extract_done",
                    {"merged_candidates": len(merged), "failed_batches": len(batch_errors), "empty_batches": empty_batches},
                )
            except Exception:
                pass
        return merged, summary

    def _merge_region_candidate_lists(
        self,
        kimi_rows: List[CandidateRegion],
        ds_rows: List[CandidateRegion],
    ) -> List[CandidateRegion]:
        """双模型：先 Kimi 再 DeepSeek；同名（英|中）以 DeepSeek 条为准覆盖。"""
        merged_by_key: Dict[str, CandidateRegion] = {}
        merge_order: List[str] = []

        def _key(c: CandidateRegion) -> str:
            en = (c.en_name_candidate or "").strip()
            cn = (c.cn_name_candidate or "").strip()
            return f"{en.lower()}|{cn}"

        for c in kimi_rows:
            k = _key(c)
            if k and k != "|" and k not in merged_by_key:
                merged_by_key[k] = c
                merge_order.append(k)
        for c in ds_rows:
            k = _key(c)
            if not k or k == "|":
                continue
            if k in merged_by_key:
                merged_by_key[k] = c
            else:
                merged_by_key[k] = c
                merge_order.append(k)
        return [merged_by_key[k] for k in merge_order]

    def _deepseek_prompt_to_regions(
        self,
        prompt: str,
        file_payload: Dict[str, Any],
        parsed_document_id: str,
        deepseek_cfg: Dict[str, Any],
        *,
        error_prefix: str = "deepseek",
        force_json: Optional[bool] = None,
        extraction_method: str = "deepseek",
        ontology_source: str = "deepseek_extract",
        allow_empty: bool = False,
        batch_meta: Optional[Dict[str, Any]] = None,
        pipeline_config: Optional[Dict[str, Any]] = None,
        root_dir: Optional[str] = None,
    ) -> List[CandidateRegion]:
        llm_cfg = deepseek_cfg
        if error_prefix == "deepseek" and not llm_cfg.get("enabled"):
            raise RuntimeError("deepseek_disabled")
        if not llm_cfg.get("api_key"):
            raise RuntimeError(f"{error_prefix}_api_key_missing")
        prompt_version = str(llm_cfg.get("prompt_version") or "region_extract_v1")
        enrich_from_kb = bool(llm_cfg.get("enrich_from_kb", False))

        default_base = "https://api.deepseek.com" if error_prefix == "deepseek" else "https://api.moonshot.cn"
        bu = (llm_cfg.get("base_url") or "").strip().rstrip("/") or default_base
        if bu.endswith("/v1"):
            bu = bu[:-3].rstrip("/")
        url = bu + "/v1/chat/completions"
        payload = {
            "model": llm_cfg.get("model", "deepseek-chat" if error_prefix == "deepseek" else "moonshot-v1-8k"),
            "temperature": llm_cfg.get("temperature", 0.2),
            "messages": [
                {"role": "system", "content": deepseek_system_content(llm_cfg)},
                {"role": "user", "content": prompt},
            ],
        }
        mt = clamp_deepseek_max_tokens(llm_cfg.get("max_tokens"))
        if mt > 0:
            payload["max_tokens"] = mt
        if llm_cfg.get("top_p") is not None:
            payload["top_p"] = float(llm_cfg.get("top_p"))
        fj = force_json if force_json is not None else (False if error_prefix == "kimi" else bool(llm_cfg.get("force_json_output", True)))
        if fj:
            payload["response_format"] = {"type": "json_object"}
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {llm_cfg.get('api_key', '')}",
            },
            method="POST",
        )
        retries = max(0, int(llm_cfg.get("request_retries", 2)))
        timeout_sec = max(10, int(llm_cfg.get("request_timeout_sec", 120)))
        backoff_sec = max(0.2, float(llm_cfg.get("retry_backoff_sec", 1.2)))
        body = ""
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                with request.urlopen(req, timeout=timeout_sec) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")
                last_exc = None
                break
            except error.HTTPError as exc:  # pragma: no cover
                detail = exc.read().decode("utf-8", errors="ignore")
                last_exc = RuntimeError(f"{error_prefix}_http_{exc.code}:{detail[:300]}")
                if exc.code in (400, 401, 403, 404):
                    break
            except Exception as exc:  # pragma: no cover
                last_exc = RuntimeError(f"{error_prefix}_request_failed:{exc}; {_network_error_hint(exc)}")
            if attempt < retries:
                time.sleep(backoff_sec * (attempt + 1))
        if last_exc is not None:
            raise RuntimeError(
                f"{last_exc}; retries={retries}; timeout_sec={timeout_sec}; prompt_version={prompt_version}"
            ) from last_exc

        msg = self._parse_chat_text(body)
        raw_msg = (msg or "").strip()
        parsed_rows = self._parse_json_rows(msg)
        # 与 _parse_json_rows 内部补救一致：双保险（截断 JSON 时仅前几项闭合）
        if not parsed_rows and raw_msg:
            parsed_rows = _extract_regions_array_objects(raw_msg)
        if not parsed_rows:
            if not raw_msg:
                if allow_empty:
                    return []
                raise RuntimeError(f"{error_prefix}_empty_result")
            probe: Any = None
            try:
                probe = json.loads(raw_msg)
            except json.JSONDecodeError:
                mbrace = re.search(r"\{[\s\S]*\}", raw_msg)
                if not mbrace:
                    parsed_rows = _extract_regions_array_objects(raw_msg)
                    if not parsed_rows:
                        raise RuntimeError(
                            f"{error_prefix}_json_parse_failed: prompt_version={prompt_version}; "
                            f"hint=truncated_or_malformed_json_try_raise_max_tokens; raw_preview={raw_msg[:240]}"
                        ) from None
                else:
                    try:
                        probe = json.loads(mbrace.group(0))
                    except json.JSONDecodeError as exc:
                        parsed_rows = _extract_regions_array_objects(raw_msg)
                        if not parsed_rows:
                            raise RuntimeError(
                                f"{error_prefix}_json_parse_failed: prompt_version={prompt_version}; "
                                f"hint=truncated_or_malformed_json_try_raise_max_tokens; raw_preview={raw_msg[:240]}"
                            ) from exc
            if not parsed_rows and probe is not None:
                if isinstance(probe, dict) and isinstance(probe.get("regions"), list) and len(probe["regions"]) == 0:
                    if allow_empty:
                        return []
                    raise RuntimeError(f"{error_prefix}_empty_result")
                if isinstance(probe, list) and len(probe) == 0:
                    if allow_empty:
                        return []
                    raise RuntimeError(f"{error_prefix}_empty_result")
                if isinstance(probe, dict) and isinstance(probe.get("regions"), list):
                    parsed_rows = probe["regions"]
                elif isinstance(probe, list):
                    parsed_rows = probe
            if not parsed_rows:
                raise RuntimeError(
                    f"{error_prefix}_json_unexpected_shape: prompt_version={prompt_version}; raw_preview={raw_msg[:240]}"
                )
        out: List[CandidateRegion] = []
        seen_keys: set[str] = set()
        orc_ds = (pipeline_config or {}).get("ontology_rules") or {}
        bind_on_ds = bool(orc_ds.get("bind_on_extract", True))
        require_binding_ds = bool(orc_ds.get("require_binding_for_confirmed", True))
        ruleset_ds: Dict[str, Any] = {}
        if bind_on_ds and root_dir:
            _rp = str(orc_ds.get("path") or "artifacts/ontology/ruleset.json").replace("\\", "/")
            ruleset_ds, _ = load_ruleset_dict(root_dir, _rp)
        for batch_index, row in enumerate(parsed_rows):
            if not isinstance(row, dict):
                continue
            norm = normalize_region_llm_row(
                row,
                ontology_default=ontology_source,
                enrich_from_kb=enrich_from_kb,
            )
            norm["ontology_source_candidate"] = ontology_source
            en = norm["en_name_candidate"]
            cn = norm["cn_name_candidate"]
            if not en and not cn:
                continue
            dedupe = f"{en.strip().lower()}|{cn.strip()}"
            if dedupe in seen_keys:
                continue
            seen_keys.add(dedupe)
            _conf = float(norm["confidence"])
            _estatus = derive_region_extract_status(
                extraction_method=extraction_method,
                match_type="",
                confidence=_conf,
                en_name=en,
                cn_name=cn,
            )
            note_obj: Dict[str, Any] = {
                "extract_status": _estatus,
                error_prefix: {
                    "prompt_version": prompt_version,
                    "batches": [batch_meta] if batch_meta else [],
                },
            }
            note_str = json.dumps(note_obj, ensure_ascii=False)
            bind_row: Dict[str, Any] = {}
            if bind_on_ds:
                bind_row = resolve_term_binding(ruleset_ds, en, cn)
            term_key_ds = str(bind_row.get("term_key") or "")
            canonical_ds = str(bind_row.get("canonical") or "")
            if bind_on_ds:
                note_str = merge_ontology_binding_into_review_note(note_str, bind_row)
            note_str = apply_ontology_binding_gate_to_review_note(
                note_str,
                bind_on_extract=bind_on_ds,
                require_binding_for_confirmed=require_binding_ds,
            )
            rid = make_region_candidate_id(
                file_id=file_payload.get("file_id", ""),
                en_name=en,
                cn_name=cn,
                source_text=norm["source_text"],
                batch_index=batch_index,
                term_key=term_key_ds,
                canonical=canonical_ds,
            )
            out.append(
                CandidateRegion(
                    id=rid,
                    file_id=file_payload.get("file_id", ""),
                    parsed_document_id=parsed_document_id,
                    chunk_id="",
                    source_text=norm["source_text"],
                    en_name_candidate=en,
                    cn_name_candidate=cn,
                    alias_candidates=norm["alias_candidates"],
                    laterality_candidate=norm["laterality_candidate"],
                    region_category_candidate=norm["region_category_candidate"],
                    granularity_candidate=norm["granularity_candidate"],
                    parent_region_candidate=norm["parent_region_candidate"],
                    ontology_source_candidate=norm["ontology_source_candidate"],
                    confidence=_conf,
                    extraction_method=extraction_method,
                    llm_model=llm_cfg.get("model", ""),
                    status="pending_review",
                    review_note=note_str,
                    created_at=utc_now_iso(),
                    updated_at=utc_now_iso(),
                )
            )
        if not out:
            if allow_empty:
                return []
            raise RuntimeError(f"{error_prefix}_empty_result")
        return out

    @staticmethod
    def build_region_prompt(mode: str, params: Dict[str, Any]) -> str:
        topic = (params.get("topic") or "脑区").strip()
        species = (params.get("species") or "人类").strip()
        granularity = (params.get("granularity") or "major").strip()
        extra = (params.get("extra_instructions") or "").strip()
        _ = mode
        return (
            f"请列出{species}与「{topic}」相关的脑区（中英文标准名），**粒度为 {granularity}**；"
            "若为 major/粗颗粒度，应覆盖大脑皮层主要叶区、边缘系统、基底节、丘脑/下丘脑、中脑/脑桥/延髓、小脑及嗅球等大体分区，条目数须充足，不得只给少数几条概括。"
            "返回 JSON 对象，且仅含键 \"regions\"，值为数组；数组元素键名必须与文件/文本抽取一致："
            "en_name_candidate,cn_name_candidate,alias_candidates,laterality_candidate,"
            "region_category_candidate,granularity_candidate,parent_region_candidate,"
            "ontology_source_candidate,confidence,source_text。"
            "granularity_candidate 仅 major/sub/allen/unknown；laterality_candidate 仅 left/right/bilateral/midline/unknown；"
            "ontology_source_candidate 填 direct_deepseek。\n"
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

    def run_direct_llm_regions(
        self,
        file_payload: Dict[str, Any],
        parsed_document_id: str,
        params: Dict[str, Any],
        deepseek_cfg: Dict[str, Any],
        *,
        provider: str = "deepseek",
        moonshot_cfg: Optional[Dict[str, Any]] = None,
        pipeline_config: Optional[Dict[str, Any]] = None,
        root_dir: Optional[str] = None,
    ) -> List[CandidateRegion]:
        prompt = compose_direct_region_user_prompt(params, deepseek_cfg)
        if (provider or "").lower() == "kimi":
            ms = dict(moonshot_cfg or {})
            if not ms.get("api_key"):
                raise RuntimeError("moonshot_api_key_missing")
            ms.setdefault("enabled", True)
            ms.setdefault("base_url", "https://api.moonshot.cn")
            ms.setdefault("model", "moonshot-v1-8k")
            ms["force_json_output"] = False
            return self._deepseek_prompt_to_regions(
                prompt,
                file_payload,
                parsed_document_id,
                ms,
                error_prefix="kimi",
                extraction_method="direct_kimi",
                ontology_source="direct_kimi",
                pipeline_config=pipeline_config,
                root_dir=root_dir,
            )
        return self._deepseek_prompt_to_regions(
            prompt,
            file_payload,
            parsed_document_id,
            deepseek_cfg,
            extraction_method="direct_deepseek",
            ontology_source="direct_deepseek",
            pipeline_config=pipeline_config,
            root_dir=root_dir,
        )

    def run_direct_deepseek_regions(
        self,
        file_payload: Dict[str, Any],
        parsed_document_id: str,
        params: Dict[str, Any],
        deepseek_cfg: Dict[str, Any],
        *,
        pipeline_config: Optional[Dict[str, Any]] = None,
        root_dir: Optional[str] = None,
    ) -> List[CandidateRegion]:
        return self.run_direct_llm_regions(
            file_payload,
            parsed_document_id,
            params,
            deepseek_cfg,
            provider="deepseek",
            moonshot_cfg=None,
            pipeline_config=pipeline_config,
            root_dir=root_dir,
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
        raw = (text or "").strip()
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
            if m:
                raw = m.group(1).strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 截取首个 [...] 或 {...} 片段再试（模型偶发前后夹杂说明文字）
            m2 = re.search(r"\[[\s\S]*\]", raw)
            if m2:
                try:
                    data = json.loads(m2.group(0))
                except json.JSONDecodeError:
                    data = None
            else:
                data = None
            if data is None:
                m3 = re.search(r"\{[\s\S]*\}", raw)
                if m3:
                    try:
                        data = json.loads(m3.group(0))
                    except json.JSONDecodeError:
                        data = None
                else:
                    data = None
            if data is None:
                # 响应被 max_tokens 截断：整段 JSON 非法，但前面若干 region 对象可能已完整闭合
                partial = _extract_regions_array_objects(raw)
                if partial:
                    return partial
                return []
        if isinstance(data, dict):
            wrapped: Any = None
            for k in ("regions", "items", "data", "candidates", "brain_regions", "results", "rows", "output", "result", "records"):
                v = data.get(k)
                if isinstance(v, list):
                    wrapped = v
                    break
            if wrapped is not None:
                data = wrapped
            elif any(x in data for x in ("en_name_candidate", "cn_name_candidate", "en_name", "cn_name")):
                data = [data]
            else:
                return []
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
