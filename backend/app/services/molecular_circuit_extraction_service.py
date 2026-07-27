"""Molecular Circuit Extraction v2 — master orchestrator.

Phases:
  1. Graph build & topology generation (graph engine)
  2. Module classification & pack building
  3. DeepSeek semantic review
  4. Quality gate validation & dedup
  5. Datacenter write (candidate pool)

Reuses existing task infrastructure (cancel/pause/retry) via adapter pattern.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.molecular_circuit_candidate import (
    MirrorMolecularCircuitCandidate,
    MolecularCircuitCandidateRun,
)
from app.schemas.molecular_circuit_extraction import (
    MolecularCircuitExtractionRequest,
    MolecularCircuitProgressResponse,
    MolecularCircuitRunRead,
    MolecularCircuitStartResponse,
)
from app.services.llm_providers import get_llm_provider
from app.services.llm_workflow_cancel_registry import (
    clear_pause_requested,
    is_cancelling,
    is_pause_requested,
    mark_cancelling,
    mark_pause_requested,
)
from app.services.molecular_circuit_graph_engine import (
    GraphEngineConfig,
    build_graph_and_generate_candidates,
)
from app.services.molecular_circuit_module_classifier import classify_regions
from app.services.molecular_circuit_prompt_builder import (
    PackPrompt,
    build_pack_prompt,
    build_system_prompt,
)
from app.services.molecular_circuit_quality_gate import (
    compute_candidate_stats,
    deduplicate_candidates,
    validate_circuit,
)
from app.services.molecular_circuit_datacenter_validator import (
    audit_existing_enums,
    validate_datacenter_record,
)
from app.services.molecular_circuit_datacenter_writer import write_circuit_to_datacenter

logger = logging.getLogger(__name__)

PROMPT_VERSION = "molecular_circuit_v2_en_v1"
QUALITY_GATE_VERSION = "v1"

PHASES = [
    "graph_loading",
    "topology_generation",
    "module_classification",
    "pack_building",
    "llm_review",
    "quality_gate",
    "datacenter_write",
    "summary",
]


@dataclass
class ExtractionProgress:
    phase: str = "pending"
    progress_percent: float = 0.0
    total_candidates: int = 0
    total_packs: int = 0
    completed_packs: int = 0
    failed_packs: int = 0
    total_passed: int = 0
    total_failed: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0
    datacenter_written: int = 0
    datacenter_failed: int = 0
    errors: list[str] = field(default_factory=list)
    phase_stats: dict[str, Any] = field(default_factory=dict)


async def _update_run_progress(
    session: AsyncSession,
    run_id: uuid.UUID,
    progress: ExtractionProgress,
) -> None:
    """Persist progress to the run record."""
    run = await session.get(MolecularCircuitCandidateRun, run_id)
    if run is None:
        return
    run.progress_json = {
        "phase": progress.phase,
        "progress_percent": progress.progress_percent,
        "total_candidates": progress.total_candidates,
        "total_packs": progress.total_packs,
        "completed_packs": progress.completed_packs,
        "failed_packs": progress.failed_packs,
        "total_passed": progress.total_passed,
        "total_failed": progress.total_failed,
        "high_confidence": progress.high_confidence,
        "medium_confidence": progress.medium_confidence,
        "low_confidence": progress.low_confidence,
        "datacenter_written": progress.datacenter_written,
        "datacenter_failed": progress.datacenter_failed,
        "errors": progress.errors,
    }
    session.add(run)
    await session.commit()


async def _run_phase(
    session: AsyncSession,
    run_id: uuid.UUID,
    progress: ExtractionProgress,
    phase_name: str,
    phase_pct: float,
) -> None:
    """Advance to a named phase and persist progress."""
    progress.phase = phase_name
    progress.progress_percent = phase_pct
    await _update_run_progress(session, run_id, progress)
    logger.info("[molecular-circuit][run=%s] Phase: %s (%.0f%%)", run_id, phase_name, phase_pct)


async def execute_molecular_circuit_extraction(
    run_id: uuid.UUID,
    request_dict: dict[str, Any],
) -> None:
    """Background execution entry point.

    Parameters
    ----------
    run_id : uuid.UUID
        The persisted run record ID.
    request_dict : dict
        Serialized MolecularCircuitExtractionRequest.
    """
    from app.database import AsyncSessionLocal

    request = MolecularCircuitExtractionRequest.model_validate(request_dict)
    progress = ExtractionProgress()

    # DB session for the full run
    async with AsyncSessionLocal() as session:
        try:
            # ── Mark running ──
            run = await session.get(MolecularCircuitCandidateRun, run_id)
            if run is None:
                logger.error("[molecular-circuit] run %s not found", run_id)
                return
            run.status = "running"
            run.provider = request.provider
            run.model_name = request.model_name
            session.add(run)
            await session.commit()

            # ── Phase 1: Build graph & generate topologies ──
            await _run_phase(session, run_id, progress, "graph_loading", 5.0)

            engine_config = GraphEngineConfig(
                max_directed_cycles_3=10000,
                max_feedforward_loops_3=10000,
                max_reciprocal_pairs_3=5000,
                max_convergent_motifs=5000,
                max_divergent_motifs=5000,
                max_relay_pathways=20000,
                max_closed_loops_4_8=5000,
                max_cortico_subcortical_loops=5000,
                max_cross_module_loops=5000,
            )
            graph_result = await build_graph_and_generate_candidates(session, engine_config)

            progress.total_candidates = len(graph_result.candidates)
            await _run_phase(
                session, run_id, progress, "topology_generation", 15.0
            )

            # ── Phase 2: Module classification ──
            await _run_phase(session, run_id, progress, "module_classification", 20.0)
            all_candidate_ids = list(graph_result.nodes.keys())
            region_modules = await classify_regions(session, [uuid.UUID(rid) for rid in all_candidate_ids])

            # ── Phase 3: Build packs & call DeepSeek ──
            await _run_phase(session, run_id, progress, "pack_building", 25.0)

            # Simple packing: chunk candidates
            pack_size = request.pack_candidate_limit
            candidates_list = graph_result.candidates
            packs = [
                candidates_list[i : i + pack_size]
                for i in range(0, len(candidates_list), pack_size)
            ]
            progress.total_packs = len(packs)
            await _update_run_progress(session, run_id, progress)

            system_prompt = build_system_prompt()
            provider = get_llm_provider(request.provider)
            resolved_model = request.model_name or "deepseek-v4-pro"

            all_reviewed: list[dict[str, Any]] = []
            valid_predicates: set[str] = {"projection", "association", "commissural", "intrinsic"}
            valid_statuses = audit_existing_enums()

            for pack_idx, pack_candidates in enumerate(packs):
                # Pause check
                if is_pause_requested(run_id):
                    run.status = "paused"
                    session.add(run)
                    await session.commit()
                    # Block until resumed (polling)
                    while is_pause_requested(run_id):
                        import asyncio
                        await asyncio.sleep(2)
                    clear_pause_requested(run_id)
                    run.status = "running"
                    session.add(run)
                    await session.commit()

                # Cancel check
                if is_cancelling(run_id):
                    run.status = "cancelled"
                    session.add(run)
                    await session.commit()
                    return

                try:
                    # Convert TopologyCandidate objects to prompt-ready dicts with
                    # 'nodes' (list of region dicts) and 'edges' (list of edge dicts)
                    prompt_candidates = _to_prompt_candidates(
                        pack_candidates, graph_result, region_modules
                    )
                    relevant_edges = _extract_edges_for_pack(graph_result, pack_candidates)
                    region_basics = _extract_region_basics(graph_result)

                    pack_prompt = build_pack_prompt(
                        pack_candidates=prompt_candidates,
                        relevant_edges=relevant_edges,
                        region_basics=region_basics,
                        functional_labels=region_modules,
                        module_name="all_modules",
                        max_circuits=100,
                    )

                    response = await provider.complete_json(
                        model=resolved_model,
                        system_prompt=system_prompt,
                        user_prompt=pack_prompt.user_prompt,
                        temperature=request.temperature if hasattr(request, 'temperature') else 0.5,
                        max_tokens=16384,
                        timeout_seconds=180,
                    )

                    if response.parsed_json and isinstance(response.parsed_json, list):
                        reviewed = response.parsed_json
                    elif isinstance(response.parsed_json, dict):
                        reviewed = response.parsed_json.get("circuits", [])
                    else:
                        reviewed = []

                    # Debug: save first pack response for inspection
                    if pack_idx == 0:
                        progress.phase_stats["debug_first_pack"] = {
                            "response_type": type(response.parsed_json).__name__,
                            "reviewed_count": len(reviewed),
                            "raw_text_preview": (response.raw_text or "")[:1000] if hasattr(response, 'raw_text') else "N/A",
                            "parsed_json_is_none": response.parsed_json is None,
                            "first_circuit": reviewed[0] if reviewed else None,
                        }
                        if reviewed:
                            c0 = reviewed[0]
                            progress.phase_stats["debug_first_keys"] = list(c0.keys()) if isinstance(c0, dict) else str(type(c0))
                            progress.phase_stats["debug_first_nodes_sample"] = str(c0.get("nodes", [])[:2]) if isinstance(c0, dict) else "N/A"
                            progress.phase_stats["debug_first_edges_sample"] = str(c0.get("edges", [])[:2]) if isinstance(c0, dict) else "N/A"

                    # Quality gate: validate each reviewed candidate
                    for candidate in reviewed:
                        validation = validate_circuit(
                            candidate,
                            graph_nodes=set(graph_result.nodes.keys()),
                            graph_edges=graph_result.edges,
                        )
                        candidate["_validation"] = {"passed": validation.passed}
                        if not validation.passed:
                            candidate["_validation"]["violations"] = [
                                {"rule": v.rule, "detail": v.detail} for v in validation.violations
                            ]
                            progress.total_failed += 1
                        else:
                            progress.total_passed += 1

                    all_reviewed.extend(reviewed)
                    progress.completed_packs += 1

                except Exception as exc:
                    logger.exception("[molecular-circuit] pack %s failed", pack_idx)
                    progress.failed_packs += 1
                    progress.errors.append(f"pack {pack_idx}: {exc}")

                await _update_run_progress(session, run_id, progress)

            # ── Phase 4: Dedup ──
            await _run_phase(session, run_id, progress, "quality_gate", 75.0)
            existing_keys = await _load_existing_canonical_keys(session)
            unique_candidates, duplicates, dedup_stats = deduplicate_candidates(
                all_reviewed, existing_keys
            )

            # ── Phase 5: Write to datacenter ──
            await _run_phase(session, run_id, progress, "datacenter_write", 85.0)

            candidate_regions = await _load_candidate_regions(
                session, [uuid.UUID(rid) for rid in all_candidate_ids]
            )

            for candidate in unique_candidates:
                if not candidate.get("_validation", {}).get("passed", False):
                    continue
                try:
                    result = await write_circuit_to_datacenter(
                        session=session,
                        circuit=candidate,
                        candidate_regions=candidate_regions,
                        extraction_run_id=run_id,
                        pack_id=0,  # simplified
                        prompt_version=PROMPT_VERSION,
                        model=resolved_model,
                        quality_gate_version=QUALITY_GATE_VERSION,
                    )
                    progress.datacenter_written += result.written
                    progress.datacenter_failed += result.failed
                except Exception as exc:
                    logger.exception("[molecular-circuit] datacenter write failed: %s", exc)
                    progress.datacenter_failed += 1

            # ── Summary ──
            await _run_phase(session, run_id, progress, "summary", 95.0)

            stats = compute_candidate_stats(unique_candidates)
            progress.high_confidence = sum(
                1 for c in unique_candidates
                if c.get("confidence_level") == "high"
            )
            progress.medium_confidence = sum(
                1 for c in unique_candidates
                if c.get("confidence_level") == "medium"
            )
            progress.low_confidence = sum(
                1 for c in unique_candidates
                if c.get("confidence_level") == "low"
            )

            run.status = "completed"
            run.total_raw_topologies = len(candidates_list)
            run.total_passed = progress.total_passed
            run.total_failed = progress.total_failed
            run.high_confidence = progress.high_confidence
            run.medium_confidence = progress.medium_confidence
            run.low_confidence = progress.low_confidence
            run.result_summary_json = {
                "candidate_stats": stats,
                "dedup_stats": dedup_stats,
                "datacenter_written": progress.datacenter_written,
                "datacenter_failed": progress.datacenter_failed,
            }
            session.add(run)
            await session.commit()

            progress.progress_percent = 100.0
            logger.info(
                "[molecular-circuit][run=%s] COMPLETED. candidates=%s passed=%s written=%s",
                run_id, len(candidates_list), progress.total_passed, progress.datacenter_written,
            )

        except Exception as exc:
            logger.exception("[molecular-circuit][run=%s] FAILED", run_id)
            try:
                run = await session.get(MolecularCircuitCandidateRun, run_id)
                if run:
                    run.status = "failed"
                    run.result_summary_json = {"error": str(exc)}
                    session.add(run)
                    await session.commit()
            except Exception:
                pass


def _to_prompt_candidates(
    pack_candidates: list,
    graph_result,
    region_modules: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Convert TopologyCandidate objects to prompt-ready dicts with
    'nodes' (list of region dicts) and 'edges' (list of edge dicts)
    so the DeepSeek prompt contains real topology data."""

    result: list[dict[str, Any]] = []
    for cand in pack_candidates:
        if hasattr(cand, 'to_dict'):
            d = cand.to_dict()
        elif hasattr(cand, '__dict__'):
            d = {k: v for k, v in cand.__dict__.items() if not k.startswith('_')}
        else:
            d = dict(cand)

        # Build nodes list from node_ids
        nodes: list[dict[str, Any]] = []
        for nid in d.get("node_ids", []):
            node_info = graph_result.nodes.get(nid)
            nodes.append({
                "region_id": nid,
                "region_name": node_info.name_en if node_info else nid,
                "name_cn": node_info.name_cn if node_info else "",
                "functional_labels": region_modules.get(nid, []),
            })

        # Build edges list from edge_ids
        edges: list[dict[str, Any]] = []
        for eid in d.get("edge_ids", []):
            edge_info = graph_result.edges.get(eid)
            if edge_info:
                edges.append({
                    "edge_id": eid,
                    "source_id": edge_info.source_id,
                    "target_id": edge_info.target_id,
                    "connection_type": edge_info.connection_type or "",
                    "confidence": edge_info.confidence or 0.0,
                    "directionality": edge_info.directionality or "directed",
                })

        result.append({
            "canonical_key": d.get("canonical_key", ""),
            "topology_type": d.get("topology_type", "unknown"),
            "anatomical_pattern": d.get("anatomical_pattern", "unknown"),
            "closed_loop": d.get("is_closed", False),
            "nodes": nodes,
            "edges": edges,
            "pre_score": d.get("pre_score", 0.0),
            "node_count": len(nodes),
            "edge_count": len(edges),
        })
    return result


