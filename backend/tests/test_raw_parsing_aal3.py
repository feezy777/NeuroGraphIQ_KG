"""Raw Parsing for AAL3 tests (no PostgreSQL required)."""

import uuid
from pathlib import Path

import pytest

from app.parsers.aal3_xml import parse_aal3_xml
from app.schemas.import_batch import (
    ImportBatchStatus,
    InvalidBatchTransitionError,
    validate_import_batch_transition,
)
from app.schemas.raw_parsing import Laterality, ParseRunStatus, ParserKey
from app.services.raw_parsing_service import DuplicateParseError
from app.utils.aal3_laterality import extract_region_base_name, infer_laterality
from app.utils.aal3_raw_adapter import xml_regions_to_raw_labels

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_XML = FIXTURES / "AAL3v1_1mm_sample.xml"


def test_laterality_from_parser_hemisphere():
    assert infer_laterality("Precentral_L", "L") == "left"
    assert infer_laterality("Precentral_R", "R") == "right"


def test_laterality_from_name_suffix():
    assert infer_laterality("Frontal_Sup_2_L", None) == "left"
    assert infer_laterality("Frontal_Sup_2_R", None) == "right"


def test_laterality_bilateral_and_midline():
    assert infer_laterality("Something_Bi", None) == "bilateral"
    assert infer_laterality("Cerebellar_Vermis", None) == "midline"


def test_laterality_unknown():
    assert infer_laterality("ACgG", None) == "unknown"


def test_region_base_name_strips_suffix():
    assert extract_region_base_name("Precentral_L") == "Precentral"
    assert extract_region_base_name("Frontal_Sup_2_R") == "Frontal_Sup_2"


def test_parse_run_status_enum():
    assert ParseRunStatus.succeeded.value == "succeeded"
    assert ParseRunStatus.failed.value == "failed"


def test_parser_key_enum():
    assert ParserKey.aal3_xml.value == "aal3_xml"


def test_running_to_parsed_allowed():
    validate_import_batch_transition(ImportBatchStatus.running, ImportBatchStatus.parsed)


def test_laterality_enum_rejects_candidate_status():
    with pytest.raises(ValueError):
        Laterality("candidate_created")  # type: ignore[arg-type]


def test_completed_batch_transition_blocked():
    with pytest.raises(InvalidBatchTransitionError):
        validate_import_batch_transition(ImportBatchStatus.completed, ImportBatchStatus.parsed)


def test_cancelled_batch_transition_blocked():
    with pytest.raises(InvalidBatchTransitionError):
        validate_import_batch_transition(ImportBatchStatus.cancelled, ImportBatchStatus.running)


def test_duplicate_parse_error_shape():
    bid = uuid.uuid4()
    rid = uuid.uuid4()
    err = DuplicateParseError(bid, "aal3_xml", rid)
    assert err.parser_key == "aal3_xml"
    assert err.existing_run_id == rid


def test_xml_adapter_produces_raw_labels():
    if not SAMPLE_XML.is_file():
        pytest.skip("fixture missing")
    regions = parse_aal3_xml(SAMPLE_XML)
    run_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    file_id = uuid.uuid4()
    rows = xml_regions_to_raw_labels(
        regions=regions,
        parse_run_id=run_id,
        batch_id=batch_id,
        resource_id=resource_id,
        source_file_id=file_id,
        source_atlas="AAL3",
        source_version="v1",
    )
    assert len(rows) == 3
    assert rows[0]["raw_payload"]["label_index"] == 1
    assert rows[0]["laterality"] == "left"
    assert rows[0]["raw_name"] == "Precentral_L"
    assert rows[0]["source_file_id"] == file_id
    assert "candidate" not in str(rows[0]["raw_payload"])


def test_batch_not_running_logic_message():
    from app.services.raw_parsing_service import BatchNotRunnableError

    err = BatchNotRunnableError("batch status must be running, got completed")
    assert "running" in str(err)


def test_no_label_file_error():
    from app.services.raw_parsing_service import NoLabelFileError

    assert "label" in str(NoLabelFileError("no label_dictionary"))


def test_raw_parsing_options_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/raw-parsing/options")
    assert resp.status_code == 200
    body = resp.json()
    assert "aal3_xml" in body["parser_key"]
    assert "left" in body["laterality"]


def test_prior_options_endpoints_still_work():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/resources/options").status_code == 200
    assert client.get("/api/files/options").status_code == 200
    assert client.get("/api/import-batches/options").status_code == 200


