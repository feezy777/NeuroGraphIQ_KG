from __future__ import annotations

from scripts.transform.major_normalization import (
    normalize_alias,
    normalize_laterality,
    normalize_major_region_record,
    normalize_region_code,
)


def test_normalize_region_code() -> None:
    assert normalize_region_code(" mPfc-left ") == "MPFC_LEFT"
    assert normalize_region_code("VISp") == "VISP"


def test_normalize_alias() -> None:
    assert normalize_alias("PFC, prefrontal cortex, PFC") == ["PFC", "prefrontal cortex"]
    assert normalize_alias(["A", "a", " B "]) == ["A", "B"]


def test_normalize_laterality() -> None:
    assert normalize_laterality("L") == "left"
    assert normalize_laterality("both") == "bilateral"
    assert normalize_laterality("unknown") is None


def test_normalize_major_region_record() -> None:
    raw = {
        "region_code": " mPfc-left ",
        "en_name": "Medial PFC",
        "alias": "mPFC;PFC",
        "laterality": "left",
    }
    normalized = normalize_major_region_record(raw)
    assert normalized["region_code"] == "MPFC_LEFT"
    assert normalized["en_name"] == "Medial PFC"
    assert normalized["alias"] == ["mPFC", "PFC"]
    assert normalized["dedupe_key"] == "MPFC_LEFT"
