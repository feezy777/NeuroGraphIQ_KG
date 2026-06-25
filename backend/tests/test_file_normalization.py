"""Unit tests for file_normalization_service pure helpers.

Tests the dispatch logic and per-format normalizers without DB or filesystem.
Does NOT test raw_aal3_region_labels, candidate_brain_regions, final_*, kg_*.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.services.file_normalization_service import (
    NORMALIZER_KEY_AAL3_XML,
    NORMALIZER_KEY_GENERIC,
    _dispatch_normalizer,
    _ext_to_source_format,
    _make_run_code,
    _normalize_json,
    _normalize_text,
    _normalize_csv_tsv,
    _normalize_binary_or_unsupported,
)


# ─── _ext_to_source_format ───────────────────────────────────────────────────

def test_ext_to_source_format_known():
    assert _ext_to_source_format(".xml") == "xml"
    assert _ext_to_source_format(".json") == "json"
    assert _ext_to_source_format(".csv") == "csv"
    assert _ext_to_source_format(".tsv") == "tsv"
    assert _ext_to_source_format(".txt") == "txt"
    assert _ext_to_source_format(".nii") == "nifti"
    assert _ext_to_source_format(".png") == "image"
    assert _ext_to_source_format(".pdf") == "pdf"


def test_ext_to_source_format_unknown():
    assert _ext_to_source_format(".xyz") == "unknown"
    assert _ext_to_source_format("") == "unknown"


# ─── _make_run_code ──────────────────────────────────────────────────────────

def test_make_run_code_uniqueness():
    import uuid
    fid = uuid.uuid4()
    codes = {_make_run_code(fid) for _ in range(5)}
    assert len(codes) == 5  # should be unique due to uuid suffix


# ─── _normalize_json ─────────────────────────────────────────────────────────

def test_normalize_json_list():
    data = [{"a": 1}, {"a": 2}, {"a": 3}]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb") as f:
        f.write(json.dumps(data).encode())
        p = Path(f.name)

    result = _normalize_json(p, {"file_id": "test"})
    assert result["artifact_kind"] == "json_document"
    assert result["row_count"] == 3
    assert result["content_jsonb"] is not None
    assert result["preview_jsonb"]["total_rows"] == 3
    assert result["warnings_jsonb"] == []


def test_normalize_json_dict():
    data = {"key": "value"}
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb") as f:
        f.write(json.dumps(data).encode())
        p = Path(f.name)

    result = _normalize_json(p, {})
    assert result["artifact_kind"] == "json_document"
    assert result["row_count"] is None  # dicts don't get row_count


def test_normalize_json_invalid():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb") as f:
        f.write(b"not valid json {{{")
        p = Path(f.name)

    result = _normalize_json(p, {})
    assert result["content_jsonb"] is None
    assert len(result["warnings_jsonb"]) > 0


# ─── _normalize_text ─────────────────────────────────────────────────────────

def test_normalize_text_basic():
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write("line1\nline2\nline3\n")
        p = Path(f.name)

    result = _normalize_text(p, {})
    assert result["artifact_kind"] == "text_document"
    assert result["row_count"] == 3
    assert result["content_jsonb"]["line_count"] == 3
    assert result["warnings_jsonb"] == []


def test_normalize_text_truncation():
    long_text = "x" * 3000
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write(long_text)
        p = Path(f.name)

    result = _normalize_text(p, {})
    assert result["preview_jsonb"]["is_truncated"] is True


# ─── _normalize_csv_tsv ──────────────────────────────────────────────────────

def test_normalize_csv():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8") as f:
        f.write("id,name,value\n1,Foo,10\n2,Bar,20\n")
        p = Path(f.name)

    result = _normalize_csv_tsv(p, ".csv", {})
    assert result["artifact_kind"] == "tabular_data"
    assert result["row_count"] == 2
    assert "id" in result["content_jsonb"]["columns"]
    assert result["source_format"] == "csv"


def test_normalize_tsv():
    with tempfile.NamedTemporaryFile(suffix=".tsv", delete=False, mode="w", encoding="utf-8") as f:
        f.write("id\tname\n1\tFoo\n")
        p = Path(f.name)

    result = _normalize_csv_tsv(p, ".tsv", {})
    assert result["artifact_kind"] == "tabular_data"
    assert result["source_format"] == "tsv"
    assert result["row_count"] == 1


# ─── _normalize_binary_or_unsupported ────────────────────────────────────────

def test_normalize_binary_unsupported():
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False, mode="wb") as f:
        f.write(b"\x80\x04\x95")
        p = Path(f.name)

    result = _normalize_binary_or_unsupported(p, ".pkl", {})
    assert result["artifact_kind"] == "binary_metadata"
    assert result["content_jsonb"] is None
    assert len(result["warnings_jsonb"]) > 0


# ─── _dispatch_normalizer ────────────────────────────────────────────────────

def test_dispatch_xml_returns_aal3_normalizer():
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w", encoding="utf-8") as f:
        # minimal FSL-style XML
        f.write("""<?xml version="1.0" encoding="UTF-8"?>