def _regions_from_intermediate_rows(raw_rows: list[dict]) -> list[dict]:
    """Mirror raw_parsing_service intermediate → regions reconstruction."""
    return [
        {
            "label_index": r.get("label_value"),
            "original_name": r.get("raw_name", ""),
            "abbr": r.get("raw_name", ""),
            "full_name": r.get("en_name") or r.get("raw_name", ""),
            "hemisphere": r.get("laterality"),
            "parent_region": None,
            "granularity": "macro",
            "source_id": r.get("source_label_id", ""),
            "coordinates_mni": None,
            "bounding_box": None,
            "extra_attrs": {},
        }
        for r in raw_rows
    ]


def test_parse_from_intermediate_matches_raw_xml():
    """Intermediate label_table rows must produce same raw labels as direct XML parse."""
    if not SAMPLE_XML.is_file():
        pytest.skip("fixture missing")
    from app.services.file_normalization_service import _dispatch_normalizer

    regions_xml = parse_aal3_xml(SAMPLE_XML)
    _, arts = _dispatch_normalizer(SAMPLE_XML, ".xml", "label_table", {})
    art = arts[0]
    regions_intermediate = _regions_from_intermediate_rows(art["content_jsonb"]["rows"])

    run_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    file_id = uuid.uuid4()

    rows_xml = xml_regions_to_raw_labels(
        regions=regions_xml,
        parse_run_id=run_id,
        batch_id=batch_id,
        resource_id=resource_id,
        source_file_id=file_id,
        source_atlas="AAL3",
        source_version="v1",
    )
    rows_int = xml_regions_to_raw_labels(
        regions=regions_intermediate,
        parse_run_id=run_id,
        batch_id=batch_id,
        resource_id=resource_id,
        source_file_id=file_id,
        source_atlas="AAL3",
        source_version="v1",
    )
    assert len(rows_xml) == len(rows_int) == 3
    for a, b in zip(rows_xml, rows_int):
        assert a["raw_name"] == b["raw_name"]
        assert a["laterality"] == b["laterality"]
        assert a["label_value"] == b["label_value"]


