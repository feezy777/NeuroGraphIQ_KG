"""Molecular circuit module classifier — multi-label functional module assignment.

Assigns 1-3 functional module labels to each brain region based on:
  1. Existing functional_domains annotations (if available on the model)
  2. Keyword matching against region names (en_name, cn_name, raw_name, std_name)
  3. Raw payload inspection for additional functional hints

Provides cross-module candidate identification, hub detection, and module
coherence scoring used by the packing and prompt-building pipeline.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion

logger = logging.getLogger(__name__)

# ── 10 Functional Module Definitions ────────────────────────────────────────
# Each entry defines keywords for matching and a set of location hints
# (cortical / subcortical) to help disambiguate ambiguous matches.

MODULE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "sensory": {
        "keywords": [
            "visual", "auditory", "somatosensory", "gustatory", "olfactory",
            "sensory", "V1", "V2", "V4", "A1", "S1", "barrel",
        ],
        "cortical": True,
    },
    "motor": {
        "keywords": [
            "motor", "premotor", "supplementary motor", "cerebell",
            "basal ganglia", "striatum", "pallidum", "substantia nigra",
            "red nucleus",
        ],
        "cortical": True,
        "subcortical": True,
    },
    "attention_salience": {
        "keywords": [
            "cingulate", "insula", "frontal eye", "parietal",
            "intraparietal", "salience",
        ],
        "cortical": True,
    },
    "executive_control": {
        "keywords": [
            "prefrontal", "dorsolateral", "frontal pole", "orbitofrontal",
            "working memory",
        ],
        "cortical": True,
    },
    "learning_memory": {
        "keywords": [
            "hippocamp", "entorhinal", "perirhinal", "parahippocamp",
            "subiculum", "dentate", "CA1", "CA2", "CA3", "memory",
        ],
        "cortical": True,
        "subcortical": True,
    },
    "emotion_reward": {
        "keywords": [
            "amygdal", "nucleus accumbens", "ventral tegmental",
            "ventral striatum", "orbitofrontal", "reward", "emotion",
            "fear", "anxiety", "stress",
        ],
        "cortical": True,
        "subcortical": True,
    },
    "language_social": {
        "keywords": [
            "broca", "wernicke", "temporal pole", "superior temporal",
            "middle temporal", "inferior frontal", "language", "semantic",
        ],
        "cortical": True,
    },
    "interoception_autonomic": {
        "keywords": [
            "hypothalam", "brainstem", "autonomic", "visceral",
            "interoception", "solitary", "parabrachial", "periaqueductal",
        ],
        "subcortical": True,
    },
    "sleep_arousal": {
        "keywords": [
            "reticular", "raphe", "locus coeruleus", "tuberomammillary",
            "pedunculopontine", "laterodorsal tegmental", "basal forebrain",
            "sleep", "arousal", "wake",
        ],
        "subcortical": True,
    },
    "multimodal_default": {
        "keywords": [
            "default mode", "posterior cingulate", "precuneus",
            "angular gyrus", "medial prefrontal", "multisensory",
            "polymodal",
        ],
        "cortical": True,
    },
}

MODULE_NAMES: list[str] = list(MODULE_DEFINITIONS.keys())


def _match_keywords(name: str, keywords: list[str]) -> bool:
    """Check if any keyword appears in the given name (case-insensitive)."""
    name_lower = name.lower()
    for kw in keywords:
        if kw.lower() in name_lower:
            return True
    return False


def _classify_single_region(
    en_name: str | None,
    cn_name: str | None,
    raw_name: str | None,
    std_name: str | None,
    functional_domains: list[str] | None,
    raw_payload: dict[str, Any] | None,
) -> list[str]:
    """Return 1-3 functional module labels for a single region.

    Priority order:
      1. Explicit functional_domains annotations (if they map to our modules)
      2. Keyword matching on region names (en, cn, raw, std)
      3. Raw payload functional hints
      4. Fallback: ['module_uncertain']
    """
    labels: list[str] = []
    seen: set[str] = set()

    # ── 1. Check explicit functional_domains ──
    if functional_domains:
        for domain in functional_domains:
            domain_lower = domain.lower().replace(" ", "_")
            for module_name in MODULE_NAMES:
                if module_name in domain_lower or domain_lower in module_name:
                    if module_name not in seen:
                        labels.append(module_name)
                        seen.add(module_name)

    # ── 2. Keyword matching on all available names ──
    names_to_check = [n for n in [en_name, cn_name, raw_name, std_name] if n]
    for module_name, definition in MODULE_DEFINITIONS.items():
        if module_name in seen:
            continue
        for name in names_to_check:
            if _match_keywords(name, definition["keywords"]):
                labels.append(module_name)
                seen.add(module_name)
                break

    # ── 3. Check raw_payload for functional hints ──
    if raw_payload and isinstance(raw_payload, dict):
        payload_func = raw_payload.get("functional_domains") or raw_payload.get(
            "functional_group"
        )
        if payload_func:
            func_text = str(payload_func).lower().replace(" ", "_")
            for module_name in MODULE_NAMES:
                if module_name not in seen and module_name in func_text:
                    labels.append(module_name)
                    seen.add(module_name)

    # ── 4. Fallback ──
    if not labels:
        labels = ["module_uncertain"]

    # Cap at 3 labels maximum
    return labels[:3]


async def classify_regions(
    session: AsyncSession,
    candidate_ids: list[uuid.UUID],
) -> dict[str, list[str]]:
    """Load candidate regions and return {region_id_str: [module_labels]}.

    Each region receives 1-3 multi-label functional module assignments.
    Regions with insufficient information get ['module_uncertain'].
    """
    if not candidate_ids:
        return {}

    # Build result lookup keyed by string-form UUID
    result: dict[str, list[str]] = {}

    # Batch load candidates
    stmt = select(CandidateBrainRegion).where(
        CandidateBrainRegion.id.in_(candidate_ids)
    )
    rows = await session.execute(stmt)
    regions = rows.scalars().all()

    for region in regions:
        region_id_str = str(region.id)

        # Extract functional_domains: check raw_payload first,
        # then fall back to getattr for any model-level annotation
        functional_domains: list[str] | None = None
        if region.raw_payload and isinstance(region.raw_payload, dict):
            functional_domains = region.raw_payload.get("functional_domains")

        if functional_domains is None:
            func_attr = getattr(region, "functional_domains", None)
            if func_attr is not None:
                functional_domains = (
                    func_attr if isinstance(func_attr, list) else [str(func_attr)]
                )

        labels = _classify_single_region(
            en_name=region.en_name,
            cn_name=region.cn_name,
            raw_name=region.raw_name,
            std_name=region.std_name,
            functional_domains=functional_domains,
            raw_payload=region.raw_payload,
        )
        result[region_id_str] = labels

    # Ensure all requested IDs have an entry (even if not found in DB)
    for cid in candidate_ids:
        cid_str = str(cid)
        if cid_str not in result:
            result[cid_str] = ["module_uncertain"]

    return result


def get_cross_module_candidates(
    candidates: list[dict[str, Any]],
    region_modules: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Identify candidates that span two or more different functional modules.

    Args:
        candidates: List of candidate topology dicts, each containing a
            'nodes' key with region_id entries.
        region_modules: Mapping from region_id (str) to list of module labels.

    Returns:
        List of candidate dicts whose nodes belong to at least 2 modules.
    """
    cross_module: list[dict[str, Any]] = []

    for candidate in candidates:
        nodes = candidate.get("nodes", [])
        modules_covered: set[str] = set()

        for node in nodes:
            region_id = node.get("region_id") if isinstance(node, dict) else str(node)
            region_id_str = str(region_id)
            node_modules = region_modules.get(region_id_str, ["module_uncertain"])
            modules_covered.update(node_modules)

            # Early exit: already have 2 distinct modules
            if len(modules_covered) >= 2:
                break

        # Remove module_uncertain from the count; only count real modules
        real_modules = modules_covered - {"module_uncertain"}

        # Also check if the candidate itself has functional_module declared
        candidate_modules = candidate.get("functional_module", [])
        if candidate_modules:
            real_modules.update(candidate_modules)

        if len(real_modules) >= 2:
            candidate["cross_module"] = True
            candidate["modules_involved"] = sorted(real_modules)
            cross_module.append(candidate)
        else:
            candidate["cross_module"] = False

    return cross_module


