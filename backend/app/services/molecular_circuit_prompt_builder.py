"""Prompt builder for DeepSeek semantic judgment of molecular circuit candidates.

Builds structured prompts for the DeepSeek LLM to judge whether candidate
topological structures constitute biologically meaningful neural circuits.
Provides system prompt, pack prompt assembly, and token estimation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── JSON Schema for circuit judgment output ────────────────────────────────
# This schema defines the exact structure DeepSeek must return for each
# candidate topology in the pack.

CIRCUIT_JUDGMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "circuit_id": {"type": "string"},
        "name_en": {"type": "string"},
        "name_cn": {"type": "string"},
        "functional_module": {"type": "array", "items": {"type": "string"}},
        "topology_type": {
            "type": "string",
            "enum": [
                "directed_cycle_3",
                "feedforward_loop_3",
                "reciprocal_pair_3",
                "convergent_motif",
                "divergent_motif",
                "relay_pathway_3_6",
                "closed_loop_4_8",
                "cortico_subcortical_loop",
                "cross_module_loop",
            ],
        },
        "anatomical_pattern": {
            "type": "string",
            "enum": [
                "closed_circuit",
                "open_pathway",
                "feedforward_motif",
                "feedback_motif",
                "convergent_motif",
                "divergent_motif",
            ],
        },
        "closed_loop": {"type": "boolean"},
        "nodes": {"type": "array"},
        "edges": {"type": "array"},
        "functional_summary": {"type": "string"},
        "neuroscience_rationale": {"type": "string"},
        "evidence_basis": {"type": "string"},
        "known_status": {
            "type": "string",
            "enum": [
                "canonical",
                "literature_supported",
                "plausible_hypothesis",
                "topology_only",
            ],
        },
        "confidence_level": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "overall_confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "uncertainties": {"type": "array"},
        "review_status": {
            "type": "string",
            "enum": ["candidate", "manual_review", "rejected"],
        },
    },
    "required": [
        "circuit_id",
        "name_en",
        "name_cn",
        "topology_type",
        "anatomical_pattern",
        "closed_loop",
        "nodes",
        "edges",
    ],
}


@dataclass
class PackPrompt:
    """Complete prompt for one pack sent to DeepSeek."""

    system_prompt: str
    user_prompt: str
    estimated_tokens: int = 0


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~3 chars per token for English, ~1.5 for Chinese.

    Uses a character-classification approach: ASCII runs are counted at 3
    chars/token, CJK runs at 1.5 chars/token. Mixed text is handled segment
    by segment.
    """
    if not text:
        return 0

    total_chars = len(text)
    cjk_count = 0
    ascii_count = 0

    for ch in text:
        code = ord(ch)
        # CJK Unified Ideographs (4E00-9FFF), CJK Extension A (3400-4DBF),
        # CJK Compatibility (F900-FAFF), and fullwidth forms (FF00-FFEF)
        if (
            0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0xF900 <= code <= 0xFAFF
            or 0xFF01 <= code <= 0xFFEF
        ):
            cjk_count += 1
        else:
            ascii_count += 1

    estimated = (ascii_count / 3.0) + (cjk_count / 1.5)
    return max(1, int(estimated))


# ── System Prompt (English, per spec section 7.1) ──────────────────────────

_SYSTEM_PROMPT = (
    "You are an expert in neuroanatomy, systems neuroscience, and brain connectomics. "
    "Your task is to judge whether candidate topological structures constitute "
    "biologically meaningful neural circuits, feedback loops, feedforward pathways, "
    "relay chains, or functional network modules.\n\n"
    "CRITICAL RULES:\n"
    "1. NEVER invent brain regions not present in the input.\n"
    "2. NEVER invent edges not present in the input.\n"
    "3. NEVER change the direction of any projection.\n"
    "4. NEVER infer A->C from A->B and B->C (no transitive closure).\n"
    "5. You MUST return the complete list of edge_ids constituting each result.\n"
    "6. For closed loops, verify the LAST node truly projects back to the FIRST.\n"
    "7. Topologically valid but functionally uncertain candidates MAY be kept at low confidence.\n"
    "8. Distinguish: canonical textbook circuits, plausible novel combinations, and topology-only structures.\n"
    "9. Do NOT reject a candidate simply because the region name is unfamiliar.\n"
    "10. Do NOT output node-rotated duplicates of the same circuit.\n"
    "11. Do NOT interpret correlational connections as causal projections.\n"
    "12. When evidence is insufficient, explicitly state the uncertainty.\n\n"
    "You will receive candidate topologies with their constituent regions and edges. "
    "For EACH candidate, output a structured JSON judgment. "
    "Do NOT output a summary paragraph — output only the JSON array."
)


def build_system_prompt() -> str:
    """Return the system prompt for DeepSeek circuit judgment (English).

    The prompt is fixed (not templated) and follows spec section 7.1.
    It guides the model to make biologically grounded judgments while
    enforcing critical constraints against hallucination.
    """
    return _SYSTEM_PROMPT


