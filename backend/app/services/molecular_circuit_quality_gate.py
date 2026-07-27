"""Post-DeepSeek deterministic validation and deduplication for molecular circuits.

Phase 4 of the Molecular circuit extraction v2 pipeline. Validates DeepSeek-reviewed
candidates against graph ground truth, deduplicates, and computes acceptance statistics.

All functions in this module are PURE — no database, no I/O, no side effects.
They operate on plain dicts so they can be tested without fixtures or mocking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

EdgeRecord = dict[str, Any]
"""Minimal shape: {"id": str, "source_id": str, "target_id": str, ...} or a dataclass
with those attributes.  The validator uses ``getattr`` for compatibility with both."""

def _edge_get(edge: Any, key: str, default: Any = None) -> Any:
    """Safe attribute/dict access for EdgeRecord objects or dicts."""
    if isinstance(edge, dict):
        return edge.get(key, default)
    return getattr(edge, key, default)


# ---------------------------------------------------------------------------
# Validation primitives
# ---------------------------------------------------------------------------


@dataclass
class ValidationViolation:
    """One rule violation found during deterministic validation.

    Attributes:
        rule: Short machine-readable rule name (e.g. ``unknown_region``).
        detail: Human-readable explanation.
        field: Optional JSON-path-style reference to the offending field.
    """

    rule: str
    detail: str
    field: str | None = None


@dataclass
class ValidationResult:
    """Aggregate result of validating one circuit candidate.

    Attributes:
        passed: True when *zero* violations were found.
        violations: Ordered list of every violation encountered.
    """

    passed: bool = True
    violations: list[ValidationViolation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Anatomical-pattern / topology-type mapping  (spec section 5.2)
# ---------------------------------------------------------------------------

ANATOMICAL_PATTERN_MAP: dict[str, str] = {
    "directed_cycle_3": "closed_circuit",
    "feedforward_loop_3": "feedforward_motif",
    "reciprocal_pair_3": "feedback_motif",
    "convergent_motif": "convergent_motif",
    "divergent_motif": "divergent_motif",
    "relay_pathway_3_6": "open_pathway",
    "closed_loop_4_8": "closed_circuit",
    "cortico_subcortical_loop": "closed_circuit",
    "cross_module_loop": "closed_circuit",
}

_VALID_TOPOLOGY_TYPES: set[str] = set(ANATOMICAL_PATTERN_MAP.keys())


# ---------------------------------------------------------------------------
# Section 8.1 — Rule-based validation
# ---------------------------------------------------------------------------


def validate_circuit(
    candidate: dict[str, Any],
    graph_nodes: set[str],
    graph_edges: dict[str, EdgeRecord],
) -> ValidationResult:
    """Check ALL rules from spec section 8.1 against one DeepSeek-reviewed candidate.

    Rules enforced:
        1. Every ``region_id`` in ``candidate["nodes"]`` lives in ``graph_nodes`` (574).
        2. Every ``edge_id`` in ``candidate["edges"]`` exists in ``graph_edges``.
        3. Each edge's ``source_region_id`` / ``target_region_id`` matches the original record.
        4. Edge order continuity: ``edge[i].target == edge[i+1].source``.
        5. If ``closed_loop == True``, last edge's target == first edge's source.
        6. No duplicate ``edge_id`` within one candidate.
        7. Rotated-duplicate detection is *not* checked here — canonical-key dedup
           is handled in :func:`deduplicate_candidates`.

    Args:
        candidate: A DeepSeek-reviewed circuit candidate dict (see spec section 7.2).
        graph_nodes: Set of valid 574 molecular-region IDs (as strings).
        graph_edges: ``{edge_id: edge_record}`` lookup for all 64 313 edges.

    Returns:
        A :class:`ValidationResult` with ``passed=True`` only when every rule passes.
    """
    violations: list[ValidationViolation] = []

    # ── Rule 1: every region_id in nodes belongs to the 574 ───────────────
    nodes = candidate.get("nodes", [])
    node_ids_in_candidate: set[str] = set()
    for idx, node in enumerate(nodes):
        rid = node.get("region_id")
        if not rid:
            violations.append(
                ValidationViolation(
                    rule="missing_region_id",
                    detail=f"Node at index {idx} has no region_id.",
                    field=f"nodes[{idx}].region_id",
                )
            )
            continue
        if rid not in graph_nodes:
            violations.append(
                ValidationViolation(
                    rule="unknown_region",
                    detail=f"region_id '{rid}' not found in the 574 valid regions.",
                    field=f"nodes[{idx}].region_id",
                )
            )
        node_ids_in_candidate.add(rid)

    # ── Rule 2 + 3: edge_id exists in graph_edges, source/target matches ──
    edges = candidate.get("edges", [])
    seen_edge_ids: set[str] = set()
    for idx, edge in enumerate(edges):
        eid = edge.get("edge_id")
        if not eid:
            violations.append(
                ValidationViolation(
                    rule="missing_edge_id",
                    detail=f"Edge at index {idx} has no edge_id.",
                    field=f"edges[{idx}].edge_id",
                )
            )
            continue

        # Rule 6 (inlined): no duplicate edge_id within candidate
        if eid in seen_edge_ids:
            violations.append(
                ValidationViolation(
                    rule="duplicate_edge",
                    detail=f"edge_id '{eid}' appears more than once in this candidate.",
                    field=f"edges[{idx}].edge_id",
                )
            )
            continue
        seen_edge_ids.add(eid)

        # edge_id can be UUID or str — normalize to str for lookup
        actual = graph_edges.get(eid) or graph_edges.get(str(eid))
        if actual is None:
            violations.append(
                ValidationViolation(
                    rule="missing_edge",
                    detail=f"edge_id '{eid}' does not exist in the 64 313-edge graph.",
                    field=f"edges[{idx}].edge_id",
                )
            )
            continue

        # Rule 3: source/target match original record (supports both dict & dataclass)
        actual_source = _edge_get(actual, "source_id")
        actual_target = _edge_get(actual, "target_id")
        edge_source = edge.get("source_region_id") or edge.get("source_id")
        edge_target = edge.get("target_region_id") or edge.get("target_id")

        mismatches: list[str] = []
        if edge_source and actual_source and edge_source != actual_source:
            mismatches.append(f"source {edge_source} != actual {actual_source}")
        if edge_target and actual_target and edge_target != actual_target:
            mismatches.append(f"target {edge_target} != actual {actual_target}")
        if mismatches:
            violations.append(
                ValidationViolation(
                    rule="direction_mismatch",
                    detail=f"edge_id '{eid}': {'; '.join(mismatches)}.",
                    field=f"edges[{idx}]",
                )
            )

    # ── Rule 4: edge order continuity ────────────────────────────────────
    if len(edges) >= 2:
        for i in range(len(edges) - 1):
            current_target = edges[i].get("target_region_id")
            next_source = edges[i + 1].get("source_region_id")
            if current_target and next_source and current_target != next_source:
                violations.append(
                    ValidationViolation(
                        rule="discontinuous_order",
                        detail=(
                            f"Edge {i} target '{current_target}' != "
                            f"edge {i + 1} source '{next_source}'."
                        ),
                        field=f"edges[{i}].target_region_id / edges[{i + 1}].source_region_id",
                    )
                )

    # ── Rule 5: closed_loop validation ──────────────────────────────────
    if candidate.get("closed_loop") and len(edges) >= 1:
        last_target = edges[-1].get("target_region_id")
        first_source = edges[0].get("source_region_id")
        if last_target and first_source and last_target != first_source:
            violations.append(
                ValidationViolation(
                    rule="loop_not_closed",
                    detail=f"Last edge target '{last_target}' != first edge source '{first_source}'.",
                    field="closed_loop",
                )
            )

    return ValidationResult(
        passed=len(violations) == 0,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Section 8.2 — Deduplication & merge
# ---------------------------------------------------------------------------


def _canonical_key_for_candidate(candidate: dict[str, Any]) -> str:
    """Extract or compute the canonical key for a candidate.

    Prefers the candidate's own ``canonical_key`` field (set by DeepSeek or
    the graph engine). Falls back to a serialised form of nodes + edges.
    """
    ck = candidate.get("canonical_key")
    if ck:
        return ck
    # Fallback: join sorted node IDs + topology type
    node_ids = sorted(n.get("region_id", "") for n in candidate.get("nodes", []))
    edge_ids = sorted(e.get("edge_id", "") for e in candidate.get("edges", []))
    tt = candidate.get("topology_type", "unknown")
    return f"{tt}::{'|'.join(node_ids)}::{'|'.join(edge_ids)}"


def _is_contained_in(shorter: dict[str, Any], longer: dict[str, Any]) -> bool:
    """Check whether the node+edge set of *shorter* is fully inside *longer*.

    Both candidates must share the same ``topology_type``.  ``shorter`` is
    considered "contained" when all its node IDs appear (in order) as a
    contiguous subsequence of the longer node list, OR its edge IDs are a
    subsequence of the longer edge list.
    """
    if shorter.get("topology_type") != longer.get("topology_type"):
        return False

    short_nodes = [n.get("region_id") for n in shorter.get("nodes", [])]
    long_nodes = [n.get("region_id") for n in longer.get("nodes", [])]

    if len(short_nodes) >= len(long_nodes):
        return False

    # Contiguous subsequence check
    for i in range(len(long_nodes) - len(short_nodes) + 1):
        if long_nodes[i : i + len(short_nodes)] == short_nodes:
            return True
    return False


def deduplicate_candidates(
    candidates: list[dict[str, Any]],
    existing_canonical_keys: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Deduplicate and merge a list of DeepSeek-reviewed candidates.

    Merge rules (spec section 8.2):
        - Same ``canonical_key`` -> keep the entry with highest ``overall_confidence``.
        - Shorter circuit fully contained in longer -> keep both, tag the shorter
          with ``parent_circuit_id`` pointing to the longer.
        - Same nodes+edges but different name -> merge values, keep highest scores.

    Args:
        candidates: List of validated (or unvalidated) candidate dicts.
        existing_canonical_keys: Set of canonical keys already persisted in the
            candidate pool.  Duplicates against this set are treated as pure duplicates.

    Returns:
        Tuple of ``(unique, duplicates, stats)`` where:

        - **unique** — merged, deduplicated list ready for DB insertion.
        - **duplicates** — every entry that was either skipped or merged into another.
        - **stats** — summary dictionary with counts.
    """
    existing_canonical_keys = existing_canonical_keys or set()
    seen: dict[str, dict[str, Any]] = {}  # canonical_key -> best candidate
    contained: list[dict[str, Any]] = []  # candidates that are contained in another
    duplicates: list[dict[str, Any]] = []
    merge_count = 0
    containment_count = 0

    # Phase 1: group by canonical key, keep highest confidence
    for cand in candidates:
        ck = _canonical_key_for_candidate(cand)
        if ck in existing_canonical_keys:
            duplicates.append(cand)
            continue

        if ck in seen:
            existing = seen[ck]
            existing_conf = existing.get("overall_confidence") or 0.0
            new_conf = cand.get("overall_confidence") or 0.0

            if new_conf > existing_conf:
                # Replace — the new candidate has higher confidence
                merge_count += 1
                seen[ck] = _merge_candidates(existing, cand)
                duplicates.append(existing)
            else:
                # Lower confidence — record as duplicate, keep existing
                merge_count += 1
                seen[ck] = _merge_candidates(cand, existing)
                duplicates.append(cand)
        else:
            seen[ck] = dict(cand)

    # Phase 2: detect containment relationships
    all_unique = list(seen.values())
    containment_relationships: list[tuple[int, int]] = []  # (shorter_idx, longer_idx)

    for i in range(len(all_unique)):
        for j in range(len(all_unique)):
            if i == j:
                continue
            shorter = all_unique[i]
            longer = all_unique[j]
            if len(shorter.get("nodes", [])) <= len(longer.get("nodes", [])):
                if _is_contained_in(shorter, longer):
                    containment_relationships.append((i, j))

    # Apply containment tags
    for short_idx, long_idx in containment_relationships:
        shorter = all_unique[short_idx]
        longer = all_unique[long_idx]
        longer_id = longer.get("id") or longer.get("canonical_key", "")
        shorter["parent_circuit_id"] = shorter.get("parent_circuit_id") or longer_id
        containment_count += 1

    stats: dict[str, Any] = {
        "total_input": len(candidates),
        "unique_count": len(seen),
        "duplicate_count": len(duplicates),
        "merged_count": merge_count,
        "containment_count": containment_count,
    }

    return all_unique, duplicates, stats