def _mock_resource_file(**overrides):
    from types import SimpleNamespace

    base = {
        "id": uuid.uuid4(),
        "original_filename": "AAL3v1_1mm.xml",
        "file_type": "label_table",
        "file_role": "label_dictionary",
        "status": "active",
        "deleted_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _mock_binding(file_id: uuid.UUID, role: str = "label_dictionary"):
    from types import SimpleNamespace

    return SimpleNamespace(file_id=file_id, file_role_in_batch=role)


def test_bound_file_not_active_detail_structure():
    from app.services.raw_parsing_service import (
        BoundFileNotActiveError,
        bound_file_not_active_detail,
    )

    file_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    exc = BoundFileNotActiveError(file_id, "archived", batch_id)
    detail = bound_file_not_active_detail(exc)
    assert detail["code"] == "BOUND_FILE_NOT_ACTIVE"
    assert detail["file_id"] == str(file_id)
    assert detail["file_status"] == "archived"
    assert detail["batch_id"] == str(batch_id)
    assert "Reactivate" in detail["suggestion"]


def test_evaluate_batch_parse_readiness_archived_label_file():
    from app.services.raw_parsing_service import evaluate_batch_parse_readiness

    file_id = uuid.uuid4()
    archived = _mock_resource_file(id=file_id, status="archived")
    binding = _mock_binding(file_id)
    can_parse, reason = evaluate_batch_parse_readiness([binding], {file_id: archived})
    assert can_parse is False
    assert str(file_id) in (reason or "")
    assert "archived" in (reason or "")


def test_assess_bound_file_parse_status_inactive():
    from app.services.raw_parsing_service import assess_bound_file_parse_status

    file_id = uuid.uuid4()
    archived = _mock_resource_file(id=file_id, status="archived")
    status = assess_bound_file_parse_status(archived, "label_dictionary")
    assert status["is_active"] is False
    assert status["can_parse"] is False
    assert status["parser_compatible_for_aal3_xml"] is False
    assert "archived" in str(status["inactive_reason"])


def test_assess_aal3_xml_parser_compatibility_xlsx():
    from app.services.raw_parsing_service import assess_aal3_xml_parser_compatibility

    xlsx = _mock_resource_file(
        original_filename="Brain volume list.xlsx",
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
    )
    ok, reason = assess_aal3_xml_parser_compatibility(xlsx, "label_dictionary")
    assert ok is False
    assert reason is not None
    assert "xlsx" in reason


def test_assess_aal3_xml_parser_compatibility_pdf():
    from app.services.raw_parsing_service import assess_aal3_xml_parser_compatibility

    pdf = _mock_resource_file(
        original_filename="atlas_doc.pdf",
        file_type="pdf",
        file_role="documentation",
    )
    ok, reason = assess_aal3_xml_parser_compatibility(pdf, "label_dictionary")
    assert ok is False
    assert reason is not None
    assert "pdf" in reason


def test_assess_aal3_xml_parser_compatibility_xml():
    from app.services.raw_parsing_service import assess_aal3_xml_parser_compatibility

    xml = _mock_resource_file(
        original_filename="AAL3v1_1mm.xml",
        file_type="label_table",
        file_role="label_dictionary",
    )
    ok, reason = assess_aal3_xml_parser_compatibility(xml, "label_dictionary")
    assert ok is True
    assert reason is None


def test_evaluate_batch_parse_readiness_xlsx_only():
    from app.services.raw_parsing_service import evaluate_batch_parse_readiness

    file_id = uuid.uuid4()
    xlsx = _mock_resource_file(
        id=file_id,
        original_filename="Brain volume list.xlsx",
        file_type="spreadsheet",
        file_role="macro_region_pool_source",
    )
    binding = _mock_binding(file_id)
    can_parse, reason = evaluate_batch_parse_readiness([binding], {file_id: xlsx})
    assert can_parse is False
    assert reason is not None
    assert "AAL3 XML" in reason


def test_no_aal3_xml_label_dictionary_detail_structure():
    from app.services.raw_parsing_service import (
        NoAal3XmlLabelDictionaryError,
        no_aal3_xml_label_dictionary_detail,
    )

    batch_id = uuid.uuid4()
    bound = [{
        "file_id": str(uuid.uuid4()),
        "original_filename": "Brain volume list.xlsx",
        "file_type": "spreadsheet",
        "reason": "xlsx file cannot be parsed by aal3_xml parser",
    }]
    exc = NoAal3XmlLabelDictionaryError(batch_id, "aal3_xml", bound)
    detail = no_aal3_xml_label_dictionary_detail(exc)
    assert detail["code"] == "NO_AAL3_XML_LABEL_DICTIONARY"
    assert detail["batch_id"] == str(batch_id)
    assert detail["bound_files"][0]["original_filename"] == "Brain volume list.xlsx"


def test_parse_aal3_xlsx_returns_structured_400():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import raw_parsing_service

    batch_id = uuid.uuid4()
    exc = raw_parsing_service.NoAal3XmlLabelDictionaryError(
        batch_id,
        "aal3_xml",
        [{
            "file_id": str(uuid.uuid4()),
            "original_filename": "Brain volume list.xlsx",
            "file_type": "spreadsheet",
            "file_role": "macro_region_pool_source",
            "file_role_in_batch": "label_dictionary",
            "file_status": "active",
            "reason": "xlsx file cannot be parsed by aal3_xml parser",
        }],
    )

    async def fake_parse(*_args, **_kwargs):
        raise exc

    original = raw_parsing_service.parse_aal3_for_batch
    raw_parsing_service.parse_aal3_for_batch = fake_parse  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(f"/api/import-batches/{batch_id}/parse-aal3")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "NO_AAL3_XML_LABEL_DICTIONARY"
        assert detail["bound_files"][0]["original_filename"] == "Brain volume list.xlsx"
        assert "xlsx" in detail["bound_files"][0]["reason"]
    finally:
        raw_parsing_service.parse_aal3_for_batch = original  # type: ignore[assignment]


def test_parse_aal3_archived_bound_file_returns_structured_409():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import raw_parsing_service

    file_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    exc = raw_parsing_service.BoundFileNotActiveError(file_id, "archived", batch_id)

    async def fake_parse(*_args, **_kwargs):
        raise exc

    original = raw_parsing_service.parse_aal3_for_batch
    raw_parsing_service.parse_aal3_for_batch = fake_parse  # type: ignore[assignment]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(f"/api/import-batches/{batch_id}/parse-aal3")
        assert resp.status_code == 409
        body = resp.json()
        detail = body["detail"]
        assert detail["code"] == "BOUND_FILE_NOT_ACTIVE"
        assert detail["file_id"] == str(file_id)
        assert detail["file_status"] == "archived"
        assert detail["batch_id"] == str(batch_id)
    finally:
        raw_parsing_service.parse_aal3_for_batch = original  # type: ignore[assignment]
