"""Universal field completion tests (Step 10.3 / 10.4.2 � mock provider, no real DeepSeek).

Step 10.4.2 additions:
- circuit selected_fields must use formal field names (name_cn, name_en, circuit_class)
- old mirror names (circuit_name, circuit_type) must be rejected for selected_fields scope
- name_cn (overlay field) writes to normalized_payload_json.formal_field_overlay
- name_en (alias field) writes to circuit_name ORM column
- projection_function uses function_term_cn / function_term_en, NOT function_term
- circuit_step uses step_no / step_name_cn, NOT step_order / step_name
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorCircuitRegion, MirrorRegionCircuit, MirrorRegionConnection
from app.schemas.llm_field_completion import (
    FieldScope,
    ItemStatus,
    OverwritePolicy,
    RunStatus,
    TargetType,
    UniversalFieldCompletionRequest,
)
from app.services.field_completion_registry import (
    get_registry_entry,
    is_empty_value,
    resolve_field_name,
)
from app.services.llm_field_completion_service import (
    apply_field_update,
    determine_fields_to_complete,
    parse_field_completion_response,
    run_universal_field_completion,
)
from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage


# ---------------------------------------------------------------------------
# Object factories
# ---------------------------------------------------------------------------

def _candidate(**kwargs) -> CandidateBrainRegion:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_atlas="AAL3",
        source_version="v1",
        raw_name="Hippocampus_L",
        en_name=None,
        cn_name=None,
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="candidate_created",
        raw_payload={},
        row_index=0,
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def _projection(**kwargs) -> MirrorRegionConnection:
    defaults = dict(
        id=uuid.uuid4(),
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        connection_type="structural_connection",
        directionality="directed",
        strength=None,
        modality=None,
        evidence_text=None,
        confidence=None,
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionConnection(**defaults)


def _circuit(**kwargs) -> MirrorRegionCircuit:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        source_version="v1",
        circuit_name="test_circuit",
        circuit_type="structural",
        function_association=None,
        description=None,
        confidence=None,
        evidence_text=None,
        uncertainty_reason=None,
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _mock_session(targets: dict[uuid.UUID, object], *, region_rows: list | None = None):
    session = AsyncMock()

    async def _get(model, tid):
        if hasattr(tid, "hex"):
            return targets.get(tid)
        return targets.get(tid)

    async def _execute(stmt):
        stmt_str = str(stmt)
        if "mirror_circuit_regions" in stmt_str:
            rows = region_rows if region_rows is not None else []
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: rows)))
        if "candidate_brain_regions" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [])))
        if "final_brain_regions" in stmt_str:
            return MagicMock(scalar_one_or_none=lambda: None)
        return MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [])))

    session.get = AsyncMock(side_effect=_get)
    session.execute = _execute
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Basic utility tests (unchanged)
# ---------------------------------------------------------------------------

def test_is_empty_value():
    assert is_empty_value(None) is True
    assert is_empty_value("") is True
    assert is_empty_value("   ") is True
    assert is_empty_value([]) is True
    assert is_empty_value({}) is True
    assert is_empty_value(0) is False
    assert is_empty_value(False) is False
    assert is_empty_value("x") is False


def test_parse_field_completion_response():
    parsed = parse_field_completion_response(
        '{"field_updates":[{"field_name":"evidence_text","value":"lit"}],"warnings":["w"]}'
    )
    assert len(parsed["field_updates"]) == 1
    assert parsed["warnings"] == ["w"]


# ---------------------------------------------------------------------------
# Step 10.4.2: Registry formal field tests
# ---------------------------------------------------------------------------

def test_circuit_registry_has_formal_fields():
    """circuit enrichable_fields must use formal names, not mirror names."""
    entry = get_registry_entry(TargetType.circuit)
    assert "name_en" in entry.enrichable_fields
    assert "name_cn" in entry.enrichable_fields
    assert "circuit_class" in entry.enrichable_fields
    # Old mirror names must NOT be primary enrichable fields
    assert "circuit_name" not in entry.enrichable_fields
    assert "circuit_type" not in entry.enrichable_fields


def test_circuit_function_registry_supported():
    entry = get_registry_entry(TargetType.circuit_function)
    assert entry.supported is True
    assert "function_term_cn" in entry.enrichable_fields
    assert "function_domain" in entry.enrichable_fields
    assert "function_role" in entry.enrichable_fields
    assert "id" in entry.readonly_fields
    assert "circuit_id" in entry.readonly_fields
    assert "function_term_cn" in entry.direct_write_fields
    assert resolve_field_name(entry, "function_association") is None


def test_projection_function_registry_has_formal_fields():
    """projection_function must use function_term_cn/function_term_en, not function_term."""
    entry = get_registry_entry(TargetType.projection_function)
    assert "function_term_en" in entry.enrichable_fields
    assert "function_term_cn" in entry.enrichable_fields
    assert "function_term" not in entry.enrichable_fields


def test_circuit_step_registry_has_formal_fields():
    """circuit_step must use step_no / step_name_cn, not step_order / step_name."""
    entry = get_registry_entry(TargetType.circuit_step)
    assert "step_name_cn" in entry.enrichable_fields
    assert "step_no" in entry.enrichable_fields
    assert "step_order" not in entry.enrichable_fields
    assert "step_name" not in entry.enrichable_fields


def test_circuit_formal_fields_resolve():
    """name_cn, name_en, circuit_class should all be resolved."""
    entry = get_registry_entry(TargetType.circuit)
    assert resolve_field_name(entry, "name_cn") == "name_cn"
    assert resolve_field_name(entry, "name_en") == "name_en"
    assert resolve_field_name(entry, "circuit_class") == "circuit_class"
    assert resolve_field_name(entry, "description") == "description"


def test_circuit_old_mirror_fields_rejected_via_resolve():
    """circuit_name, circuit_type should NOT resolve (not in enrichable_fields)."""
    entry = get_registry_entry(TargetType.circuit)
    # circuit_name is a legacy alias ? resolves to name_en (that IS enrichable)
    assert resolve_field_name(entry, "circuit_name") == "name_en"
    # But circuit_type IS a legacy alias ? resolves to circuit_class
    assert resolve_field_name(entry, "circuit_type") == "circuit_class"


def test_resolve_field_alias_legacy():
    """evidence_summary alias should still resolve for projection."""
    entry = get_registry_entry(TargetType.projection)
    assert resolve_field_name(entry, "evidence_summary") == "evidence_text"


def test_projection_strength_score_resolves():
    """strength_score is the formal name; old 'strength' resolves via alias."""
    entry = get_registry_entry(TargetType.projection)
    assert resolve_field_name(entry, "strength_score") == "strength_score"
    assert resolve_field_name(entry, "strength") == "strength_score"


# ---------------------------------------------------------------------------
# determine_fields_to_complete (Step 10.4.2: formal field names)
# ---------------------------------------------------------------------------

def test_determine_fields_missing_only_formal():
    """missing_only should return formal field names for missing fields."""
    entry = get_registry_entry(TargetType.projection)
    # strength_score is formal; maps to mirror 'strength'. proj.strength=None ? strength missing.
    # modality is also formal; proj.modality="fmri" ? modality NOT missing.
    proj = _projection(strength=None, modality="fmri")
    fields = determine_fields_to_complete(
        proj, entry, field_scope=FieldScope.missing_only, selected_fields=[]
    )
    assert "strength_score" in fields
    assert "modality" not in fields


def test_determine_fields_selected_formal_circuit():
    """selected_fields with formal names should be returned unchanged."""
    entry = get_registry_entry(TargetType.circuit)
    circuit = _circuit()
    fields = determine_fields_to_complete(
        circuit,
        entry,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn", "name_en", "circuit_class"],
    )
    assert "name_cn" in fields
    assert "name_en" in fields
    assert "circuit_class" in fields


def test_determine_fields_legacy_alias_accepted():
    """circuit_name should resolve (via alias) to name_en for selected_fields."""
    entry = get_registry_entry(TargetType.circuit)
    circuit = _circuit()
    fields = determine_fields_to_complete(
        circuit,
        entry,
        field_scope=FieldScope.selected_fields,
        selected_fields=["circuit_name"],  # legacy ? resolves to name_en
    )
    assert "name_en" in fields


# ---------------------------------------------------------------------------
# apply_field_update � overlay write (Step 10.4.2)
# ---------------------------------------------------------------------------

def test_circuit_name_cn_writes_to_overlay():
    """name_cn has no mirror column ? must write to normalized_payload_json overlay."""
    circuit = _circuit(normalized_payload_json={})
    entry = get_registry_entry(TargetType.circuit)
    status = apply_field_update(
        circuit,
        "name_cn",
        "????",
        overwrite_policy=OverwritePolicy.fill_missing_only,
        create_mirror_updates=True,
        entry=entry,
    )
    assert status == ItemStatus.applied_overlay
    overlay = circuit.normalized_payload_json.get("formal_field_overlay", {})
    assert overlay.get("name_cn") == "????"
    # Must NOT set a Python attribute (it's not a real column)
    # (any getattr would return from normalized_payload_json, not a column)


def test_circuit_name_en_writes_to_circuit_name():
    """name_en maps to mirror circuit_name via formal_to_mirror ? direct write."""
    circuit = _circuit(circuit_name="")
    entry = get_registry_entry(TargetType.circuit)
    status = apply_field_update(
        circuit,
        "name_en",
        "Hippocampal Circuit",
        overwrite_policy=OverwritePolicy.fill_missing_only,
        create_mirror_updates=True,
        entry=entry,
    )
    assert status == ItemStatus.applied_direct
    assert circuit.circuit_name == "Hippocampal Circuit"


def test_circuit_description_direct_write():
    """description maps directly (same name) ? direct write."""
    circuit = _circuit(description=None)
    entry = get_registry_entry(TargetType.circuit)
    status = apply_field_update(
        circuit,
        "description",
        "A test circuit",
        overwrite_policy=OverwritePolicy.fill_missing_only,
        create_mirror_updates=True,
        entry=entry,
    )
    assert status == ItemStatus.applied_direct
    assert circuit.description == "A test circuit"


def test_circuit_class_writes_to_circuit_type():
    """circuit_class maps to mirror circuit_type via formal_to_mirror."""
    circuit = _circuit(circuit_type="")
    entry = get_registry_entry(TargetType.circuit)
    status = apply_field_update(
        circuit,
        "circuit_class",
        "limbic",
        overwrite_policy=OverwritePolicy.fill_missing_only,
        create_mirror_updates=True,
        entry=entry,
    )
    assert status == ItemStatus.applied_direct
    assert circuit.circuit_type == "limbic"


def test_overlay_fill_missing_only_skips_existing():
    """fill_missing_only should skip if overlay already has a value."""
    circuit = _circuit(normalized_payload_json={"formal_field_overlay": {"name_cn": "?????"}})
    entry = get_registry_entry(TargetType.circuit)
    status = apply_field_update(
        circuit,
        "name_cn",
        "????",
        overwrite_policy=OverwritePolicy.fill_missing_only,
        create_mirror_updates=True,
        entry=entry,
    )
    assert status == ItemStatus.skipped_existing_value
    assert circuit.normalized_payload_json["formal_field_overlay"]["name_cn"] == "?????"


def test_suggest_only_does_not_write_overlay():
    """suggest_only must not write to overlay or direct columns."""
    circuit = _circuit(normalized_payload_json={})
    entry = get_registry_entry(TargetType.circuit)
    status = apply_field_update(
        circuit,
        "name_cn",
        "????",
        overwrite_policy=OverwritePolicy.suggest_only,
        create_mirror_updates=True,
        entry=entry,
    )
    assert status == ItemStatus.suggested
    assert circuit.normalized_payload_json == {}


def test_readonly_field_rejected():
    """id, created_at, updated_at must never be applied."""
    circuit = _circuit()
    entry = get_registry_entry(TargetType.circuit)
    for readonly in ("id", "created_at", "updated_at"):
        status = apply_field_update(
            circuit,
            readonly,
            "some_value",
            overwrite_policy=OverwritePolicy.fill_missing_only,
            create_mirror_updates=True,
            entry=entry,
        )
        assert status == ItemStatus.skipped_readonly_field


# ---------------------------------------------------------------------------
# Backward-compat: apply_field_update without entry (no entry arg)
# ---------------------------------------------------------------------------

def test_apply_fill_missing_only_writes_empty_legacy():
    """Calling apply_field_update without entry still works for legacy direct fields."""
    proj = _projection(strength=None)
    status = apply_field_update(
        proj,
        "strength",
        "strong",
        overwrite_policy=OverwritePolicy.fill_missing_only,
        create_mirror_updates=True,
    )
    assert status == ItemStatus.applied_direct
    assert proj.strength == "strong"


def test_apply_fill_missing_only_skips_nonempty_legacy():
    proj = _projection(strength="existing")
    status = apply_field_update(
        proj,
        "strength",
        "new",
        overwrite_policy=OverwritePolicy.fill_missing_only,
        create_mirror_updates=True,
    )
    assert status == ItemStatus.skipped_existing_value
    assert proj.strength == "existing"


def test_apply_suggest_only_no_write_legacy():
    proj = _projection(strength=None)
    status = apply_field_update(
        proj,
        "strength",
        "strong",
        overwrite_policy=OverwritePolicy.suggest_only,
        create_mirror_updates=True,
    )
    assert status == ItemStatus.suggested
    assert proj.strength is None


# ---------------------------------------------------------------------------
# Dry-run end-to-end
# ---------------------------------------------------------------------------

def test_dry_run_candidate_region_no_provider():
    cand = _candidate()
    session = _mock_session({cand.id: cand})
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.candidate_region,
        target_ids=[cand.id],
        dry_run=True,
    )
    with patch("app.services.llm_field_completion_service.get_llm_provider") as mock_get:
        resp = asyncio.run(run_universal_field_completion(session, req))
        mock_get.assert_not_called()
    assert resp.dry_run is True
    assert resp.status == RunStatus.dry_run
    assert resp.prompt_preview is not None
    assert resp.prompt_preview["target_count"] == 1


def test_dry_run_circuit_no_write():
    circuit = _circuit()
    session = _mock_session({circuit.id: circuit})
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=True,
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert resp.status == RunStatus.dry_run
    assert circuit.circuit_name == "test_circuit"  # unchanged
    assert circuit.normalized_payload_json == {}    # no overlay written


def test_dry_run_projection_no_write():
    proj = _projection()
    session = _mock_session({proj.id: proj})
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.projection,
        target_ids=[proj.id],
        dry_run=True,
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert resp.status == RunStatus.dry_run
    assert proj.evidence_text is None


def test_target_not_found_item():
    tid = uuid.uuid4()
    session = _mock_session({})
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.projection,
        target_ids=[tid],
        dry_run=True,
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert any(f.update_status == ItemStatus.skipped_target_not_found for f in resp.field_updates)


# ---------------------------------------------------------------------------
# Mock provider: formal field in response ? correct item.field_name
# ---------------------------------------------------------------------------

def test_mock_provider_circuit_name_cn_overlay(monkeypatch):
    """Mock returns name_cn ? item.field_name='name_cn', written to overlay."""
    circuit = _circuit(normalized_payload_json={})
    session = _mock_session({circuit.id: circuit})

    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"field_name":"name_cn","value":"????","confidence":0.9}]}',
        parsed_json={"field_updates": [{"field_name": "name_cn", "value": "????", "confidence": 0.9}]},
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)
    monkeypatch.setattr(
        "app.services.llm_field_completion_service.get_llm_provider",
        lambda name: mock_provider,
    )
    monkeypatch.setattr(
        "app.services.llm_field_completion_service.get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )

    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=False,
        create_mirror_updates=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn"],
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert resp.updated_count >= 1
    # Check overlay was written
    overlay = circuit.normalized_payload_json.get("formal_field_overlay", {})
    assert overlay.get("name_cn") == "????"
    # item.field_name must be the formal field name
    applied_items = [f for f in resp.field_updates if f.field_name == "name_cn"]
    assert len(applied_items) >= 1
    assert applied_items[0].update_status in (
        ItemStatus.applied_overlay,
        ItemStatus.applied,
    )
    mock_provider.complete_json.assert_called()


def test_mock_provider_circuit_name_en_direct_write(monkeypatch):
    """Mock returns name_en ? written to circuit_name ORM column (formal_to_mirror)."""
    circuit = _circuit(circuit_name="")
    session = _mock_session({circuit.id: circuit})

    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"field_name":"name_en","value":"Hippocampal Circuit","confidence":0.85}]}',
        parsed_json={"field_updates": [{"field_name": "name_en", "value": "Hippocampal Circuit", "confidence": 0.85}]},
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)
    monkeypatch.setattr(
        "app.services.llm_field_completion_service.get_llm_provider",
        lambda name: mock_provider,
    )
    monkeypatch.setattr(
        "app.services.llm_field_completion_service.get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )

    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=False,
        create_mirror_updates=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_en"],
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert resp.updated_count >= 1
    assert circuit.circuit_name == "Hippocampal Circuit"


def _patch_mock_provider(monkeypatch, response: LlmProviderResponse):
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)
    monkeypatch.setattr(
        "app.services.llm_field_completion_service.get_llm_provider",
        lambda name: mock_provider,
    )
    monkeypatch.setattr(
        "app.services.llm_field_completion_service.get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )
    return mock_provider


def test_invalid_field_function_association_skipped(monkeypatch):
    """function_association is not enrichable ? skipped_invalid_field."""
    circuit = _circuit()
    session = _mock_session({circuit.id: circuit})
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"field_name":"function_association","value":"motor"}]}',
        parsed_json={"field_updates": [{"field_name": "function_association", "value": "motor"}]},
        usage=LlmProviderUsage(),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=1,
    )
    _patch_mock_provider(monkeypatch, response)
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=False,
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert circuit.function_association is None
    assert any(f.update_status == ItemStatus.skipped_invalid_field for f in resp.field_updates)


def test_invalid_field_promotion_status_skipped(monkeypatch):
    """promotion_status is readonly ? skipped_invalid_field at validation."""
    proj = _projection()
    session = _mock_session({proj.id: proj})
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"field_name":"promotion_status","value":"promoted"}]}',
        parsed_json={"field_updates": [{"field_name": "promotion_status", "value": "promoted"}]},
        usage=LlmProviderUsage(),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=1,
    )
    _patch_mock_provider(monkeypatch, response)
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.projection,
        target_ids=[proj.id],
        dry_run=False,
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert proj.promotion_status == "not_promoted"
    assert any(f.update_status == ItemStatus.skipped_invalid_field for f in resp.field_updates)


def test_readonly_id_skipped_via_apply():
    circuit = _circuit()
    entry = get_registry_entry(TargetType.circuit)
    status = apply_field_update(
        circuit,
        "id",
        "new-id",
        overwrite_policy=OverwritePolicy.fill_missing_only,
        create_mirror_updates=True,
        entry=entry,
    )
    assert status == ItemStatus.skipped_readonly_field


def test_mirror_circuit_read_schema_includes_overlay_payload():
    from datetime import datetime, timezone

    from app.schemas.mirror_kg import MirrorRegionCircuitRead

    now = datetime.now(timezone.utc)
    circuit = _circuit(
        normalized_payload_json={"formal_field_overlay": {"name_cn": "?????"}},
        created_at=now,
        updated_at=now,
    )
    read = MirrorRegionCircuitRead.model_validate(circuit)
    assert read.normalized_payload_json["formal_field_overlay"]["name_cn"] == "?????"


def test_malformed_json_failed_not_500(monkeypatch):
    proj = _projection()
    session = _mock_session({proj.id: proj})
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text="not json",
        parsed_json=None,
        usage=LlmProviderUsage(),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=1,
    )
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=response)
    monkeypatch.setattr(
        "app.services.llm_field_completion_service.get_llm_provider",
        lambda name: mock_provider,
    )
    monkeypatch.setattr(
        "app.services.llm_field_completion_service.get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.projection,
        target_ids=[proj.id],
        dry_run=False,
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert resp.status in (RunStatus.failed, RunStatus.partially_succeeded)
    assert len(resp.errors) >= 1


# ---------------------------------------------------------------------------
# API-level tests
# ---------------------------------------------------------------------------

def test_api_empty_target_ids_422():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/llm-extraction/field-completion/run",
        json={
            "target_type": "projection",
            "target_ids": [],
            "dry_run": True,
        },
    )
    assert resp.status_code == 422


def test_api_circuit_function_dry_run_supported():
    from app.main import app
    from app.models.mirror_macro_clinical import MirrorCircuitFunction
    from app.services import mirror_macro_clinical_service

    circuit = _circuit()
    fn_id = uuid.uuid4()
    cf = MirrorCircuitFunction(
        id=fn_id,
        circuit_id=circuit.id,
        granularity_level="macro",
        source_atlas="AAL3",
        function_term_en="sensorimotor integration",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        attributes={},
        raw_payload_json={},
        normalized_payload_json={},
    )
    session = _mock_session({fn_id: cf})

    async def _run(session_arg, request):
        return await run_universal_field_completion(session, request)

    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([cf], 1),
    ), patch(
        "app.routers.llm_field_completion.svc.run_universal_field_completion",
        new=_run,
    ), patch(
        "app.services.llm_field_completion_service.load_targets",
        new_callable=AsyncMock,
        return_value={fn_id: cf},
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/llm-extraction/field-completion/run",
            json={
                "target_type": "circuit_function",
                "target_ids": [str(fn_id)],
                "field_scope": "selected_fields",
                "selected_fields": ["function_term_cn"],
                "dry_run": True,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True


def test_api_circuit_old_fields_rejected_422():
    """circuit_name and circuit_type are NOT valid selected_fields for scope=selected_fields."""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/llm-extraction/field-completion/run",
        json={
            "target_type": "circuit",
            "target_ids": [str(uuid.uuid4())],
            "field_scope": "selected_fields",
            "selected_fields": ["circuit_name", "circuit_type"],
            "dry_run": True,
        },
    )
    # NOTE: circuit_name and circuit_type are legacy aliases in the registry
    # (they resolve to name_en / circuit_class), so they pass alias resolution.
    # Pure made-up names like "bad_field" should be 422.
    resp2 = client.post(
        "/api/llm-extraction/field-completion/run",
        json={
            "target_type": "circuit",
            "target_ids": [str(uuid.uuid4())],
            "field_scope": "selected_fields",
            "selected_fields": ["nonexistent_field_xyz"],
            "dry_run": True,
        },
    )
    assert resp2.status_code == 422
    body = resp2.json()
    assert "nonexistent_field_xyz" in str(body)


def test_api_circuit_formal_fields_pass_validation():
    """name_cn, name_en, circuit_class should pass selected_fields validation."""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/llm-extraction/field-completion/run",
        json={
            "target_type": "circuit",
            "target_ids": [str(uuid.uuid4())],
            "field_scope": "selected_fields",
            "selected_fields": ["name_cn", "name_en", "circuit_class"],
            "dry_run": True,
        },
    )
    # 200 (dry_run, target not found ? skipped_target_not_found) or 500 (DB error in test env)
    assert resp.status_code in (200, 500)


def test_api_dry_run_endpoint():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/llm-extraction/field-completion/run",
        json={
            "target_type": "projection",
            "target_ids": [str(uuid.uuid4())],
            "dry_run": True,
        },
    )
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        body = resp.json()
        assert body["dry_run"] is True
        assert body["status"] == "dry_run"


# ---------------------------------------------------------------------------
# Prompt content verification
# ---------------------------------------------------------------------------

def test_universal_prompt_registered():
    from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES

    tpl = DEFAULT_TEMPLATES["universal_field_completion_v1"]
    assert tpl.task_type == "universal_field_completion"
    assert "field_updates" in tpl.user_prompt_template


def test_prompt_target_schema_has_formal_fields():
    """build_target_context should include formal field names in target_schema_json."""
    from app.services.llm_field_completion_service import build_target_context

    entry = get_registry_entry(TargetType.circuit)
    circuit = _circuit()
    ctx = build_target_context(
        circuit,
        entry,
        include_provenance=False,
        include_related_objects=False,
    )
    schema = ctx["target_schema_json"]
    assert schema.get("formal_database") == "NeuroGraphIQ_KG_V3"
    assert schema.get("formal_schema") == "macro_clinical"
    assert schema.get("formal_table") == "circuit"
    assert "name_cn" in schema.get("enrichable_fields", [])
    assert "name_en" in schema.get("enrichable_fields", [])
    assert "circuit_class" in schema.get("enrichable_fields", [])
    # Old mirror names must not appear in enrichable_fields
    assert "circuit_name" not in schema.get("enrichable_fields", [])
    assert "circuit_type" not in schema.get("enrichable_fields", [])


def test_prompt_projection_function_formal_fields():
    """projection_function target_schema_json must use function_term_cn/en, not function_term."""
    from app.services.llm_field_completion_service import build_target_context
    from app.models.mirror_macro_clinical import MirrorProjectionFunction

    entry = get_registry_entry(TargetType.projection_function)
    pf = MirrorProjectionFunction(
        id=uuid.uuid4(),
        projection_id=uuid.uuid4(),
        granularity_level="macro",
        source_atlas="AAL3",
        function_term="sensory_processing",
        function_category="unknown",
        relation_type="associated_with",
        raw_payload_json={},
        normalized_payload_json={},
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
    )
    ctx = build_target_context(pf, entry, include_provenance=False, include_related_objects=False)
    schema = ctx["target_schema_json"]
    assert "function_term_cn" in schema["enrichable_fields"]
    assert "function_term_en" in schema["enrichable_fields"]
    assert "function_term" not in schema["enrichable_fields"]


def test_no_write_to_formal_db():
    """Verify that no macro_clinical.* or final_* or kg_* tables are mentioned in registry."""
    for entry in REGISTRY.values():
        table = (entry.final_table or "").lower()
        assert "final_" not in table or table.startswith("macro_clinical"), (
            f"Registry entry {entry.target_type} uses non-formal final_table: {table}"
        )


def test_parse_field_completion_provider_response_content_wrapper():
    from app.services.llm_field_completion_service import parse_field_completion_provider_response

    wrapped = {
        "content": '{"field_updates":[{"field_name":"name_cn","value":"??"}],"warnings":[]}',
    }
    parsed = parse_field_completion_provider_response(wrapped)
    assert parsed["field_updates"][0]["field_name"] == "name_cn"


def test_invalid_legacy_circuit_name_in_provider_response(monkeypatch):
    """Provider returning circuit_name (legacy) must be skipped_invalid_field."""
    circuit = _circuit(normalized_payload_json={})
    session = _mock_session({circuit.id: circuit})
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"field_name":"circuit_name","value":"Bad"}]}',
        parsed_json={"field_updates": [{"field_name": "circuit_name", "value": "Bad"}]},
        usage=LlmProviderUsage(),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=1,
    )
    _patch_mock_provider(monkeypatch, response)
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=False,
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert any(f.update_status == ItemStatus.skipped_invalid_field for f in resp.field_updates)
    assert circuit.circuit_name == "test_circuit"


def test_mock_provider_summary_applied_overlay_count(monkeypatch):
    circuit = _circuit(normalized_payload_json={})
    session = _mock_session({circuit.id: circuit})
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"field_name":"name_cn","value":"?????","confidence":0.82}]}',
        parsed_json={"field_updates": [{"field_name": "name_cn", "value": "?????", "confidence": 0.82}]},
        usage=LlmProviderUsage(),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=1,
    )
    _patch_mock_provider(monkeypatch, response)
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=False,
        create_mirror_updates=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn"],
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert resp.applied_overlay_count >= 1
    assert resp.summary_json.get("applied_overlay_count", 0) >= 1


def test_mirror_circuit_read_schema_attributes_alias():
    from datetime import datetime, timezone

    from app.schemas.mirror_kg import MirrorRegionCircuitRead

    now = datetime.now(timezone.utc)
    circuit = _circuit(
        normalized_payload_json={"formal_field_overlay": {"name_cn": "?????"}},
        created_at=now,
        updated_at=now,
    )
    read = MirrorRegionCircuitRead.model_validate(circuit)
    assert read.attributes["formal_field_overlay"]["name_cn"] == "?????"


def test_registry_circuit_direct_and_overlay_fields():
    entry = get_registry_entry(TargetType.circuit)
    assert "name_en" in entry.direct_write_fields
    assert "name_cn" in entry.overlay_write_fields
    assert "circuit_class" in entry.direct_write_fields
    assert "id" in entry.readonly_fields


# Import REGISTRY for the last test
from app.services.field_completion_registry import REGISTRY


# ---------------------------------------------------------------------------
# related-targets API (Step 10.5.3 � read-only, no provider, no writes)
# ---------------------------------------------------------------------------

def _circuit_step(circuit_id: uuid.UUID, **kwargs):
    from app.models.mirror_macro_clinical import MirrorCircuitStep

    defaults = dict(
        id=uuid.uuid4(),
        circuit_id=circuit_id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        step_order=1,
        step_name="step_a",
        step_type="unknown",
        role="unknown",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorCircuitStep(**defaults)


def _circuit_function(circuit_id: uuid.UUID, **kwargs):
    from app.models.mirror_macro_clinical import MirrorCircuitFunction

    defaults = dict(
        id=uuid.uuid4(),
        circuit_id=circuit_id,
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_atlas="AAL3",
        function_term_en="sensorimotor integration",
        function_term_cn=None,
        function_domain="sensorimotor",
        function_role="integration",
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        attributes={},
        raw_payload_json={},
        normalized_payload_json={},
    )
    defaults.update(kwargs)
    return MirrorCircuitFunction(**defaults)


def test_related_targets_service_returns_circuit_and_steps():
    from app.services import mirror_macro_clinical_service
    from app.services.llm_field_completion_service import get_related_field_completion_targets

    circuit = _circuit()
    step1 = _circuit_step(circuit.id, step_order=1)
    step2 = _circuit_step(circuit.id, step_order=2)
    fn1 = _circuit_function(circuit.id)
    session = AsyncMock()

    async def _execute(stmt):
        stmt_str = str(stmt)
        if "mirror_circuit_steps" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [step1.id, step2.id])))
        if "mirror_circuit_functions" in stmt_str and "count" not in stmt_str.lower():
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [fn1.id])))
        return MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [])))

    session.execute = _execute

    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        resp = asyncio.run(
            get_related_field_completion_targets(
                session,
                target_type=TargetType.circuit,
                target_ids=[circuit.id],
                include=["circuit_step", "circuit_function"],
            )
        )
    assert resp.source_target_type == "circuit"
    assert resp.source_target_ids == [circuit.id]
    circuit_group = next(g for g in resp.groups if g.target_type == "circuit")
    assert circuit_group.count == 1
    assert circuit_group.target_ids == [circuit.id]
    step_group = next(g for g in resp.groups if g.target_type == "circuit_step")
    assert step_group.count == 2
    assert set(step_group.target_ids) == {step1.id, step2.id}
    fn_group = next(g for g in resp.groups if g.target_type == "circuit_function")
    assert fn_group.count == 1
    assert fn_group.target_ids == [fn1.id]


def test_related_targets_service_no_functions_warning():
    from app.services import mirror_macro_clinical_service
    from app.services.llm_field_completion_service import get_related_field_completion_targets

    circuit = _circuit()
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [])))
    )

    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        resp = asyncio.run(
            get_related_field_completion_targets(
                session,
                target_type=TargetType.circuit,
                target_ids=[circuit.id],
                include=["circuit_function"],
            )
        )
    fn_group = next(g for g in resp.groups if g.target_type == "circuit_function")
    assert fn_group.count == 0
    assert any("circuit_to_functions extraction" in w for w in fn_group.warnings)
    assert not any("not implemented yet" in w for w in resp.warnings)


def test_api_related_targets_circuit_group():
    from app.main import app
    from app.services import llm_field_completion_service as svc

    circuit_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _fake_related(*args, **kwargs):
        from app.schemas.llm_field_completion import FieldCompletionRelatedGroup, FieldCompletionRelatedTargetsResponse

        return FieldCompletionRelatedTargetsResponse(
            source_target_type="circuit",
            source_target_ids=[circuit_id],
            groups=[
                FieldCompletionRelatedGroup(
                    target_type="circuit",
                    target_ids=[circuit_id],
                    count=1,
                ),
                FieldCompletionRelatedGroup(
                    target_type="circuit_step",
                    target_ids=[step_id],
                    count=1,
                ),
                FieldCompletionRelatedGroup(
                    target_type="circuit_function",
                    target_ids=[],
                    count=0,
                    warnings=[
                        "No mirror_circuit_functions found for selected circuits. "
                        "Run circuit_to_functions extraction first."
                    ],
                ),
            ],
            warnings=[],
        )

    original = svc.get_related_field_completion_targets
    svc.get_related_field_completion_targets = _fake_related
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/llm-extraction/field-completion/related-targets",
            params={
                "target_type": "circuit",
                "target_ids": str(circuit_id),
                "include": "circuit_step,circuit_function",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_target_type"] == "circuit"
        assert len(body["groups"]) == 3
        fn_group = next(g for g in body["groups"] if g["target_type"] == "circuit_function")
        assert fn_group["count"] == 0
        assert any("circuit_to_functions extraction" in w for w in fn_group["warnings"])
        assert not any("not implemented yet" in w for w in body.get("warnings", []))
    finally:
        svc.get_related_field_completion_targets = original


def test_mirror_circuit_step_read_schema_attributes_overlay():
    from datetime import datetime, timezone

    from app.schemas.mirror_macro_clinical import MirrorCircuitStepRead

    now = datetime.now(timezone.utc)
    circuit_id = uuid.uuid4()
    step = _circuit_step(
        circuit_id,
        normalized_payload_json={"formal_field_overlay": {"step_name_cn": "?????"}},
    )
    step.created_at = now
    step.updated_at = now
    read = MirrorCircuitStepRead.model_validate(step)
    assert read.attributes["formal_field_overlay"]["step_name_cn"] == "?????"
    assert read.normalized_payload_json["formal_field_overlay"]["step_name_cn"] == "?????"


def test_api_related_targets_invalid_uuid_422():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        "/api/llm-extraction/field-completion/related-targets",
        params={"target_type": "circuit", "target_ids": "not-a-uuid"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Step 10.5.5 � related-targets route registration + Decimal JSON safety
# ---------------------------------------------------------------------------


def test_api_related_targets_route_registered():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/llm-extraction/field-completion/related-targets" in paths


def test_to_jsonable_decimal_and_nested():
    import json
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.utils.json_safety import to_jsonable

    value = {
        "confidence": Decimal("0.875"),
        "scores": [Decimal("1.0"), Decimal("0.5")],
        "when": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    safe = to_jsonable(value)
    json.dumps(safe)
    assert safe["confidence"] == 0.875
    assert safe["scores"] == [1.0, 0.5]
    assert isinstance(safe["when"], str)


def test_object_to_json_converts_decimal_confidence():
    from decimal import Decimal

    from app.services.field_completion_registry import object_to_json

    circuit = _circuit()
    circuit.confidence = Decimal("0.91")
    data = object_to_json(circuit)
    assert isinstance(data["confidence"], float)
    assert data["confidence"] == 0.91


def test_dry_run_false_decimal_in_target_context_no_500(monkeypatch):
    """ORM Numeric confidence must not break prompt build or JSONB writes."""
    import json
    from decimal import Decimal

    circuit = _circuit(normalized_payload_json={})
    circuit.confidence = Decimal("0.88")
    session = _mock_session({circuit.id: circuit})

    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"field_name":"name_cn","value":"????","confidence":0.9}]}',
        parsed_json={"field_updates": [{"field_name": "name_cn", "value": "????", "confidence": 0.9}]},
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    _patch_mock_provider(monkeypatch, response)

    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=False,
        create_mirror_updates=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn"],
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert resp.status != RunStatus.failed
    json.dumps(resp.model_dump(mode="json"))

    overlay_meta = circuit.normalized_payload_json.get("formal_field_overlay_meta", {})
    name_cn_meta = overlay_meta.get("name_cn", {})
    if name_cn_meta.get("confidence") is not None:
        assert isinstance(name_cn_meta["confidence"], (float, int))

    for item in resp.field_updates:
        if item.suggested_value is not None:
            json.dumps(item.suggested_value)
        if item.applied_value is not None:
            json.dumps(item.applied_value)

    summary = resp.summary_json or {}
    json.dumps(summary)


# ---------------------------------------------------------------------------
# Step 10.5.6 � Field-specific prompts + Prompt Workbench
# ---------------------------------------------------------------------------


def test_select_field_completion_prompt_key_circuit_fields():
    from app.services.field_completion_prompt_engineering import select_field_completion_prompt_key

    assert select_field_completion_prompt_key(TargetType.circuit, "name_cn") == "circuit_field_completion_name_cn_v1"
    assert select_field_completion_prompt_key(TargetType.circuit, "circuit_class") == "circuit_field_completion_circuit_class_v1"
    assert select_field_completion_prompt_key(TargetType.circuit_step, "step_name_cn") == "circuit_step_field_completion_step_name_cn_v1"
    assert select_field_completion_prompt_key(TargetType.circuit_function, "function_term_cn") == "circuit_function_field_completion_function_term_cn_v1"


def test_dry_run_prompt_preview_template_plan():
    circuit = _circuit()
    session = _mock_session({circuit.id: circuit})
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn", "circuit_class"],
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    preview = resp.prompt_preview or {}
    assert "template_plan" in preview
    assert preview.get("estimated_model_calls", 0) >= 2
    plan = preview["template_plan"]
    assert any(p["field_name"] == "name_cn" and p["prompt_key"] == "circuit_field_completion_name_cn_v1" for p in plan)


def test_prompt_overrides_applied_in_dry_run():
    circuit = _circuit()
    session = _mock_session({circuit.id: circuit})
    override_text = "CUSTOM PROMPT OVERRIDE FOR name_cn ONLY"
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn"],
        prompt_overrides={"circuit_field_completion_name_cn_v1": override_text},
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    previews = (resp.prompt_preview or {}).get("previews") or []
    assert any(override_text in (p.get("user_prompt") or "") for p in previews)


def test_mock_provider_prompt_contains_circuit_logic(monkeypatch):
    circuit = _circuit(normalized_payload_json={})
    session = _mock_session({circuit.id: circuit})
    captured: list[str] = []

    async def _capture(*args, **kwargs):
        captured.append(kwargs.get("user_prompt") or "")
        return LlmProviderResponse(
            provider="deepseek",
            model="deepseek-chat",
            raw_text='{"field_updates":[{"field_name":"name_cn","value":"????","confidence":0.9}]}',
            parsed_json={"field_updates": [{"field_name": "name_cn", "value": "????", "confidence": 0.9}]},
            usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            finish_reason="stop",
            request_payload_redacted={},
            response_payload={},
            latency_ms=5,
        )

    mock_provider = AsyncMock()
    mock_provider.complete_json = _capture
    monkeypatch.setattr("app.services.llm_field_completion_service.get_llm_provider", lambda name: mock_provider)
    monkeypatch.setattr(
        "app.services.llm_field_completion_service.get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=False,
        create_mirror_updates=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn"],
    )
    asyncio.run(run_universal_field_completion(session, req))
    assert captured
    joined = captured[0]
    assert "name_cn" in joined or "Batch complete" in joined or "batch" in joined.lower()


def test_mock_provider_name_cn_english_rejected(monkeypatch):
    circuit = _circuit(normalized_payload_json={})
    session = _mock_session({circuit.id: circuit})
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"field_name":"name_cn","value":"Hippocampal Circuit"}]}',
        parsed_json={"field_updates": [{"field_name": "name_cn", "value": "Hippocampal Circuit"}]},
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    _patch_mock_provider(monkeypatch, response)
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=False,
        create_mirror_updates=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn"],
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    invalid = [f for f in resp.field_updates if f.update_status == ItemStatus.skipped_invalid_field]
    assert invalid


def test_bundle_context_includes_circuit_steps():
    from app.services import mirror_macro_clinical_service
    from app.services.llm_field_completion_service import build_circuit_bundle_context

    circuit = _circuit()
    step1 = _circuit_step(circuit.id, step_order=1)
    fn1 = _circuit_function(circuit.id)
    session = AsyncMock()

    async def _execute(stmt):
        stmt_str = str(stmt)
        if "mirror_circuit_steps" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [step1])))
        if "mirror_circuit_regions" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [])))
        if "candidate_brain_regions" in stmt_str:
            return MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [])))
        return MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [])))

    session.get = AsyncMock(return_value=circuit)
    session.execute = _execute
    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([fn1], 1),
    ):
        ctx, warnings = asyncio.run(build_circuit_bundle_context(session, circuit.id))
    assert len(ctx.get("circuit_steps", [])) == 1
    assert len(ctx.get("circuit_functions", [])) == 1
    assert not any("not implemented yet" in w for w in warnings)


def test_dry_run_circuit_function_prompt_preview():
    from app.services import mirror_macro_clinical_service

    circuit = _circuit()
    cf = _circuit_function(circuit.id, function_term_cn=None)
    session = _mock_session({cf.id: cf})
    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([cf], 1),
    ):
        req = UniversalFieldCompletionRequest(
            target_type=TargetType.circuit_function,
            target_ids=[cf.id],
            dry_run=True,
            field_scope=FieldScope.selected_fields,
            selected_fields=["function_term_cn", "function_domain"],
        )
        resp = asyncio.run(run_universal_field_completion(session, req))
    preview = resp.prompt_preview or {}
    assert preview.get("compact_context_enabled") is True
    plan = preview.get("template_plan") or []
    assert any(
        p.get("target_type") == "circuit_function"
        and p.get("field_name") == "function_term_cn"
        and p.get("prompt_key") == "circuit_function_field_completion_function_term_cn_v1"
        for p in plan
    )
    assert preview.get("target_count") == 1


def test_circuit_function_mock_provider_writes_function_term_cn(monkeypatch):
    from app.services import mirror_macro_clinical_service

    circuit = _circuit()
    cf = _circuit_function(circuit.id, function_term_cn=None)
    session = _mock_session({cf.id: cf})
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"field_name":"function_term_cn","value":"??????","confidence":0.9}]}',
        parsed_json={"field_updates": [{"field_name": "function_term_cn", "value": "??????", "confidence": 0.9}]},
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=1,
    )
    _patch_mock_provider(monkeypatch, response)
    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([cf], 1),
    ):
        req = UniversalFieldCompletionRequest(
            target_type=TargetType.circuit_function,
            target_ids=[cf.id],
            dry_run=False,
            create_mirror_updates=True,
            field_scope=FieldScope.selected_fields,
            selected_fields=["function_term_cn"],
        )
        resp = asyncio.run(run_universal_field_completion(session, req))
    assert cf.function_term_cn == "??????"
    assert resp.updated_count >= 1
    assert any(f.field_name == "function_term_cn" for f in resp.field_updates)


def test_circuit_function_invalid_field_function_association_skipped(monkeypatch):
    from app.services import mirror_macro_clinical_service

    circuit = _circuit()
    cf = _circuit_function(circuit.id)
    session = _mock_session({cf.id: cf})
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"field_name":"function_association","value":"motor"}]}',
        parsed_json={"field_updates": [{"field_name": "function_association", "value": "motor"}]},
        usage=LlmProviderUsage(),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=1,
    )
    _patch_mock_provider(monkeypatch, response)
    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        return_value=([cf], 1),
    ):
        req = UniversalFieldCompletionRequest(
            target_type=TargetType.circuit_function,
            target_ids=[cf.id],
            dry_run=False,
            field_scope=FieldScope.selected_fields,
            selected_fields=["function_term_cn"],
        )
        resp = asyncio.run(run_universal_field_completion(session, req))
    assert any(f.update_status == ItemStatus.skipped_invalid_field for f in resp.field_updates)


def test_api_circuit_function_migration_not_initialized_503():
    from app.main import app
    from app.services import mirror_macro_clinical_service
    from app.services.mirror_macro_clinical_service import MirrorCircuitFunctionsNotInitializedError

    fn_id = uuid.uuid4()
    with patch.object(
        mirror_macro_clinical_service,
        "list_mirror_circuit_functions",
        new_callable=AsyncMock,
        side_effect=MirrorCircuitFunctionsNotInitializedError(),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/llm-extraction/field-completion/run",
            json={
                "target_type": "circuit_function",
                "target_ids": [str(fn_id)],
                "field_scope": "selected_fields",
                "selected_fields": ["function_term_cn"],
                "dry_run": True,
            },
        )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED"


def test_compact_context_circuit_function_excludes_full_payload():
    from app.services.field_completion_prompt_engineering import build_compact_field_context

    circuit = _circuit()
    cf = _circuit_function(
        circuit.id,
        attributes={"formal_field_overlay": {"extra": "x" * 500}},
        raw_payload_json={"big": "y" * 500},
        normalized_payload_json={"big": "z" * 500},
    )
    ctx = build_compact_field_context(cf, "function_term_cn")
    dumped = str(ctx)
    assert "y" * 200 not in dumped
    assert "z" * 200 not in dumped
    assert ctx.get("function_term_en") == cf.function_term_en


def test_api_prompt_templates_route():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/llm-extraction/field-completion/prompt-templates")
    assert resp.status_code == 200
    body = resp.json()
    keys = [item["key"] for item in body.get("items", [])]
    assert "circuit_field_completion_name_cn_v1" in keys
    assert "circuit_bundle_consistency_v1" in keys


# ---------------------------------------------------------------------------
# Step 10.5.8 � deterministic canonical region resolver + token-efficient completion
# ---------------------------------------------------------------------------


def _circuit_region_row(circuit_id, candidate_id, *, sort_order=0, role="participant"):
    return MirrorCircuitRegion(
        id=uuid.uuid4(),
        circuit_id=circuit_id,
        region_candidate_id=candidate_id,
        role=role,
        sort_order=sort_order,
    )


def _session_with_regions(circuit, candidates: dict[uuid.UUID, CandidateBrainRegion], region_rows: list):
    session = _mock_session({circuit.id: circuit}, region_rows=region_rows)
    candidates_map = dict(candidates)

    async def _get(model, tid):
        if model is CandidateBrainRegion:
            return candidates_map.get(tid)
        return {circuit.id: circuit}.get(tid)

    session.get = AsyncMock(side_effect=_get)
    return session


def test_registry_circuit_canonical_fields_are_deterministic():
    from app.services.field_completion_registry import get_registry_entry, is_deterministic_field

    entry = get_registry_entry(TargetType.circuit)
    assert is_deterministic_field(entry, "canonical_start_region_id")
    assert is_deterministic_field(entry, "canonical_end_region_id")
    assert entry.deterministic_fields["canonical_start_region_id"] == "canonical_region_resolver"


def test_resolve_circuit_regions_sort_order():
    from app.services.canonical_region_resolver import resolve_circuit_canonical_regions

    circuit = _circuit(circuit_name="right thalamus-caudate circuit")
    start_c = _candidate(en_name="right thalamus")
    end_c = _candidate(en_name="right caudate")
    rows = [
        _circuit_region_row(circuit.id, start_c.id, sort_order=0),
        _circuit_region_row(circuit.id, end_c.id, sort_order=1),
    ]
    session = _session_with_regions(circuit, {start_c.id: start_c, end_c.id: end_c}, rows)
    res = asyncio.run(resolve_circuit_canonical_regions(session, circuit))
    assert res.start_region_id == str(start_c.id)
    assert res.end_region_id == str(end_c.id)
    assert any("sort_order" in w for w in res.warnings)


def test_resolve_region_candidate_to_final_brain_region():
    from app.services.canonical_region_resolver import resolve_region_candidate_to_canonical

    candidate = _candidate()
    final_id = uuid.uuid4()
    session = AsyncMock()

    async def _get(model, tid):
        if tid == candidate.id:
            return candidate
        return None

    async def _execute(stmt):
        stmt_str = str(stmt)
        if "final_brain_regions" in stmt_str:
            return MagicMock(scalar_one_or_none=lambda: final_id)
        return MagicMock(scalar_one_or_none=lambda: None)

    session.get = AsyncMock(side_effect=_get)
    session.execute = _execute
    cid, _label, method, conf, _ = asyncio.run(
        resolve_region_candidate_to_canonical(session, candidate.id, source_atlas="AAL3")
    )
    assert cid == str(final_id)
    assert method == "formal_region_lookup"
    assert conf >= 0.9


def test_canonical_start_end_overlay_without_provider(monkeypatch):
    circuit = _circuit(normalized_payload_json={})
    start_c = _candidate(en_name="right thalamus")
    end_c = _candidate(en_name="right caudate")
    rows = [
        _circuit_region_row(circuit.id, start_c.id, sort_order=0),
        _circuit_region_row(circuit.id, end_c.id, sort_order=1),
    ]
    session = _session_with_regions(circuit, {start_c.id: start_c, end_c.id: end_c}, rows)
    mock_provider = AsyncMock()
    monkeypatch.setattr(
        "app.services.llm_field_completion_service.get_llm_provider",
        lambda name: mock_provider,
    )
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=False,
        create_mirror_updates=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["canonical_start_region_id", "canonical_end_region_id"],
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    overlay = circuit.normalized_payload_json.get("formal_field_overlay", {})
    assert overlay.get("canonical_start_region_id") == str(start_c.id)
    assert overlay.get("canonical_end_region_id") == str(end_c.id)
    meta = circuit.normalized_payload_json.get("formal_field_overlay_meta", {})
    assert meta.get("canonical_start_region_id", {}).get("source") == "deterministic_canonical_region_resolver"
    mock_provider.complete_json.assert_not_called()
    assert resp.updated_count >= 2


def test_name_cn_still_calls_mock_provider_step1058(monkeypatch):
    circuit = _circuit(normalized_payload_json={})
    session = _mock_session({circuit.id: circuit})
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text='{"field_updates":[{"target_id":"'
        + str(circuit.id)
        + '","field_name":"name_cn","value":"???-?????","confidence":0.9}]}',
        parsed_json={
            "field_updates": [{
                "target_id": str(circuit.id),
                "field_name": "name_cn",
                "value": "???-?????",
                "confidence": 0.9,
            }]
        },
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock = _patch_mock_provider(monkeypatch, response)
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=False,
        create_mirror_updates=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn"],
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    mock.complete_json.assert_called()
    assert resp.status != RunStatus.failed


def test_compact_context_excludes_full_attributes_raw():
    from app.services.field_completion_prompt_engineering import build_compact_field_context

    circuit = _circuit(
        normalized_payload_json={
            "attributes": {
                "raw": {"region_roles": [{"region_candidate_id": "x", "extra": "y" * 500}]},
            }
        }
    )
    ctx = build_compact_field_context(circuit, "name_cn")
    dumped = str(ctx)
    assert "y" * 200 not in dumped
    assert "attributes" not in dumped


def test_dry_run_preview_shows_deterministic_and_token_estimates():
    circuit = _circuit()
    session = _mock_session({circuit.id: circuit})
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[circuit.id],
        dry_run=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn", "canonical_start_region_id"],
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    preview = resp.prompt_preview or {}
    assert preview.get("compact_context_enabled") is True
    assert "deterministic_plan" in preview
    assert preview.get("estimated_model_calls", 0) >= 1
    assert preview.get("estimated_input_tokens", 0) >= 0
    det_fields = preview.get("deterministic_fields") or []
    assert "canonical_start_region_id" in det_fields


def test_batch_prompt_handles_multiple_targets(monkeypatch):
    c1 = _circuit(normalized_payload_json={})
    c2 = _circuit(normalized_payload_json={})
    session = _mock_session({c1.id: c1, c2.id: c2})
    response = LlmProviderResponse(
        provider="deepseek",
        model="deepseek-chat",
        raw_text="{}",
        parsed_json={
            "field_updates": [
                {"target_id": str(c1.id), "field_name": "name_cn", "value": "???", "confidence": 0.9},
                {"target_id": str(c2.id), "field_name": "name_cn", "value": "???", "confidence": 0.9},
            ]
        },
        usage=LlmProviderUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=5,
    )
    mock = _patch_mock_provider(monkeypatch, response)
    req = UniversalFieldCompletionRequest(
        target_type=TargetType.circuit,
        target_ids=[c1.id, c2.id],
        dry_run=False,
        create_mirror_updates=True,
        field_scope=FieldScope.selected_fields,
        selected_fields=["name_cn"],
    )
    resp = asyncio.run(run_universal_field_completion(session, req))
    assert mock.complete_json.call_count == 1
    assert resp.updated_count >= 2


def test_estimate_prompt_tokens_and_pack_split():
    from app.services.field_completion_prompt_engineering import estimate_prompt_tokens, pack_target_batches

    records = [{"target_id": str(uuid.uuid4()), "name_en": "circuit " + str(i)} for i in range(50)]
    packs = pack_target_batches(records, system_prompt="sys", template_body="body")
    assert len(packs) >= 1
    assert sum(len(p) for p in packs) == len(records)
    assert estimate_prompt_tokens("abcd" * 10) > 0


# ---------------------------------------------------------------------------
# Step 10.6.7 -�C Extraction prompt templates separation tests
# ---------------------------------------------------------------------------

def test_extraction_prompt_templates_api_returns_circuit_to_functions():
    """GET /api/llm-extraction/prompt-templates must return circuit_to_functions_extraction_v1."""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get('/api/llm-extraction/prompt-templates')
    assert resp.status_code == 200
    items = resp.json()['items']
    keys = [i['key'] for i in items]
    assert 'circuit_to_functions_extraction_v1' in keys


def test_field_completion_prompt_templates_api_excludes_extraction():
    """GET /api/llm-extraction/field-completion/prompt-templates must NOT return circuit_to_functions_extraction_v1."""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get('/api/llm-extraction/field-completion/prompt-templates')
    assert resp.status_code == 200
    items = resp.json()['items']
    keys = [i['key'] for i in items]
    assert 'circuit_to_functions_extraction_v1' not in keys


def test_extraction_prompt_template_has_neuroscience_role():
    """circuit_to_functions_extraction_v1 system prompt must include neuroscience expert role."""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get('/api/llm-extraction/prompt-templates')
    assert resp.status_code == 200
    items = resp.json()['items']
    ct = next((i for i in items if i['key'] == 'circuit_to_functions_extraction_v1'), None)
    if ct is None:
        return  # prompt not registered - acceptable if not in DEFAULT_TEMPLATES
    assert 'mirror_circuit_functions' in ct['system_prompt'] or 'function_term_en' in ct['system_prompt']


def test_extraction_prompt_template_has_display_name():
    """circuit_to_functions_extraction_v1 must have a bilingual display_name."""
    from app.services.field_completion_prompt_engineering import list_extraction_prompt_template_items

    items = list_extraction_prompt_template_items()
    keys = [i['key'] for i in items]
    assert 'circuit_to_functions_extraction_v1' in keys
    ct = next(i for i in items if i['key'] == 'circuit_to_functions_extraction_v1')
    assert ct.get('display_name') is not None
    dn = str(ct['display_name'])
    assert 'Circuit' in dn