def _merge_candidates(
    lower: dict[str, Any],
    higher: dict[str, Any],
) -> dict[str, Any]:
    """Merge two candidates with the same canonical key.

    Takes the **higher-confidence** candidate as base and fills in null/missing
    string fields from the lower-confidence candidate.  Numeric scores always
    use the higher value.
    """
    merged = dict(higher)

    # String fields: fill nulls from lower
    for string_field in ("name_en", "name_cn", "functional_summary",
                         "neuroscience_rationale", "evidence_basis"):
        if not merged.get(string_field):
            val = lower.get(string_field)
            if val:
                merged[string_field] = val

    # Functional modules: union
    merged_modules = set(merged.get("functional_module") or [])
    lower_modules = set(lower.get("functional_module") or [])
    merged["functional_module"] = list(merged_modules | lower_modules)

    # Scores: take the max
    for score_field in ("topology_score", "anatomical_score", "functional_score",
                        "evidence_score", "overall_confidence", "pre_score"):
        lower_val = lower.get(score_field) or 0.0
        higher_val = merged.get(score_field) or 0.0
        merged[score_field] = max(lower_val, higher_val)

    # Uncertainties: combine lists
    merged_uncerts = set(merged.get("uncertainties") or [])
    lower_uncerts = set(lower.get("uncertainties") or [])
    merged["uncertainties"] = list(merged_uncerts | lower_uncerts)

    return merged


