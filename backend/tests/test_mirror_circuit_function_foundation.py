"""Mirror circuit_function foundation tests (Step 10.6.1 — no DB / no LLM)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.models.mirror_macro_clinical import MirrorCircuitFunction
from app.schemas.mirror_macro_clinical import (
    MirrorCircuitFunctionCreate,
    MirrorCircuitFunctionRead,
    MirrorCircuitFunctionUpdate,
)
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus, MirrorStatus


def test_mirror_circuit_function_model_import():
    assert MirrorCircuitFunction.__tablename__ == "mirror_circuit_functions"


def test_mirror_circuit_function_read_schema_import():
    assert MirrorCircuitFunctionRead is not None


def test_migration_file_contains_mirror_circuit_functions_table():
    migration_path = Path(__file__).resolve().parents[1] / "migrations" / "033_mirror_circuit_functions.sql"
    assert migration_path.is_file()
    sql = migration_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS mirror_circuit_functions" in sql
    for col in (
        "circuit_id",
        "function_term_en",
        "function_term_cn",
        "function_domain",
        "function_role",
        "effect_type",
        "attributes",
    ):
        assert col in sql


def test_read_schema_serializes_decimal_confidence_score():
    now = datetime.now(timezone.utc)
    row = MirrorCircuitFunction(
        id=uuid.uuid4(),
        circuit_id=uuid.uuid4(),
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        function_term_en="memory consolidation",
        function_term_cn="记忆巩固",
        function_domain="memory",
        function_role="associated_with",
        effect_type="modulatory",
        confidence_score=Decimal("0.875"),
        confidence=Decimal("0.91"),
        attributes={"formal_field_overlay": {"function_term_cn": "记忆巩固"}},
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={"formal_field_overlay": {}},
        created_at=now,
        updated_at=now,
    )
    read = MirrorCircuitFunctionRead.model_validate(row)
    payload = read.model_dump(mode="json")
    json.dumps(payload)
    assert payload["confidence_score"] == 0.875
    assert payload["confidence"] == 0.91
    assert isinstance(payload["attributes"], dict)
    assert payload["attributes"]["formal_field_overlay"]["function_term_cn"] == "记忆巩固"


def test_create_schema_governance_defaults():
    payload = MirrorCircuitFunctionCreate(
        circuit_id=uuid.uuid4(),
        granularity_level="macro",
        source_atlas="AAL3",
        function_term_en="sensorimotor integration",
    )
    assert payload.mirror_status == MirrorStatus.llm_suggested
    assert payload.review_status == MirrorReviewStatus.pending
    assert payload.promotion_status == MirrorPromotionStatus.not_promoted


def test_update_schema_accepts_partial_fields():
    payload = MirrorCircuitFunctionUpdate(function_term_cn="感觉运动整合")
    assert payload.function_term_cn == "感觉运动整合"
    assert payload.function_term_en is None


def test_read_schema_includes_governance_and_provenance_fields():
    now = datetime.now(timezone.utc)
    row = MirrorCircuitFunction(
        id=uuid.uuid4(),
        circuit_id=uuid.uuid4(),
        granularity_level="macro",
        source_atlas="AAL3",
        validation_status="rule_checked",
        provenance="llm_extraction_run:abc",
        evidence_text="General knowledge",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        attributes={},
        raw_payload_json={},
        normalized_payload_json={},
        created_at=now,
        updated_at=now,
    )
    read = MirrorCircuitFunctionRead.model_validate(row)
    assert read.validation_status == "rule_checked"
    assert read.provenance == "llm_extraction_run:abc"
    assert read.created_at == now
    assert read.updated_at == now