def _extract_edges_for_pack(
    graph_result, pack_candidates: list
) -> list[dict[str, Any]]:
    """Extract relevant edge details for a pack of candidates."""
    seen_edges: set[str] = set()
    edges_list: list[dict[str, Any]] = []
    for c in pack_candidates:
        edge_ids = getattr(c, "edge_ids", []) or []
        for eid in edge_ids:
            if eid in seen_edges:
                continue
            seen_edges.add(eid)
            edge = graph_result.edges.get(eid)
            if edge:
                edges_list.append({
                    "edge_id": eid,
                    "source_id": str(edge.source_id),
                    "target_id": str(edge.target_id),
                    "connection_type": edge.connection_type,
                    "confidence": edge.confidence,
                    "evidence_count": edge.evidence_count,
                    "directionality": edge.directionality,
                })
    return edges_list


def _extract_region_basics(graph_result) -> list[dict[str, Any]]:
    """Extract basic region info for prompt context."""
    return [
        {
            "region_id": rid,
            "name_en": node.name_en or rid,
            "name_cn": node.name_cn or "",
            "functional_domains": node.functional_domains or [],
        }
        for rid, node in graph_result.nodes.items()
    ]


async def _load_existing_canonical_keys(session: AsyncSession) -> set[str]:
    """Load existing canonical keys to prevent duplicate writes."""
    rows = await session.execute(
        select(MirrorMolecularCircuitCandidate.canonical_key)
    )
    return set(rows.scalars().all())