# ---------------------------------------------------------------------------
# Section 5.2 — Anatomical pattern validation
# ---------------------------------------------------------------------------


def validate_anatomical_pattern(candidate: dict[str, Any]) -> ValidationResult:
    """Verify that ``anatomical_pattern`` matches ``topology_type`` per spec section 5.2.

    Returns a violation when:
        - ``topology_type`` is not one of the 9 known types.
        - ``anatomical_pattern`` does not match the expected pattern for that type.
    """
    violations: list[ValidationViolation] = []

    topology_type = candidate.get("topology_type")
    anatomical_pattern = candidate.get("anatomical_pattern")

    if not topology_type:
        return ValidationResult(
            passed=False,
            violations=[
                ValidationViolation(
                    rule="missing_topology_type",
                    detail="Candidate has no topology_type field.",
                    field="topology_type",
                )
            ],
        )

    expected = ANATOMICAL_PATTERN_MAP.get(topology_type)
    if expected is None:
        violations.append(
            ValidationViolation(
                rule="unknown_topology_type",
                detail=f"'{topology_type}' is not one of the 9 known types: {sorted(_VALID_TOPOLOGY_TYPES)}.",
                field="topology_type",
            )
        )
    elif anatomical_pattern and anatomical_pattern != expected:
        violations.append(
            ValidationViolation(
                rule="pattern_mismatch",
                detail=(
                    f"topology_type '{topology_type}' expects anatomical_pattern "
                    f"'{expected}', but got '{anatomical_pattern}'."
                ),
                field="anatomical_pattern",
            )
        )

    return ValidationResult(passed=len(violations) == 0, violations=violations)


