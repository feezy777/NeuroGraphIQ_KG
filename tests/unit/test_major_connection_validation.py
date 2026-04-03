from __future__ import annotations

from scripts.validate.validate_major_connection_table import validate_major_connection_record


def _base_connection() -> dict:
    return {
        "major_connection_id": "CONN_MAJOR_PFC_AMY_STRUCTURAL",
        "connection_code": "CONN_MAJOR_PFC_AMY_STRUCTURAL",
        "en_name": "PFC to AMY",
        "connection_modality": "structural",
        "source_major_region_id": "REG_MAJOR_PFC_LEFT",
        "target_major_region_id": "REG_MAJOR_AMY_LEFT",
        "confidence": 0.8,
        "validation_status": "cross_pass_unverified",
    }


def test_validate_major_connection_success() -> None:
    errors = validate_major_connection_record(
        _base_connection(),
        seen_ids=set(),
        seen_keys=set(),
        valid_region_ids={"REG_MAJOR_PFC_LEFT", "REG_MAJOR_AMY_LEFT"},
    )
    assert errors == []


def test_validate_major_connection_duplicate_and_fk() -> None:
    errors = validate_major_connection_record(
        _base_connection(),
        seen_ids={"CONN_MAJOR_PFC_AMY_STRUCTURAL"},
        seen_keys={("REG_MAJOR_PFC_LEFT", "REG_MAJOR_AMY_LEFT", "structural")},
        valid_region_ids={"REG_MAJOR_PFC_LEFT"},
    )
    assert "duplicate_major_connection_id" in errors
    assert "duplicate_connection_key" in errors
    assert "unknown_target_major_region_id" in errors


def test_validate_major_connection_invalid_status() -> None:
    record = _base_connection()
    record["validation_status"] = "approved"
    errors = validate_major_connection_record(
        record,
        seen_ids=set(),
        seen_keys=set(),
        valid_region_ids={"REG_MAJOR_PFC_LEFT", "REG_MAJOR_AMY_LEFT"},
    )
    assert "invalid_validation_status" in errors