async def _load_candidate_regions(
    session: AsyncSession, candidate_ids: list[uuid.UUID]
) -> dict[str, Any]:
    """Load CandidateBrainRegion records for label resolution."""
    from app.models.candidate import CandidateBrainRegion

    result: dict[str, Any] = {}
    rows = await session.execute(
        select(CandidateBrainRegion).where(
            CandidateBrainRegion.id.in_(candidate_ids)
        )
    )
    for row in rows.scalars().all():
        result[str(row.id)] = row
    return result


# ── CRUD helpers ──


async def create_extraction_run(
    session: AsyncSession,
    request: MolecularCircuitExtractionRequest,
) -> MolecularCircuitCandidateRun:
    """Create a pending extraction run record."""
    run = MolecularCircuitCandidateRun(
        id=uuid.uuid4(),
        status="pending",
        provider=request.provider,
        model_name=request.model_name,
        candidate_count=574,
        pack_count=None,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_extraction_run(
    session: AsyncSession, run_id: uuid.UUID
) -> MolecularCircuitCandidateRun | None:
    return await session.get(MolecularCircuitCandidateRun, run_id)


async def list_extraction_runs(
    session: AsyncSession,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MolecularCircuitCandidateRun], int]:
    from sqlalchemy import func

    q = select(MolecularCircuitCandidateRun)
    if status:
        q = q.where(MolecularCircuitCandidateRun.status == status)
    count_q = select(func.count()).select_from(q.subquery())
    total = (await session.execute(count_q)).scalar_one()
    q = q.order_by(MolecularCircuitCandidateRun.created_at.desc()).offset(offset).limit(limit)
    rows = (await session.execute(q)).scalars().all()
    return list(rows), total


