"""Unit tests for circuit pack full-field write helpers."""

from __future__ import annotations

import uuid

from app.schemas.mirror_kg import MirrorStatus
from app.services.llm_circuit_pack_service import (
    _build_circuit_orm,
    _build_function_orm,
    _build_step_orm,
    _meta_from_candidate,
    _normalize_circuit_type,
)


def test_meta_from_candidate_object() -> None:
    class _C:
        granularity_level = "molecular_attr"
        granularity_family = "molecular_attr"
        source_atlas = "Allen_HBA_2012"
        source_version = "v1"
        resource_id = uuid.uuid4()
        batch_id = uuid.uuid4()

    meta = _meta_from_candidate(_C())
    assert meta["granularity_level"] == "molecular_attr"
    assert meta["source_atlas"] == "Allen_HBA_2012"
    assert meta["source_version"] == "v1"


def test_build_circuit_orm_covers_datacenter_fields() -> None:
    mid = uuid.uuid4()
    cdata = {
        "circuit_name": "hippocampus_to_entorhinal_memory",
        "name_cn": "海马-内嗅记忆回路",
        "circuit_type": "memory_related",
        "function_association": "memory encoding",
        "description": "classic trisynaptic path",
        "confidence": 0.72,
        "circuit_strength": 0.7,
        "evidence_text": "Supported by known hippocampal circuitry",
        "uncertainty_reason": "layer specificity incomplete",
        "member_region_ids": [str(mid)],
        "steps": [],
    }
    meta = {
        "granularity_level": "molecular_attr",
        "granularity_family": "molecular_attr",
        "source_atlas": "Allen_HBA_2012",
        "source_version": "v1",
        "resource_id": uuid.uuid4(),
        "batch_id": uuid.uuid4(),
    }
    circuit = _build_circuit_orm(
        cdata=cdata,
        member_rids=[mid],
        meta=meta,
        created_by="test",
    )
    assert circuit.mirror_status == MirrorStatus.llm_suggested
    assert circuit.evidence_text.startswith("Supported")
    assert circuit.uncertainty_reason
    assert circuit.granularity_family == "molecular_attr"
    assert circuit.source_version == "v1"
    assert circuit.resource_id == meta["resource_id"]
    assert circuit.batch_id == meta["batch_id"]
    assert circuit.canonical_start_region_id is None
    assert circuit.raw_payload_json.get("circuit_name") == cdata["circuit_name"]
    assert circuit.created_by == "test"


def test_build_step_and_function_inherit_provenance() -> None:
    mid = uuid.uuid4()
    circuit = _build_circuit_orm(
        cdata={
            "circuit_name": "a_to_b_sensory",
            "name_cn": "感觉回路",
            "circuit_type": "sensory_circuit",
            "confidence": 0.5,
            "evidence_text": "pair connection",
            "uncertainty_reason": "weak",
        },
        member_rids=[mid],
        meta={
            "granularity_level": "molecular_attr",
            "granularity_family": "molecular_attr",
            "source_atlas": "Allen_HBA_2012",
            "source_version": "v1",
            "resource_id": None,
            "batch_id": None,
        },
        created_by="test",
    )
    step = _build_step_orm(
        circuit=circuit,
        sdata={
            "step_order": 1,
            "step_name": "source",
            "step_type": "region",
            "role": "source",
            "description": "origin",
            "confidence": 0.5,
            "evidence_text": "step evidence",
        },
        region_candidate_id=mid,
    )
    fn = _build_function_orm(
        circuit=circuit,
        fdata={
            "function_term_en": "sensory relay",
            "function_term_cn": "感觉中继",
            "function_domain": "sensory",
            "function_role": "transmission",
            "confidence": 0.4,
            "evidence_text": "fn evidence",
        },
    )
    assert step.granularity_family == "molecular_attr"
    assert step.source_atlas == "Allen_HBA_2012"
    assert step.evidence_text == "step evidence"
    assert step.mirror_status == MirrorStatus.llm_suggested
    assert fn.evidence_text == "fn evidence"
    assert fn.granularity_family == "molecular_attr"


def test_normalize_circuit_type_maps_aliases() -> None:
    assert _normalize_circuit_type("memory_circuit") == "memory_related"
    assert _normalize_circuit_type("sensory_circuit") == "sensory_circuit"
    assert _normalize_circuit_type("") == "uncertain_circuit"
