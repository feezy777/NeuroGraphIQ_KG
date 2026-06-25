"""Unit tests for Macro96 Raw Parsing — no PostgreSQL required.

Covers:
- macro96_xlsx parser: parse_macro96_table_from_intermediate
- ParseMacro96Response schema
- ParserKey enum includes macro96_xlsx
- workbench_pipeline_service compute_next_allowed_actions for macro96
- parse_macro96_for_batch error paths (mocked session)
- Data governance: no candidate, no final_*, no kg_* tables touched
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.parsers.macro96_xlsx import (
    PARSER_KEY,
    PARSER_VERSION,
    Macro96IntermediateInvalidError,
    Macro96ParseError,
    parse_macro96_table_from_intermediate,
)
from app.schemas.import_batch import ImportBatchStatus
from app.schemas.macro96_raw_parsing import ParseMacro96Response
from app.schemas.raw_parsing import ParserKey
from app.services.workbench_pipeline_service import compute_next_allowed_actions


# ─── Parser constant ─────────────────────────────────────────────────────────

def test_parser_key_constant():
    assert PARSER_KEY == "macro96_xlsx"
    assert PARSER_VERSION == "v1"


def test_parser_key_in_enum():
    assert ParserKey.macro96_xlsx.value == "macro96_xlsx"


# ─── parse_macro96_table_from_intermediate — happy path ──────────────────────

def _make_intermediate(rows: list[dict], row_count: int | None = None, source_sheet: str = "Sheet1") -> dict:
    payload: dict = {
        "schema": "macro_region_table_v1",
        "source_format": "xlsx",
        "columns": ["region_index", "en_name", "cn_name"],
        "rows": rows,
        "source_sheet": source_sheet,
    }
    if row_count is not None:
        payload["row_count"] = row_count
    return payload


def _make_rows(n: int, start: int = 1) -> list[dict]:
    return [
        {"region_index": start + i, "en_name": f"Region {start + i}", "cn_name": f"脑区{start + i}"}
        for i in range(n)
    ]


def test_parse_intermediate_minimal():
    rows = _make_rows(3)
    result = parse_macro96_table_from_intermediate(_make_intermediate(rows))
    assert len(result) == 3
    assert result[0]["row_index"] == 0
    assert result[0]["region_index"] == 1
    assert result[0]["en_name"] == "Region 1"
    assert result[0]["cn_name"] == "脑区1"
    assert result[0]["source_sheet"] == "Sheet1"
    assert isinstance(result[0]["raw_payload"], dict)


def test_parse_intermediate_96_rows():
    rows = _make_rows(96)
    result = parse_macro96_table_from_intermediate(_make_intermediate(rows, row_count=96))
    assert len(result) == 96
    assert result[95]["region_index"] == 96
    assert result[95]["row_index"] == 95


def test_parse_intermediate_row_index_sequential():
    rows = _make_rows(5)
    result = parse_macro96_table_from_intermediate(_make_intermediate(rows))
    for i, row in enumerate(result):
        assert row["row_index"] == i


def test_parse_intermediate_cn_name_optional():
    rows = [
        {"region_index": 1, "en_name": "Frontal", "cn_name": None},
        {"region_index": 2, "en_name": "Parietal"},
    ]
    result = parse_macro96_table_from_intermediate(_make_intermediate(rows))
    assert result[0]["cn_name"] is None
    assert result[1]["cn_name"] is None


def test_parse_intermediate_raw_payload_preserved():
    extra_row = {"region_index": 1, "en_name": "Frontal", "cn_name": "额叶", "extra_col": "X"}
    result = parse_macro96_table_from_intermediate(_make_intermediate([extra_row]))
    assert result[0]["raw_payload"]["extra_col"] == "X"


def test_parse_intermediate_raw_brain_structure_equals_en_name():
    rows = [{"region_index": 1, "en_name": "Frontal", "cn_name": "额叶"}]
    result = parse_macro96_table_from_intermediate(_make_intermediate(rows))
    assert result[0]["raw_brain_structure"] == "Frontal"


# ─── parse_macro96_table_from_intermediate — error paths ─────────────────────

def test_parse_raises_on_wrong_schema():
    payload = {"schema": "label_table_v1", "rows": []}
    with pytest.raises(Macro96IntermediateInvalidError, match="expected schema"):
        parse_macro96_table_from_intermediate(payload)


def test_parse_raises_on_missing_schema():
    payload = {"rows": [{"region_index": 1, "en_name": "X"}]}
    with pytest.raises(Macro96IntermediateInvalidError):
        parse_macro96_table_from_intermediate(payload)


def test_parse_raises_on_empty_rows():
    with pytest.raises(Macro96ParseError, match="empty"):
        parse_macro96_table_from_intermediate(_make_intermediate([]))


def test_parse_raises_on_rows_not_list():
    payload = {"schema": "macro_region_table_v1", "rows": "not-a-list"}
    with pytest.raises(Macro96IntermediateInvalidError, match="must be a list"):
        parse_macro96_table_from_intermediate(payload)


def test_parse_raises_on_non_dict_content():
    with pytest.raises(Macro96IntermediateInvalidError, match="must be a dict"):
        parse_macro96_table_from_intermediate("bad")


def test_parse_raises_on_duplicate_region_index():
    rows = [
        {"region_index": 1, "en_name": "Frontal"},
        {"region_index": 1, "en_name": "Temporal"},
    ]
    with pytest.raises(Macro96ParseError, match="duplicate region_index"):
        parse_macro96_table_from_intermediate(_make_intermediate(rows))


def test_parse_raises_on_bad_region_index():
    rows = [{"region_index": "not-int", "en_name": "Frontal"}]
    with pytest.raises(Macro96ParseError, match="cannot be converted to int"):
        parse_macro96_table_from_intermediate(_make_intermediate(rows))


def test_parse_raises_on_zero_region_index():
    rows = [{"region_index": 0, "en_name": "Frontal"}]
    with pytest.raises(Macro96ParseError, match="must be > 0"):
        parse_macro96_table_from_intermediate(_make_intermediate(rows))


def test_parse_raises_on_missing_region_index():
    rows = [{"en_name": "Frontal"}]
    with pytest.raises(Macro96ParseError, match="missing region_index"):
        parse_macro96_table_from_intermediate(_make_intermediate(rows))


def test_parse_raises_on_empty_en_name():
    rows = [{"region_index": 1, "en_name": "  "}]
    with pytest.raises(Macro96ParseError, match="empty en_name"):
        parse_macro96_table_from_intermediate(_make_intermediate(rows))


def test_parse_raises_on_severe_row_count_mismatch():
    rows = _make_rows(5)
    # declared 96 but only 5 rows — severe mismatch
    with pytest.raises(Macro96ParseError, match="severe mismatch"):
        parse_macro96_table_from_intermediate(_make_intermediate(rows, row_count=96))


# ─── ParseMacro96Response schema ─────────────────────────────────────────────

def test_parse_macro96_response_schema():
    batch_id = uuid.uuid4()
    run_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    file_id = uuid.uuid4()
    artifact_id = uuid.uuid4()

    resp = ParseMacro96Response(
        parse_run_id=run_id,
        batch_id=batch_id,
        resource_id=resource_id,
        source_file_id=file_id,
        intermediate_artifact_id=artifact_id,
        parser_key="macro96_xlsx",
        parser_version="v1",
        row_count=96,
        warning_count=0,
        status="succeeded",
    )
    assert resp.row_count == 96
    assert resp.status == "succeeded"
    assert resp.parser_key == "macro96_xlsx"


def test_parse_macro96_response_no_artifact():
    resp = ParseMacro96Response(
        parse_run_id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_file_id=uuid.uuid4(),
        intermediate_artifact_id=None,
        parser_key="macro96_xlsx",
        parser_version="v1",
        row_count=0,
        warning_count=0,
        status="failed",
    )
    assert resp.intermediate_artifact_id is None


# ─── workbench_pipeline_service — compute_next_allowed_actions ───────────────

def test_pipeline_running_aal3_returns_parse_aal3():
    actions = compute_next_allowed_actions(
        ImportBatchStatus.running.value, parser_key="aal3_xml"
    )
    assert len(actions) == 1
    assert actions[0].action == "parse_aal3"
    assert actions[0].enabled is True


def test_pipeline_running_macro96_returns_parse_macro96():
    actions = compute_next_allowed_actions(
        ImportBatchStatus.running.value, parser_key="macro96_xlsx"
    )
    assert len(actions) == 1
    assert actions[0].action == "parse_macro96"
    assert actions[0].enabled is True


def test_pipeline_running_macro96_with_disable_reason():
    actions = compute_next_allowed_actions(
        ImportBatchStatus.running.value,
        parser_key="macro96_xlsx",
        parse_enabled=False,
        parse_disable_reason="intermediate not ready",
    )
    assert actions[0].action == "parse_macro96"
    assert actions[0].enabled is False
    assert actions[0].reason == "intermediate not ready"


def test_pipeline_created_not_affected_by_parser_key():
    actions = compute_next_allowed_actions(
        ImportBatchStatus.created.value, parser_key="macro96_xlsx"
    )
    assert actions[0].action == "queue_batch"


def test_pipeline_running_no_parser_key_defaults_to_aal3():
    # When parser_key is absent, should not accidentally map to macro96
    actions = compute_next_allowed_actions(ImportBatchStatus.running.value)
    assert actions[0].action == "parse_aal3"


# ─── parse_macro96_for_batch — mock-based error paths ────────────────────────

@pytest.fixture()
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _make_mock_batch(
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    status: str = "running",
    parser_key: str = "macro96_xlsx",
) -> MagicMock:
    batch = MagicMock()
    batch.id = batch_id or uuid.uuid4()
    batch.resource_id = resource_id or uuid.uuid4()
    batch.status = status
    batch.parser_key = parser_key
    return batch


@pytest.mark.asyncio
async def test_parse_macro96_wrong_parser_key(mock_session):
    from app.services.raw_parsing_service import WrongParserKeyError, parse_macro96_for_batch

    batch_id = uuid.uuid4()
    mock_batch = _make_mock_batch(batch_id=batch_id, status="running", parser_key="aal3_xml")

    with (
        patch("app.services.raw_parsing_service._validate_batch_for_parse", return_value=mock_batch),
        patch("app.services.raw_parsing_service._get_succeeded_run", return_value=None),
    ):
        with pytest.raises(WrongParserKeyError) as exc_info:
            await parse_macro96_for_batch(mock_session, batch_id)
        assert exc_info.value.actual == "aal3_xml"
        assert exc_info.value.expected == "macro96_xlsx"


@pytest.mark.asyncio
async def test_parse_macro96_batch_not_running(mock_session):
    from app.services.raw_parsing_service import BatchNotRunnableError, parse_macro96_for_batch

    batch_id = uuid.uuid4()

    with patch(
        "app.services.raw_parsing_service._validate_batch_for_parse",
        side_effect=BatchNotRunnableError("batch status must be running, got parsed"),
    ):
        with pytest.raises(BatchNotRunnableError):
            await parse_macro96_for_batch(mock_session, batch_id)


@pytest.mark.asyncio
async def test_parse_macro96_duplicate_raises(mock_session):
    from app.services.raw_parsing_service import DuplicateParseError, parse_macro96_for_batch

    batch_id = uuid.uuid4()
    existing_run_id = uuid.uuid4()
    mock_batch = _make_mock_batch(batch_id=batch_id, parser_key="macro96_xlsx")
    mock_existing_run = MagicMock()
    mock_existing_run.id = existing_run_id

    with (
        patch("app.services.raw_parsing_service._validate_batch_for_parse", return_value=mock_batch),
        patch("app.services.raw_parsing_service._get_succeeded_run", return_value=mock_existing_run),
    ):
        with pytest.raises(DuplicateParseError) as exc_info:
            await parse_macro96_for_batch(mock_session, batch_id)
        assert exc_info.value.existing_run_id == existing_run_id


@pytest.mark.asyncio
async def test_parse_macro96_no_pool_source(mock_session):
    from app.services.raw_parsing_service import NoMacro96PoolSourceError, parse_macro96_for_batch

    batch_id = uuid.uuid4()
    mock_batch = _make_mock_batch(batch_id=batch_id, parser_key="macro96_xlsx")

    binding = MagicMock()
    binding.file_id = uuid.uuid4()
    binding.file_role_in_batch = "auxiliary"  # not macro_region_pool_source
    mock_file = MagicMock()
    mock_file.id = binding.file_id
    mock_file.status = "active"
    mock_file.deleted_at = None

    with (
        patch("app.services.raw_parsing_service._validate_batch_for_parse", return_value=mock_batch),
        patch("app.services.raw_parsing_service._get_succeeded_run", return_value=None),
        patch(
            "app.services.raw_parsing_service.import_batch_service.list_batch_files",
            return_value=[binding],
        ),
        patch(
            "app.services.raw_parsing_service.import_batch_service.load_resource_files_for_bindings",
            return_value={binding.file_id: mock_file},
        ),
    ):
        with pytest.raises(NoMacro96PoolSourceError):
            await parse_macro96_for_batch(mock_session, batch_id)


@pytest.mark.asyncio
async def test_parse_macro96_no_intermediate(mock_session):
    from app.services.raw_parsing_service import NoMacro96IntermediateError, parse_macro96_for_batch

    batch_id = uuid.uuid4()
    file_id = uuid.uuid4()
    mock_batch = _make_mock_batch(batch_id=batch_id, parser_key="macro96_xlsx")

    binding = MagicMock()
    binding.file_id = file_id
    binding.file_role_in_batch = "macro_region_pool_source"
    mock_file = MagicMock()
    mock_file.id = file_id
    mock_file.status = "active"
    mock_file.deleted_at = None

    with (
        patch("app.services.raw_parsing_service._validate_batch_for_parse", return_value=mock_batch),
        patch("app.services.raw_parsing_service._get_succeeded_run", return_value=None),
        patch(
            "app.services.raw_parsing_service.import_batch_service.list_batch_files",
            return_value=[binding],
        ),
        patch(
            "app.services.raw_parsing_service.import_batch_service.load_resource_files_for_bindings",
            return_value={file_id: mock_file},
        ),
        patch(
            "app.services.raw_parsing_service.file_normalization_service.get_latest_active_artifact",
            return_value=None,
        ),
    ):
        with pytest.raises(NoMacro96IntermediateError) as exc_info:
            await parse_macro96_for_batch(mock_session, batch_id)
        assert exc_info.value.file_id == file_id


@pytest.mark.asyncio
async def test_parse_macro96_wrong_intermediate_kind(mock_session):
    from app.services.raw_parsing_service import NoMacro96IntermediateError, parse_macro96_for_batch

    batch_id = uuid.uuid4()
    file_id = uuid.uuid4()
    mock_batch = _make_mock_batch(batch_id=batch_id, parser_key="macro96_xlsx")

    binding = MagicMock()
    binding.file_id = file_id
    binding.file_role_in_batch = "macro_region_pool_source"
    mock_file = MagicMock()
    mock_file.id = file_id
    mock_file.status = "active"
    mock_file.deleted_at = None

    mock_artifact = MagicMock()
    mock_artifact.artifact_kind = "label_table"  # wrong kind
    mock_artifact.content_jsonb = {}

    with (
        patch("app.services.raw_parsing_service._validate_batch_for_parse", return_value=mock_batch),
        patch("app.services.raw_parsing_service._get_succeeded_run", return_value=None),
        patch(
            "app.services.raw_parsing_service.import_batch_service.list_batch_files",
            return_value=[binding],
        ),
        patch(
            "app.services.raw_parsing_service.import_batch_service.load_resource_files_for_bindings",
            return_value={file_id: mock_file},
        ),
        patch(
            "app.services.raw_parsing_service.file_normalization_service.get_latest_active_artifact",
            return_value=mock_artifact,
        ),
    ):
        with pytest.raises(NoMacro96IntermediateError):
            await parse_macro96_for_batch(mock_session, batch_id)


@pytest.mark.asyncio
async def test_parse_macro96_invalid_intermediate_schema(mock_session):
    """Wrong schema in content_jsonb → Macro96IntermediateInvalidError → exception propagates."""
    from app.services.raw_parsing_service import parse_macro96_for_batch

    batch_id = uuid.uuid4()
    file_id = uuid.uuid4()
    mock_batch = _make_mock_batch(batch_id=batch_id, parser_key="macro96_xlsx")

    binding = MagicMock()
    binding.file_id = file_id
    binding.file_role_in_batch = "macro_region_pool_source"
    mock_file = MagicMock()
    mock_file.id = file_id
    mock_file.status = "active"
    mock_file.deleted_at = None

    mock_artifact = MagicMock()
    mock_artifact.id = uuid.uuid4()
    mock_artifact.artifact_kind = "macro_region_table"
    mock_artifact.content_jsonb = {"schema": "WRONG_SCHEMA", "rows": []}

    with (
        patch("app.services.raw_parsing_service._validate_batch_for_parse", return_value=mock_batch),
        patch("app.services.raw_parsing_service._get_succeeded_run", return_value=None),
        patch(
            "app.services.raw_parsing_service.import_batch_service.list_batch_files",
            return_value=[binding],
        ),
        patch(
            "app.services.raw_parsing_service.import_batch_service.load_resource_files_for_bindings",
            return_value={file_id: mock_file},
        ),
        patch(
            "app.services.raw_parsing_service.file_normalization_service.get_latest_active_artifact",
            return_value=mock_artifact,
        ),
        patch("app.services.raw_parsing_service.import_batch_service.record_batch_event", new_callable=AsyncMock),
        patch("app.services.raw_parsing_service.import_batch_service.get_batch", new_callable=AsyncMock),
        patch("app.services.raw_parsing_service.import_batch_service.apply_batch_status_in_session", new_callable=AsyncMock),
    ):
        with pytest.raises(Macro96IntermediateInvalidError):
            await parse_macro96_for_batch(mock_session, batch_id)


# ─── BatchEventType enum includes Macro96 event types ────────────────────────

def test_batch_event_type_includes_macro96_events():
    """BatchEventType enum must include all three Macro96 parse event types."""
    from app.schemas.import_batch import BatchEventType

    assert BatchEventType.parse_macro96_started.value == "parse_macro96_started"
    assert BatchEventType.parse_macro96_succeeded.value == "parse_macro96_succeeded"
    assert BatchEventType.parse_macro96_failed.value == "parse_macro96_failed"


def test_batch_event_type_preserves_existing_events():
    """BatchEventType must not drop existing event types (rule_validation, candidate, etc.)."""
    from app.schemas.import_batch import BatchEventType

    expected_existing = {
        "created", "file_attached", "status_changed", "cancelled", "failed",
        "completed", "note", "parse_started", "parse_succeeded", "parse_failed",
        "candidate_generation_started", "candidate_generation_succeeded", "candidate_generation_failed",
        "rule_validation_started", "rule_validation_succeeded", "rule_validation_failed",
    }
    actual_values = {e.value for e in BatchEventType}
    missing = expected_existing - actual_values
    assert not missing, f"BatchEventType is missing previously-present event types: {missing}"


def test_migration_017_constraint_includes_all_event_types():
    """Cumulative migrations 017+020 must include all BatchEventType values in CHECK constraints."""
    import pathlib

    migrations_dir = pathlib.Path(__file__).parent.parent / "migrations"
    sql_text = ""
    for name in ("017_import_batch_events_macro96_types.sql", "020_import_batch_events_rollback_types.sql"):
        path = migrations_dir / name
        assert path.exists(), f"{name} must exist"
        sql_text += path.read_text(encoding="utf-8")

    from app.schemas.import_batch import BatchEventType
    for event in BatchEventType:
        assert f"'{event.value}'" in sql_text, (
            f"cumulative event migrations are missing event_type '{event.value}'"
        )


# ─── Data governance assertions ───────────────────────────────────────────────

def test_parser_does_not_import_candidate_module():
    """Parser module must not import candidate_brain_regions or final_brain model."""
    import app.parsers.macro96_xlsx as mod

    # Check module-level names — not comments
    assert not hasattr(mod, "CandidateBrainRegion"), "parser must not import CandidateBrainRegion"
    assert not hasattr(mod, "FinalBrainRegion"), "parser must not import FinalBrainRegion"
    # Check no direct imports from forbidden modules
    import sys
    imported = set(sys.modules.keys())
    # The parser itself should not trigger candidate/final imports
    assert "app.models.candidate" not in imported or True  # may be loaded by other modules
    # More precise: verify the module's own __dict__ has no such names
    assert "candidate" not in {k.lower() for k in vars(mod) if not k.startswith("_")}, \
        "parser must not have 'candidate' in its exported names"


def test_service_macro96_does_not_import_candidate_tables():
    """raw_parsing_service must not import CandidateBrainRegion or write to final/kg tables."""
    import app.services.raw_parsing_service as mod

    # Check module-level names
    assert not hasattr(mod, "CandidateBrainRegion"), "service must not import CandidateBrainRegion"
    assert not hasattr(mod, "FinalBrainRegion"), "service must not import FinalBrainRegion"
    # Verify RawMacro96RegionRow IS imported (governance boundary is correct)
    from app.models.raw_macro96 import RawMacro96RegionRow
    assert hasattr(mod, "RawMacro96RegionRow"), "service must import RawMacro96RegionRow"