# ── Pack Prompt Builder ────────────────────────────────────────────────────

_TOPOLOGY_TYPE_DESCRIPTIONS = {
    "directed_cycle_3": "3-node directed cycle: A -> B -> C -> A. A closed-loop motif.",
    "feedforward_loop_3": "3-node feedforward: A->B, A->C, B->C. Hierarchical processing.",
    "reciprocal_pair_3": "3-node chain with reciprocal connections: A<->B, B<->C.",
    "convergent_motif": "Two sources converge onto one target: A->C, B->C.",
    "divergent_motif": "One source diverges to two targets: A->B, A->C.",
    "relay_pathway_3_6": "Multi-node directed relay pathway (3-6 nodes).",
    "closed_loop_4_8": "Closed loop with 4-8 nodes returning to origin.",
    "cortico_subcortical_loop": "Cortex <-> subcortical closed loop.",
    "cross_module_loop": "Closed loop spanning 2+ functional modules.",
}

_ANATOMICAL_PATTERN_DESCRIPTIONS = {
    "closed_circuit": "A circuit that closes back on itself (feedback regulation).",
    "open_pathway": "An open chain with distinct start and end (feedforward processing).",
    "feedforward_motif": "Hierarchical feedforward motif with convergence.",
    "feedback_motif": "Reciprocal or feedback connectivity pattern.",
    "convergent_motif": "Multiple inputs converging on a single target (integration).",
    "divergent_motif": "Single source diverging to multiple targets (broadcast).",
}


def _format_candidates_section(
    candidates: list[dict[str, Any]],
    module_name: str,
    region_basics: list[dict[str, Any]],
    functional_labels: dict[str, list[str]],
) -> str:
    """Format the candidate topologies section of the user prompt."""
    lines: list[str] = [
        f"# Candidate Topologies for Module: {module_name}",
        f"Total candidates in this pack: {len(candidates)}",
        "",
    ]

    for idx, cand in enumerate(candidates):
        cand_id = cand.get("canonical_key", cand.get("id", f"candidate_{idx}"))
        topo_type = cand.get("topology_type", "unknown")
        anat_pattern = cand.get("anatomical_pattern", "unknown")
        closed = cand.get("closed_loop", False)
        nodes = cand.get("nodes", [])
        edges = cand.get("edges", [])

        lines.append(f"--- Candidate {idx + 1}: {cand_id} ---")
        lines.append(f"Topology Type: {topo_type}")
        lines.append(
            f"  Description: {_TOPOLOGY_TYPE_DESCRIPTIONS.get(topo_type, '')}"
        )
        lines.append(f"Anatomical Pattern: {anat_pattern}")
        lines.append(
            f"  Description: {_ANATOMICAL_PATTERN_DESCRIPTIONS.get(anat_pattern, '')}"
        )
        lines.append(f"Closed Loop: {closed}")
        lines.append(f"Node count: {len(nodes)}  Edge count: {len(edges)}")

        # Nodes
        lines.append("Nodes (ordered):")
        for n_idx, node in enumerate(nodes):
            if isinstance(node, dict):
                region_id = node.get("region_id", "?")
                region_name = node.get(
                    "region_name", node.get("label", f"region_{n_idx}")
                )
                role = node.get("role", "participant")
                modules = functional_labels.get(str(region_id), [])
                module_str = ",".join(modules) if modules else "uncertain"
                lines.append(
                    f"  {n_idx + 1}. {region_id} | {region_name} | role={role} | modules=[{module_str}]"
                )
            else:
                region_id_str = str(node)
                modules = functional_labels.get(region_id_str, [])
                module_str = ",".join(modules) if modules else "uncertain"
                lines.append(f"  {n_idx + 1}. {node} | modules=[{module_str}]")

        # Edges
        lines.append("Edges (ordered):")
        for e_idx, edge in enumerate(edges):
            if isinstance(edge, dict):
                edge_id = edge.get("edge_id", "?")
                src = edge.get("source_region_id", "?")
                tgt = edge.get("target_region_id", "?")
                conn_type = edge.get("connection_type", "projection")
                conf = edge.get("source_confidence", "N/A")
                lines.append(
                    f"  {e_idx + 1}. {edge_id} | {src} -> {tgt} | type={conn_type} conf={conf}"
                )
            else:
                lines.append(f"  {e_idx + 1}. {edge}")
        lines.append("")

    return "\n".join(lines)


def _format_edges_section(edges: list[dict[str, Any]]) -> str:
    """Format the relevant edge details section."""
    lines: list[str] = [
        "# Relevant Edge Details",
        f"Total edges provided for context: {len(edges)}",
        "",
        "Each edge is a directed projection between two brain regions.",
        "Format: edge_id | source -> target | type | confidence | evidence_count",
        "",
    ]

    for edge in edges:
        edge_id = edge.get("edge_id", "?")
        src = edge.get("source_region_id", "?")
        tgt = edge.get("target_region_id", "?")
        conn_type = edge.get("connection_type", "projection")
        conf = edge.get("confidence", edge.get("source_confidence", "N/A"))
        evidence = edge.get("evidence_count", "N/A")
        lines.append(
            f"  {edge_id} | {src} -> {tgt} | {conn_type} | {conf} | evidence={evidence}"
        )

    return "\n".join(lines)


