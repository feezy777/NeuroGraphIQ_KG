"""Deterministic canonical start/end region resolution for circuit field completion."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorCircuitRegion, MirrorRegionCircuit
from app.models.promotion import FinalBrainRegion
from app.services.field_completion_registry import get_attributes_dict, get_overlay_value


@dataclass
class CanonicalRegionResolution:
    start_region_id: str | None = None
    end_region_id: str | None = None
    start_region_label: str | None = None
    end_region_label: str | None = None
    method: str = "unresolved"
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, AttributeError):
        return None


def _region_label(candidate: CandidateBrainRegion | None) -> str | None:
    if candidate is None:
        return None
    for attr in ("en_name", "std_name", "raw_name", "cn_name", "region_base_name"):
        val = getattr(candidate, attr, None)
        if val and str(val).strip():
            return str(val).strip()
    return None


def _payload_dict(circuit: Any) -> dict[str, Any]:
    for attr in ("normalized_payload_json", "raw_payload_json"):
        payload = getattr(circuit, attr, None)
        if isinstance(payload, dict):
            return payload
    attrs = get_attributes_dict(circuit)
    return attrs if isinstance(attrs, dict) else {}


def _extract_region_roles_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []
    attrs = payload.get("attributes")
    if isinstance(attrs, dict):
        cr = attrs.get("circuit_regions")
        if isinstance(cr, list):
            roles.extend(x for x in cr if isinstance(x, dict))
        raw = attrs.get("raw")
        if isinstance(raw, dict):
            rr = raw.get("region_roles")
            if isinstance(rr, list):
                roles.extend(x for x in rr if isinstance(x, dict))
    cr2 = payload.get("circuit_regions")
    if isinstance(cr2, list):
        roles.extend(x for x in cr2 if isinstance(x, dict))
    return roles


def _extract_involved_ids(payload: dict[str, Any]) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for key in ("involved_region_candidate_ids",):
        raw = payload.get(key)
        if not isinstance(raw, list):
            attrs = payload.get("attributes")
            if isinstance(attrs, dict):
                raw = attrs.get(key)
        if isinstance(raw, list):
            for item in raw:
                uid = _parse_uuid(item)
                if uid:
                    ids.append(uid)
    return ids


async def resolve_region_candidate_to_canonical(
    session: AsyncSession,
    region_candidate_id: uuid.UUID,
    *,
    source_atlas: str | None = None,
) -> tuple[str | None, str | None, str, float, list[str]]:
    """Return (canonical_id, label, method, confidence, warnings)."""
    warnings: list[str] = []
    candidate = await session.get(CandidateBrainRegion, region_candidate_id)
    if candidate is None:
        return None, None, "unresolved", 0.0, [f"region_candidate_id {region_candidate_id} not found"]

    label = _region_label(candidate)

    stmt = select(FinalBrainRegion.id).where(FinalBrainRegion.candidate_id == region_candidate_id)
    if source_atlas:
        stmt = stmt.where(FinalBrainRegion.source_atlas == source_atlas)
    final_id = (await session.execute(stmt.limit(2))).scalar_one_or_none()
    if final_id is not None:
        return str(final_id), label, "formal_region_lookup", 0.9, warnings

    if source_atlas and candidate.source_atlas != source_atlas:
        warnings.append(
            f"candidate atlas {candidate.source_atlas} differs from circuit source_atlas {source_atlas}"
        )

    # Workbench has no separate canonical_region_id column on candidates; use candidate id as mirror reference.
    return (
        str(candidate.id),
        label,
        "candidate_region_canonical_id",
        0.85,
        warnings + ["no promoted final_brain_regions row; using candidate_brain_regions.id as overlay canonical reference"],
    )


async def _resolve_pair(
    session: AsyncSession,
    start_cid: uuid.UUID,
    end_cid: uuid.UUID,
    *,
    source_atlas: str | None,
    method: str,
    base_confidence: float,
    extra_warnings: list[str],
    evidence: dict[str, Any],
) -> CanonicalRegionResolution:
    start_id, start_label, start_method, start_conf, start_warn = await resolve_region_candidate_to_canonical(
        session, start_cid, source_atlas=source_atlas
    )
    end_id, end_label, end_method, end_conf, end_warn = await resolve_region_candidate_to_canonical(
        session, end_cid, source_atlas=source_atlas
    )
    warnings = list(extra_warnings) + start_warn + end_warn
    if start_id is None or end_id is None:
        return CanonicalRegionResolution(
            method="unresolved",
            confidence=0.0,
            warnings=warnings + ["could not resolve start/end canonical region ids"],
            evidence=evidence,
        )
    conf = min(base_confidence, start_conf, end_conf)
    combined_method = method if start_method == end_method else f"{method}|{start_method}/{end_method}"
    return CanonicalRegionResolution(
        start_region_id=start_id,
        end_region_id=end_id,
        start_region_label=start_label,
        end_region_label=end_label,
        method=combined_method,
        confidence=conf,
        warnings=warnings,
        evidence=evidence,
    )


# Generic anatomical / connector words that carry no distinguishing signal when
# matching a circuit *name* against region labels. Matching on these produces
# false positives (e.g. "…_nucleus_…" matching "Anterior hypothalamic nucleus").
_GENERIC_NAME_TOKENS = frozenset({
    "pathway", "circuit", "loop", "network", "tract", "projection", "projections",
    "connection", "connections", "system", "from", "and", "via", "the", "of", "in",
    "into", "onto", "between", "layer", "part", "region", "regions", "area", "areas",
    "nucleus", "nuclei", "cortex", "cortical", "subcortical", "zone", "division",
    "complex", "dorsal", "ventral", "medial", "lateral", "anterior", "posterior",
    "superior", "inferior", "rostral", "caudal", "left", "right", "deep", "superficial",
    "input", "output", "relay", "hub", "primary", "secondary", "association",
})


def _name_tokens(text: str, *, drop_generic: bool = False) -> list[str]:
    text = text.lower().replace("_", " ").replace("-", " ")
    tokens = [t for t in re.split(r"[\s,;/]+", text) if len(t) > 2]
    if drop_generic:
        tokens = [t for t in tokens if t not in _GENERIC_NAME_TOKENS]
    return tokens


async def _match_regions_by_name(
    session: AsyncSession,
    text: str,
    *,
    source_atlas: str | None,
    limit: int = 2,
) -> list[tuple[uuid.UUID, str]]:
    tokens = _name_tokens(text, drop_generic=True)
    if len(tokens) < 2:
        return []
    q = select(CandidateBrainRegion)
    if source_atlas:
        q = q.where(CandidateBrainRegion.source_atlas == source_atlas)
    candidates = list((await session.execute(q.limit(500))).scalars().all())
    scored: list[tuple[int, uuid.UUID, str]] = []
    for c in candidates:
        label = _region_label(c) or ""
        hay = label.lower()
        score = sum(1 for t in tokens if t in hay)
        if score >= 1:
            scored.append((score, c.id, label))
    scored.sort(key=lambda x: (-x[0], x[2]))
    out: list[tuple[uuid.UUID, str]] = []
    seen: set[uuid.UUID] = set()
    for _, cid, label in scored:
        if cid in seen:
            continue
        seen.add(cid)
        out.append((cid, label))
        if len(out) >= limit:
            break
    return out


_STEP_START_ROLES = frozenset({"source", "start", "input", "origin", "afferent"})
_STEP_END_ROLES = frozenset({"target", "output", "end", "sink", "efferent", "terminal"})


async def _resolve_from_circuit_steps(
    session: AsyncSession,
    circuit_id: uuid.UUID,
    *,
    source_atlas: str | None,
    evidence: dict[str, Any],
) -> CanonicalRegionResolution | None:
    """Resolve start/end from mirror_circuit_steps region assignments (ordered, role-aware).

    Steps carry real region_candidate_ids grounded during extraction, so they are a far
    more reliable source than crude circuit_name token matching. Returns None when fewer
    than two distinct step regions exist (caller falls through to other strategies).
    """
    from app.models.mirror_macro_clinical import MirrorCircuitStep

    stmt = (
        select(MirrorCircuitStep)
        .where(MirrorCircuitStep.circuit_id == circuit_id)
        .order_by(MirrorCircuitStep.step_order)
    )
    steps = list((await session.execute(stmt)).scalars().all())
    rows: list[tuple[int, uuid.UUID, str]] = []
    for idx, s in enumerate(steps):
        cid = _parse_uuid(getattr(s, "region_candidate_id", None))
        if cid is None:
            continue
        order = getattr(s, "step_order", None)
        try:
            order = int(order) if order is not None else idx
        except (TypeError, ValueError):
            order = idx
        role = str(getattr(s, "role", "") or "").strip().lower()
        rows.append((order, cid, role))

    if len(rows) < 2:
        return None
    rows.sort(key=lambda x: x[0])

    start = next((r for r in rows if r[2] in _STEP_START_ROLES), rows[0])
    end = next((r for r in reversed(rows) if r[2] in _STEP_END_ROLES), rows[-1])
    if start[1] == end[1]:
        # Role heuristic collapsed to one region — fall back to first/last by order.
        start, end = rows[0], rows[-1]
    if start[1] == end[1]:
        return None

    evidence["region_candidate_ids"] = [str(r[1]) for r in rows]
    evidence["region_roles"] = [r[2] for r in rows]
    evidence["region_source"] = "mirror_circuit_steps"
    used_roles = start[2] in _STEP_START_ROLES or end[2] in _STEP_END_ROLES
    extra = [] if used_roles else [
        "start/end inferred from step_order; steps did not mark explicit source/target roles"
    ]
    return await _resolve_pair(
        session,
        start[1],
        end[1],
        source_atlas=source_atlas,
        method="circuit_step_regions",
        base_confidence=0.8,
        extra_warnings=extra,
        evidence=evidence,
    )


async def resolve_circuit_canonical_regions(
    session: AsyncSession,
    circuit: MirrorRegionCircuit | Any,
) -> CanonicalRegionResolution:
    """Resolve canonical_start/end from circuit regions (DB + payload), no LLM."""
    source_atlas = getattr(circuit, "source_atlas", None)
    circuit_id = getattr(circuit, "id", None)
    payload = _payload_dict(circuit)
    evidence: dict[str, Any] = {
        "circuit_id": str(circuit_id) if circuit_id else None,
        "circuit_name": getattr(circuit, "circuit_name", None),
        "description": getattr(circuit, "description", None),
        "region_candidate_ids": [],
        "region_roles": [],
    }

    # Priority 1: mirror_circuit_regions table
    region_rows: list[dict[str, Any]] = []
    if circuit_id is not None:
        stmt = (
            select(MirrorCircuitRegion)
            .where(MirrorCircuitRegion.circuit_id == circuit_id)
            .order_by(MirrorCircuitRegion.sort_order)
        )
        db_regions = list((await session.execute(stmt)).scalars().all())
        for cr in db_regions:
            if cr.region_candidate_id:
                region_rows.append({
                    "region_candidate_id": str(cr.region_candidate_id),
                    "role": cr.role,
                    "sort_order": cr.sort_order,
                })

    if not region_rows:
        region_rows = _extract_region_roles_from_payload(payload)

    parsed_rows: list[tuple[int, uuid.UUID, str]] = []
    for row in region_rows:
        cid = _parse_uuid(row.get("region_candidate_id"))
        if cid is None:
            continue
        sort_order = row.get("sort_order")
        try:
            order = int(sort_order) if sort_order is not None else len(parsed_rows)
        except (TypeError, ValueError):
            order = len(parsed_rows)
        role = str(row.get("role") or "participant")
        parsed_rows.append((order, cid, role))

    if len(parsed_rows) >= 2:
        parsed_rows.sort(key=lambda x: x[0])
        start_cid, end_cid = parsed_rows[0][1], parsed_rows[-1][1]
        roles = [r[2] for r in parsed_rows]
        evidence["region_candidate_ids"] = [str(r[1]) for r in parsed_rows]
        evidence["region_roles"] = roles
        extra: list[str] = []
        if all(r in ("participant", "unknown") for r in roles):
            extra.append(
                "direction inferred from sort_order; connectivity direction not explicitly evidenced"
            )
        return await _resolve_pair(
            session,
            start_cid,
            end_cid,
            source_atlas=source_atlas,
            method="candidate_region_canonical_id",
            base_confidence=0.85,
            extra_warnings=extra,
            evidence=evidence,
        )

    # Priority 1.5: mirror_circuit_steps region assignments (ordered, role-aware).
    # These are grounded region_candidate_ids and far more reliable than name matching.
    if circuit_id is not None:
        step_res = await _resolve_from_circuit_steps(
            session, circuit_id, source_atlas=source_atlas, evidence=evidence
        )
        if step_res is not None:
            return step_res

    # Priority 2: involved_region_candidate_ids
    involved = _extract_involved_ids(payload)
    if len(involved) >= 2:
        evidence["region_candidate_ids"] = [str(x) for x in involved]
        return await _resolve_pair(
            session,
            involved[0],
            involved[-1],
            source_atlas=source_atlas,
            method="involved_region_candidate_ids",
            base_confidence=0.75,
            extra_warnings=["direction inferred from involved_region_candidate_ids list order"],
            evidence=evidence,
        )

    # Priority 3: circuit_name
    circuit_name = getattr(circuit, "circuit_name", None) or ""
    name_matches = await _match_regions_by_name(session, circuit_name, source_atlas=source_atlas, limit=2)
    if len(name_matches) >= 2:
        evidence["name_parse_source"] = circuit_name
        return await _resolve_pair(
            session,
            name_matches[0][0],
            name_matches[1][0],
            source_atlas=source_atlas,
            method="name_match",
            base_confidence=0.65,
            extra_warnings=["direction inferred from circuit_name token order; verify manually"],
            evidence=evidence,
        )

    # Priority 4: description
    description = getattr(circuit, "description", None) or ""
    desc_matches = await _match_regions_by_name(session, description, source_atlas=source_atlas, limit=2)
    if len(desc_matches) >= 2:
        evidence["name_parse_source"] = description[:200]
        return await _resolve_pair(
            session,
            desc_matches[0][0],
            desc_matches[1][0],
            source_atlas=source_atlas,
            method="name_match",
            base_confidence=0.55,
            extra_warnings=["direction inferred from description; may be ambiguous"],
            evidence=evidence,
        )

    return CanonicalRegionResolution(
        method="unresolved",
        confidence=0.0,
        warnings=["unable to resolve canonical start/end regions from circuit regions or text"],
        evidence=evidence,
    )


def resolve_source_db_default(circuit: Any) -> tuple[str | None, str, float, list[str]]:
    existing = get_overlay_value(circuit, "source_db")
    if existing not in (None, ""):
        return None, "skipped_existing", 0.0, []
    atlas = getattr(circuit, "source_atlas", None)
    if atlas:
        return str(atlas), "source_db_resolver", 1.0, []
    return "mirror_kg", "source_db_resolver", 0.8, []


def resolve_status_default(circuit: Any) -> tuple[str | None, str, float, list[str]]:
    existing = get_overlay_value(circuit, "status")
    if existing not in (None, ""):
        return None, "skipped_existing", 0.0, []
    mirror_status = getattr(circuit, "mirror_status", None)
    if mirror_status:
        return str(mirror_status), "status_default_resolver", 0.9, []
    return "candidate", "status_default_resolver", 0.8, []