<atlas>
  <data>
    <label index="1" name="Precentral_L" x="-36" y="-2" z="50"/>
    <label index="2" name="Precentral_R" x="36" y="-2" z="50"/>
  </data>
</atlas>""")
        p = Path(f.name)

    key, arts = _dispatch_normalizer(p, ".xml", "label_table", {"file_id": "test"})
    assert key == NORMALIZER_KEY_AAL3_XML
    art = arts[0]
    assert art["artifact_kind"] == "label_table"
    assert art["row_count"] == 2
    rows = art["content_jsonb"]["rows"]
    assert len(rows) == 2
    assert rows[0]["raw_name"] == "Precentral_L"


def test_dispatch_json():
    data = [{"a": 1}]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb") as f:
        f.write(json.dumps(data).encode())
        p = Path(f.name)

    key, arts = _dispatch_normalizer(p, ".json", "json", {})
    assert key == NORMALIZER_KEY_GENERIC
    assert arts[0]["artifact_kind"] == "json_document"


def test_dispatch_binary_fallback():
    with tempfile.NamedTemporaryFile(suffix=".mat", delete=False, mode="wb") as f:
        f.write(b"\x00\x01\x02")
        p = Path(f.name)

    key, arts = _dispatch_normalizer(p, ".mat", "other", {})
    assert key == NORMALIZER_KEY_GENERIC
    assert arts[0]["artifact_kind"] == "binary_metadata"


# ─── Architecture boundary checks ────────────────────────────────────────────

def test_service_does_not_import_raw_or_candidate_models():
    """Ensure file_normalization_service has no dependency on restricted tables."""
    import importlib
    import ast
    import pathlib

    service_path = pathlib.Path(__file__).parent.parent / "app" / "services" / "file_normalization_service.py"
    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_patterns = [
        "raw_aal3_region_labels",
        "candidate_brain_regions",
        "final_brain_regions",
        "kg_",
        "llm",
        "deepseek",
    ]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            node_str = ast.unparse(node)
            for pattern in forbidden_patterns:
                assert pattern not in node_str.lower(), (
                    f"file_normalization_service must not import '{pattern}': found '{node_str}'"
                )


# ─── AAL3 fixture integration ────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_XML = FIXTURES / "AAL3v1_1mm_sample.xml"


def test_aal3_sample_xml_label_table_row_count():
    if not SAMPLE_XML.is_file():
        pytest.skip("fixture missing")
    key, arts = _dispatch_normalizer(SAMPLE_XML, ".xml", "label_table", {"file_id": "test"})
    assert key == NORMALIZER_KEY_AAL3_XML
    art = arts[0]
    assert art["artifact_kind"] == "label_table"
    assert art["row_count"] == 3
    assert art["content_jsonb"]["schema"] == "label_table_v1"
    assert art["preview_jsonb"]["rows_preview"] is not None
    assert art["metadata_jsonb"]["parser_hint"] == "aal3_xml"


def test_intermediate_api_endpoints_no_500():
    """Unknown file_id must not cause 500 on intermediate endpoints."""
    import uuid
    from fastapi.testclient import TestClient
    from app.main import app

    fid = str(uuid.uuid4())
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get(f"/api/files/{fid}/intermediate").status_code == 200
    body = client.get(f"/api/files/{fid}/intermediate").json()
    assert body["status"] == "missing"
    assert body["artifacts"] == []
    assert client.get(f"/api/files/{fid}/intermediate/runs").status_code == 200
    assert client.get(f"/api/files/{fid}/intermediate/runs").json() == []
    assert client.post(f"/api/files/{fid}/normalize").status_code == 404


def test_normalize_does_not_touch_restricted_tables():
    """Static check: normalization service must not import or execute writes to restricted tables."""
    import ast
    import pathlib

    service_path = pathlib.Path(__file__).parent.parent / "app" / "services" / "file_normalization_service.py"
    tree = ast.parse(service_path.read_text(encoding="utf-8"))
    forbidden = [
        "raw_aal3_region_labels",
        "candidate_brain_regions",
        "final_brain_regions",
    ]
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value.lower()
            for pattern in forbidden:
                assert pattern not in val or "must not" in val or "does not" in val, (
                    f"normalization must not reference {pattern} in executable strings"
                )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            node_str = ast.unparse(node).lower()
            for pattern in forbidden + ["kg_"]:
                assert pattern not in node_str, f"normalization must not import {pattern}"


# ─── Spreadsheet / PDF semantic normalizers ───────────────────────────────────

BRAIN_VOLUME_FIXTURE = FIXTURES / "brain_volume_list_sample.xlsx"


def _write_brain_volume_fixture(path: Path, *, rows: int = 3) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["ID #", "Brain Structure", "脑区中文名称"])
    sample = [
        (1, "white matter", "脑白质"),
        (2, "left lateral ventricle", "左侧脑室"),
        (3, "left thalamus proper", "左丘脑本体"),
    ]
    for i in range(rows):
        if i < len(sample):
            ws.append(list(sample[i]))
        else:
            ws.append([i + 1, f"region_{i + 1}", f"区域_{i + 1}"])
    wb.save(path)
    wb.close()


@pytest.fixture(scope="module")
def brain_volume_xlsx(tmp_path_factory) -> Path:
    path = FIXTURES / "brain_volume_list_sample.xlsx"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        _write_brain_volume_fixture(path, rows=3)
    return path


def test_xlsx_generates_spreadsheet_workbook_not_binary(brain_volume_xlsx):
    from app.utils.intermediate_normalizers import NORMALIZER_KEY_MACRO_REGION, NORMALIZER_KEY_SPREADSHEET

    prov = {"original_filename": "Brain volume list.xlsx", "file_id": "test"}
    key, arts = _dispatch_normalizer(brain_volume_xlsx, ".xlsx", "spreadsheet", prov)
    kinds = {a["artifact_kind"] for a in arts}
    assert "binary_metadata" not in kinds
    assert "spreadsheet_workbook" in kinds
    wb = next(a for a in arts if a["artifact_kind"] == "spreadsheet_workbook")
    assert wb["content_jsonb"]["schema"] == "spreadsheet_workbook_v1"
    assert len(wb["content_jsonb"]["sheets"]) >= 1
    assert wb["content_jsonb"]["sheets"][0]["columns"] == ["ID #", "Brain Structure", "脑区中文名称"]
    assert key in (NORMALIZER_KEY_SPREADSHEET, NORMALIZER_KEY_MACRO_REGION)


def test_brain_volume_list_generates_macro_region_table(brain_volume_xlsx):
    prov = {"original_filename": "Brain volume list.xlsx", "file_id": "test"}
    _, arts = _dispatch_normalizer(brain_volume_xlsx, ".xlsx", "spreadsheet", prov)
    macro = next((a for a in arts if a["artifact_kind"] == "macro_region_table"), None)
    assert macro is not None
    assert macro["row_count"] == 3
    assert macro["content_jsonb"]["schema"] == "macro_region_table_v1"
    assert macro["content_jsonb"]["columns"] == ["region_index", "en_name", "cn_name"]
    assert macro["metadata_jsonb"]["purpose"] == "macro_96_region_pool_intermediate"
    assert "does not create macro_96_pool records" in macro["metadata_jsonb"].get("note", "").lower()


def test_macro_region_table_preview_has_rows(brain_volume_xlsx):
    _, arts = _dispatch_normalizer(brain_volume_xlsx, ".xlsx", "spreadsheet", {"original_filename": "Brain volume list.xlsx"})
    macro = next(a for a in arts if a["artifact_kind"] == "macro_region_table")
    preview = macro["preview_jsonb"]
    assert preview["rows_preview"]
    assert preview["columns"] == ["region_index", "en_name", "cn_name"]


def test_pdf_generates_pdf_metadata_not_label_table():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, mode="wb") as f:
        # minimal PDF header bytes — pdf_metadata even if unreadable
        f.write(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n")
        p = Path(f.name)
    key, arts = _dispatch_normalizer(p, ".pdf", "pdf", {"original_filename": "paper1.pdf"})
    assert len(arts) == 1
    assert arts[0]["artifact_kind"] == "pdf_metadata"
    assert arts[0]["artifact_kind"] != "label_table"
    assert key == "pdf_metadata_v1"


def test_unknown_binary_still_binary_metadata():
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False, mode="wb") as f:
        f.write(b"\x00\x01\x02")
        p = Path(f.name)
    _, arts = _dispatch_normalizer(p, ".bin", "other", {})
    assert arts[0]["artifact_kind"] == "binary_metadata"


def test_infer_file_role_brain_volume_xlsx():
    from app.utils.file_meta import infer_file_role, infer_file_type, suggest_file_classification
    from app.schemas.resource_file import FileRole, FileType

    ft, fr = suggest_file_classification("Brain volume list.xlsx")
    assert ft == FileType.spreadsheet
    assert fr == FileRole.macro_region_pool_source
    assert infer_file_type("paper1.pdf") == FileType.pdf
    assert infer_file_role("paper1.pdf") == FileRole.documentation
    assert infer_file_type("labels.xml") == FileType.label_table
