"""Macro96 Excel parser — converts macro_region_table_v1 intermediate to raw row dicts.

Input: content_jsonb from a FileIntermediateArtifact with artifact_kind=macro_region_table.
Output: list of raw row dicts (one per Excel row).

Boundaries (strictly enforced):
- Does NOT call LLM.
- Does NOT write to DB.
- Does NOT generate candidates, final_*, or kg_*.
- Does NOT parse AAL3 XML.
"""

from __future__ import annotations

from typing import Any

PARSER_KEY = "macro96_xlsx"
PARSER_VERSION = "v1"
EXPECTED_SCHEMA = "macro_region_table_v1"


class Macro96ParseError(ValueError):
    """Raised when content_jsonb rows are invalid or cannot be parsed."""


class Macro96IntermediateInvalidError(ValueError):
    """Raised when content_jsonb does not conform to macro_region_table_v1 schema."""


def parse_macro96_table_from_intermediate(content_jsonb: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse macro_region_table_v1 content_jsonb into raw row dicts.

    Args:
        content_jsonb: The content_jsonb field of a FileIntermediateArtifact
                       with artifact_kind=macro_region_table.

    Returns:
        List of row dicts with keys:
          row_index, region_index, en_name, cn_name,
          raw_brain_structure, raw_cn_name, source_sheet, raw_payload

    Raises:
        Macro96IntermediateInvalidError: schema mismatch or rows missing.
        Macro96ParseError: empty rows, duplicate region_index, bad region_index.
    """
    if not isinstance(content_jsonb, dict):
        raise Macro96IntermediateInvalidError(
            f"content_jsonb must be a dict, got {type(content_jsonb).__name__}"
        )

    schema = content_jsonb.get("schema")
    if schema != EXPECTED_SCHEMA:
        raise Macro96IntermediateInvalidError(
            f"expected schema={EXPECTED_SCHEMA!r}, got {schema!r}"
        )

    rows = content_jsonb.get("rows")
    if not isinstance(rows, list):
        raise Macro96IntermediateInvalidError(
            f"content_jsonb.rows must be a list, got {type(rows).__name__}"
        )

    if len(rows) == 0:
        raise Macro96ParseError("content_jsonb.rows is empty — nothing to parse")

    declared_row_count = content_jsonb.get("row_count")
    if declared_row_count is not None and int(declared_row_count) != len(rows):
        # Warning-level mismatch — log but continue unless severe
        if abs(int(declared_row_count) - len(rows)) > 10:
            raise Macro96ParseError(
                f"row_count={declared_row_count} declared but {len(rows)} rows found — "
                "severe mismatch, refusing to parse"
            )

    source_sheet = content_jsonb.get("source_sheet")

    seen_region_indices: set[int] = set()
    result: list[dict[str, Any]] = []

    for row_idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise Macro96ParseError(f"row[{row_idx}] is not a dict: {row!r}")

        # region_index
        raw_idx = row.get("region_index")
        if raw_idx is None:
            raise Macro96ParseError(f"row[{row_idx}] missing region_index")
        try:
            region_index = int(raw_idx)
        except (TypeError, ValueError) as exc:
            raise Macro96ParseError(
                f"row[{row_idx}] region_index={raw_idx!r} cannot be converted to int"
            ) from exc
        if region_index <= 0:
            raise Macro96ParseError(
                f"row[{row_idx}] region_index={region_index} must be > 0"
            )
        if region_index in seen_region_indices:
            raise Macro96ParseError(
                f"duplicate region_index={region_index} at row[{row_idx}]"
            )
        seen_region_indices.add(region_index)

        # en_name
        en_name_raw = row.get("en_name")
        if not en_name_raw or not str(en_name_raw).strip():
            raise Macro96ParseError(
                f"row[{row_idx}] region_index={region_index} has empty en_name"
            )
        en_name = str(en_name_raw).strip()

        # cn_name (optional)
        cn_name_raw = row.get("cn_name")
        cn_name = str(cn_name_raw).strip() if cn_name_raw and str(cn_name_raw).strip() else None

        result.append(
            {
                "row_index": row_idx,
                "region_index": region_index,
                "en_name": en_name,
                "cn_name": cn_name,
                "raw_brain_structure": en_name,
                "raw_cn_name": cn_name_raw if cn_name_raw is not None else None,
                "source_sheet": source_sheet,
                "raw_payload": dict(row),
            }
        )

    return result
