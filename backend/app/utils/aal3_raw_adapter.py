"""Adapt parse_aal3_xml output to raw_aal3_region_labels row dicts."""

from __future__ import annotations

import uuid
from typing import Any

from app.parsers.aal3_parser import PARSER_VERSION
from app.utils.aal3_laterality import extract_region_base_name, infer_laterality

PARSER_KEY_AAL3_XML = "aal3_xml"
DEFAULT_PARSER_VERSION = PARSER_VERSION


def xml_regions_to_raw_labels(
    *,
    regions: list[dict[str, Any]],
    parse_run_id: uuid.UUID,
    batch_id: uuid.UUID,
    resource_id: uuid.UUID,
    source_file_id: uuid.UUID,
    source_atlas: str,
    source_version: str,
    row_index_offset: int = 0,
) -> list[dict[str, Any]]:
    """Convert parse_aal3_xml records into raw_aal3_region_labels field dicts."""
    rows: list[dict[str, Any]] = []
    for idx, region in enumerate(regions):
        raw_name = region.get("abbr") or region.get("original_name") or region.get("full_name") or ""
        label_value = region.get("label_index")
        laterality = infer_laterality(raw_name, region.get("hemisphere"))
        rows.append(
            {
                "parse_run_id": parse_run_id,
                "batch_id": batch_id,
                "resource_id": resource_id,
                "source_file_id": source_file_id,
                "source_atlas": source_atlas,
                "source_version": source_version,
                "source_label_id": str(label_value) if label_value is not None else raw_name,
                "label_value": label_value,
                "raw_name": raw_name,
                "en_name": region.get("full_name") or raw_name,
                "cn_name": None,
                "laterality": laterality,
                "region_base_name": extract_region_base_name(raw_name),
                "raw_payload": region,
                "row_index": row_index_offset + idx,
            }
        )
    return rows