def get_module_hubs(
    region_modules: dict[str, list[str]],
    graph_nodes: set[str],
    min_module_count: int = 2,
) -> dict[str, list[str]]:
    """Identify hub regions that belong to multiple functional modules.

    A hub region participates in 2 or more modules — these are key
    integrative nodes for cross-module circuit formation.

    Args:
        region_modules: Mapping from region_id (str) to list of module labels.
        graph_nodes: Set of all region IDs present in the graph.
        min_module_count: Minimum number of modules to qualify as a hub.

    Returns:
        Dictionary mapping module_name -> list of hub region_id strings
        that belong to that module and also belong to other modules.
    """
    # Build reverse map: module -> set of region_ids
    module_regions: dict[str, set[str]] = {}
    for region_id_str, modules in region_modules.items():
        if region_id_str not in graph_nodes:
            continue
        for mod in modules:
            if mod == "module_uncertain":
                continue
            module_regions.setdefault(mod, set()).add(region_id_str)

    # For each region, count how many distinct modules it participates in
    region_module_count: dict[str, set[str]] = {}
    for region_id_str, modules in region_modules.items():
        if region_id_str not in graph_nodes:
            continue
        real_modules = {m for m in modules if m != "module_uncertain"}
        if len(real_modules) >= min_module_count:
            region_module_count[region_id_str] = real_modules

    # Build result: module -> [hub_region_ids]
    hubs: dict[str, list[str]] = {}
    for region_id_str, modules in region_module_count.items():
        for mod in modules:
            hubs.setdefault(mod, []).append(region_id_str)

    return hubs