def _format_regions_section(regions: list[dict[str, Any]]) -> str:
    """Format the region basics lookup section."""
    lines: list[str] = [
        "# Region Basic Information",
        f"Total regions referenced: {len(regions)}",
        "",
        "Each region is identified by its canonical ID. Use these names and IDs",
        "when constructing circuit judgments.",
        "",
        "Format: region_id | en_name | cn_name | laterality",
        "",
    ]

    for region in regions:
        region_id = region.get("region_id", region.get("id", "?"))
        en_name = region.get("en_name", region.get("english_name", "?"))
        cn_name = region.get("cn_name", region.get("chinese_name", "?"))
        laterality = region.get("laterality", "unknown")
        lines.append(f"  {region_id} | {en_name} | {cn_name} | {laterality}")

    return "\n".join(lines)


def _format_labels_section(labels: dict[str, list[str]]) -> str:
    """Format the functional labels section."""
    lines: list[str] = [
        "# Functional Module Labels",
        "Each region's predicted functional module(s).",
        "Modules: sensory, motor, attention_salience, executive_control, learning_memory,",
        "emotion_reward, language_social, interoception_autonomic, sleep_arousal, multimodal_default",
        "",
        "Format: region_id -> [module1, module2, ...]",
        "",
    ]

    for region_id_str, module_list in sorted(labels.items()):
        modules_str = ", ".join(module_list) if module_list else "module_uncertain"
        lines.append(f"  {region_id_str} -> [{modules_str}]")

    return "\n".join(lines)


def _build_user_prompt_body(
    pack_candidates: list[dict[str, Any]],
    relevant_edges: list[dict[str, Any]],
    region_basics: list[dict[str, Any]],
    functional_labels: dict[str, list[str]],
    module_name: str,
    max_circuits: int,
) -> str:
    """Assemble the user prompt body with all sections."""
    sections: list[str] = [
        _format_candidates_section(
            candidates=pack_candidates,
            module_name=module_name,
            region_basics=region_basics,
            functional_labels=functional_labels,
        ),
        _format_edges_section(relevant_edges),
        _format_regions_section(region_basics),
        _format_labels_section(functional_labels),
    ]

    return "\n\n".join(sections)


def build_pack_prompt(
    pack_candidates: list[dict[str, Any]],
    relevant_edges: list[dict[str, Any]],
    region_basics: list[dict[str, Any]],
    functional_labels: dict[str, list[str]],
    module_name: str,
    max_circuits: int = 200,
) -> PackPrompt:
    """Build a complete pack prompt for DeepSeek semantic judgment.

    The prompt includes:
      - Module context and identification goal
      - Candidate topologies with ordered nodes and edge_ids
      - Relevant edge details (direction, type, confidence)
      - Region basic info (name/id mapping)
      - Functional labels per region
      - Clear output format specification (JSON array)

    Args:
        pack_candidates: List of candidate topology dicts (nodes + edges).
        relevant_edges: Edge detail records for context.
        region_basics: Region name/id mapping records.
        functional_labels: Region_id -> [module_label] mapping.
        module_name: Name of the functional module being processed.
        max_circuits: Target maximum number of circuits to identify.

    Returns:
        A PackPrompt with system_prompt, user_prompt, and estimated_tokens.
    """
    system_prompt = build_system_prompt()

    body = _build_user_prompt_body(
        pack_candidates=pack_candidates,
        relevant_edges=relevant_edges,
        region_basics=region_basics,
        functional_labels=functional_labels,
        module_name=module_name,
        max_circuits=max_circuits,
    )

    # Instruction header for the user prompt
    header = (
        f"Analyze the {len(pack_candidates)} candidate topologies below for module '{module_name}'.\n"
        f"Identify biologically meaningful neural circuits and output your judgment "
        f"as a JSON array. Target up to {max_circuits} circuits.\n\n"
        "OUTPUT FORMAT: Return ONLY a JSON array. Each element must conform to the schema:\n"
        f"{json.dumps(CIRCUIT_JUDGMENT_SCHEMA, indent=2, ensure_ascii=False)}\n\n"
        "IMPORTANT:\n"
        "- Output a JSON array, one object per valid circuit.\n"
        "- If a candidate is judged invalid (no biological meaning), OMIT it from the array.\n"
        "- Do NOT wrap in a top-level object with a 'circuits' key.\n"
        "- Do NOT include markdown code fences (```).\n"
        "- Return [] if no candidate is valid.\n\n"
        "DATA:\n"
    )

    user_prompt = header + body

    total_text = system_prompt + user_prompt
    estimated = estimate_tokens(total_text)

    return PackPrompt(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        estimated_tokens=estimated,
    )