async def cancel_extraction_run(
    session: AsyncSession, run_id: uuid.UUID
) -> MolecularCircuitCandidateRun | None:
    run = await session.get(MolecularCircuitCandidateRun, run_id)
    if run is None:
        return None
    mark_cancelling(run_id)
    run.status = "cancelled"
    session.add(run)
    await session.commit()
    return run


async def pause_extraction_run(
    session: AsyncSession, run_id: uuid.UUID
) -> MolecularCircuitCandidateRun | None:
    run = await session.get(MolecularCircuitCandidateRun, run_id)
    if run is None:
        return None
    mark_pause_requested(run_id)
    run.status = "pause_requested"
    session.add(run)
    await session.commit()
    return run


async def resume_extraction_run(
    session: AsyncSession, run_id: uuid.UUID
) -> MolecularCircuitCandidateRun | None:
    run = await session.get(MolecularCircuitCandidateRun, run_id)
    if run is None:
        return None
    clear_pause_requested(run_id)
    run.status = "running"
    session.add(run)
    await session.commit()
    return run


async def get_extraction_progress(
    session: AsyncSession, run_id: uuid.UUID
) -> MolecularCircuitProgressResponse:
    run = await session.get(MolecularCircuitCandidateRun, run_id)
    if run is None:
        raise ValueError(f"Run {run_id} not found")
    pj = run.progress_json or {}
    return MolecularCircuitProgressResponse(
        run_id=run.id,
        status=run.status,
        phase=pj.get("phase", "unknown"),
        progress_percent=float(pj.get("progress_percent", 0)),
        phase_stats=pj,
    )