def calculate_module_coherence(
    candidate_nodes: list[str],
    region_modules: dict[str, list[str]],
) -> float:
    """Calculate a 0-1 coherence score for the module labels of a set of nodes.

    Score rationale:
      - 1.0: All nodes share exactly the same non-uncertain module label.
      - 0.7-0.9: All nodes share at least one common module.
      - 0.4-0.6: Nodes belong to different but related modules (overlap exists).
      - 0.1-0.3: Modules are distinct with no overlap (cross-module).
      - 0.0: All nodes are module_uncertain.

    Args:
        candidate_nodes: List of region_id strings in the candidate.
        region_modules: Mapping from region_id (str) to list of module labels.

    Returns:
        Float between 0.0 and 1.0.
    """
    if not candidate_nodes:
        return 0.0

    all_modules: list[set[str]] = []
    any_uncertain = False

    for node_id in candidate_nodes:
        modules = region_modules.get(node_id, ["module_uncertain"])
        real_modules = {m for m in modules if m != "module_uncertain"}
        if not real_modules:
            any_uncertain = True
        all_modules.append(real_modules)

    # ── If all nodes have no real modules ──
    if all(not s for s in all_modules):
        return 0.0

    # ── Check for a common module across ALL nodes ──
    common_modules = set.intersection(*all_modules) if all_modules else set()
    if common_modules and not any_uncertain:
        # Perfect match
        if len(common_modules) == 1 and all(len(s) == 1 for s in all_modules):
            return 1.0
        return 0.8

    if common_modules:
        # Common module exists but some nodes also have uncertain
        return 0.7

    # ── Check pairwise Jaccard similarity ──
    pairwise_scores: list[float] = []
    for i in range(len(all_modules)):
        for j in range(i + 1, len(all_modules)):
            a = all_modules[i]
            b = all_modules[j]
            if not a and not b:
                pairwise_scores.append(1.0)
            elif not a or not b:
                pairwise_scores.append(0.3)
            else:
                intersection = len(a & b)
                union = len(a | b)
                pairwise_scores.append(intersection / union if union > 0 else 0.0)

    if pairwise_scores:
        avg_pairwise = sum(pairwise_scores) / len(pairwise_scores)
        return round(avg_pairwise * 0.6 + 0.1, 4)

    return 0.1