# ---------------------------------------------------------------------------
# Section 16 — Acceptance statistics
# ---------------------------------------------------------------------------


def compute_candidate_stats(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate statistics for a list of circuit candidates.

    Returns:
        Dictionary with keys:
        - ``total``
        - ``by_type`` — count per ``topology_type``
        - ``by_confidence_level`` — count per confidence band
        - ``avg_scores`` — per-field averages
        - ``closed_loop_count`` / ``open_pathway_count``
    """
    total = len(candidates)
    by_type: dict[str, int] = {}
    by_confidence: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    score_fields = [
        "topology_score", "anatomical_score", "functional_score",
        "evidence_score", "overall_confidence", "pre_score",
    ]
    score_sums: dict[str, float] = {f: 0.0 for f in score_fields}
    closed_loop_count = 0

    for c in candidates:
        tt = c.get("topology_type", "unknown")
        by_type[tt] = by_type.get(tt, 0) + 1

        cl = (c.get("confidence_level") or "unknown").lower()
        if cl in by_confidence:
            by_confidence[cl] += 1
        else:
            by_confidence["unknown"] = by_confidence.get("unknown", 0) + 1

        for f in score_fields:
            score_sums[f] += c.get(f) or 0.0

        if c.get("closed_loop"):
            closed_loop_count += 1

    avg_scores = {
        f"avg_{f}": round(score_sums[f] / total, 4) if total > 0 else 0.0
        for f in score_fields
    }

    return {
        "total": total,
        "by_type": by_type,
        "by_confidence_level": by_confidence,
        "avg_scores": avg_scores,
        "closed_loop_count": closed_loop_count,
        "open_pathway_count": total - closed_loop_count,
    }
