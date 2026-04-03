from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.utils.constants import DIV_NON_LOBE_DIVISION_BRAIN_ID, ORG_HUMAN_ID
from scripts.utils.deepseek_client import DeepSeekClient
from scripts.utils.excel_reader import read_xlsx_rows
from scripts.utils.id_utils import (
    major_region_code,
    major_region_id,
    parse_laterality,
    slugify,
    strip_laterality_prefix,
)
from scripts.utils.io_utils import write_json, write_jsonl
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


def _try_parse_json_text(value: str) -> Any:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text, idx=idx)
            return parsed
        except Exception:
            continue
    return None


def _extract_array_payload(result: Any) -> list[Any] | None:
    if isinstance(result, list):
        return result
    if isinstance(result, str):
        parsed = _try_parse_json_text(result)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            result = parsed

    preferred_keys = ("items", "data", "records", "rows", "result", "major_regions", "mappings", "payload")
    queue: list[Any] = [result]
    visited: set[int] = set()
    singleton_keys = {"source_en_name", "major_en_name", "major_cn_name", "laterality", "region_category"}

    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            current_id = id(current)
            if current_id in visited:
                continue
            visited.add(current_id)
            if any(key in current for key in singleton_keys):
                return [current]

            for key in preferred_keys:
                candidate = current.get(key)
                if isinstance(candidate, list):
                    return candidate
                if isinstance(candidate, str):
                    parsed = _try_parse_json_text(candidate)
                    if isinstance(parsed, list):
                        return parsed
                    if isinstance(parsed, dict):
                        queue.append(parsed)

            for candidate in current.values():
                if isinstance(candidate, list):
                    return candidate
                if isinstance(candidate, str):
                    parsed = _try_parse_json_text(candidate)
                    if isinstance(parsed, list):
                        return parsed
                    if isinstance(parsed, dict):
                        queue.append(parsed)
                elif isinstance(candidate, dict):
                    queue.append(candidate)

    if isinstance(result, dict) and any(key in result for key in singleton_keys):
        return [result]
    return None


def _response_shape(result: Any) -> str:
    if isinstance(result, dict):
        return f"dict(keys={list(result.keys())[:10]})"
    if isinstance(result, list):
        return f"list(len={len(result)})"
    return type(result).__name__


def _response_preview(result: Any, limit: int = 280) -> str:
    try:
        text = json.dumps(result, ensure_ascii=False)
    except Exception:
        text = str(result)
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _cn_name_key(record: dict[str, str]) -> str:
    known_skip = {"ID #", "Brain Structure"}
    for key in record.keys():
        if key in known_skip:
            continue
        return key
    return ""


def _default_map(row: dict[str, str]) -> dict[str, Any]:
    en_name = str(row.get("Brain Structure") or "").strip()
    cn_key = _cn_name_key(row)
    cn_name = str(row.get(cn_key) or "").strip() if cn_key else ""
    laterality = parse_laterality(en_name)
    major_en = strip_laterality_prefix(en_name)
    return {
        "source_en_name": en_name,
        "source_cn_name": cn_name,
        "major_en_name": major_en,
        "major_cn_name": cn_name,
        "laterality": laterality,
        "region_category": "unknown",
    }


def _deepseek_map(rows: list[dict[str, str]], config: dict[str, Any]) -> list[dict[str, Any]]:
    batch_size = int(config.get("llm", {}).get("batch_size", 60))
    system_prompt = (
        "You map fine-grained brain structures to major brain regions. "
        "Return JSON array only. "
        "Each item must contain: source_en_name, source_cn_name, major_en_name, major_cn_name, laterality, region_category."
    )
    client = DeepSeekClient()
    mapped: list[dict[str, Any]] = []
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        user_prompt = (
            "Map the following structures into major brain regions while preserving side (left/right/midline/bilateral). "
            "Input JSON:\n"
            + json.dumps(chunk, ensure_ascii=False)
        )
        result = client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.1)
        result_array = _extract_array_payload(result)
        if result_array is None:
            raise ValueError(
                f"DeepSeek mapping response must be a JSON array. "
                f"shape={_response_shape(result)} preview={_response_preview(result)}"
            )
        for item in result_array:
            if isinstance(item, dict):
                mapped.append(item)
    return mapped


def _aggregate(mapped: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in mapped:
        major_en = str(item.get("major_en_name") or "").strip()
        if not major_en:
            continue
        laterality = str(item.get("laterality") or parse_laterality(major_en)).lower()
        if laterality not in {"left", "right", "midline", "bilateral"}:
            laterality = parse_laterality(major_en)
        key = (major_en.lower(), laterality)

        if key not in grouped:
            region_id = major_region_id(major_en, laterality)
            grouped[key] = {
                "major_region_id": region_id,
                "organism_id": ORG_HUMAN_ID,
                "division_id": DIV_NON_LOBE_DIVISION_BRAIN_ID,
                "region_code": major_region_code(major_en, laterality),
                "en_name": major_en,
                "cn_name": str(item.get("major_cn_name") or "").strip() or None,
                "alias": [],
                "description": f"Aggregated from Excel structures for {major_en}",
                "laterality": laterality,
                "region_category": str(item.get("region_category") or "unknown"),
                "ontology_source": "DeepSeek+Excel",
                "data_source": "Brain volume list.xlsx",
                "status": "active",
                "remark": "",
                "run_id": run_id,
                "source_structures": [],
            }
        src = str(item.get("source_en_name") or "").strip()
        if src:
            grouped[key]["source_structures"].append(src)

    records = list(grouped.values())
    for record in records:
        srcs = sorted(set(record["source_structures"]))
        record["source_structures"] = srcs
        record["alias"] = [slugify(s).upper() for s in srcs[:6]]
        record["remark"] = f"source_count={len(srcs)}"
    return records


def run_extract_major_regions(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    config = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)

    excel = config.get("excel", {})
    sheet_index = int(excel.get("sheet_index", 1))
    header_row = int(excel.get("header_row", 1))
    rows = read_xlsx_rows(input_path, sheet_index=sheet_index, header_row=header_row)
    mapped_rows = [_default_map(row) for row in rows]

    use_deepseek = bool(config.get("llm", {}).get("use_deepseek", True))
    if use_deepseek and rows:
        mapped_rows = _deepseek_map(rows, config)
    elif use_deepseek and not rows:
        raise ValueError("No rows found in Excel input.")

    aggregated = _aggregate(mapped_rows, resolved_run_id)
    output = Path(output_path)
    count = write_jsonl(output, aggregated)
    report = {
        "stage": "extract_major_regions",
        "run_id": resolved_run_id,
        "input_records": len(rows),
        "mapped_records": len(mapped_rows),
        "output_records": count,
        "output_path": str(output),
    }
    write_json(output.with_suffix(".report.json"), report)
    return report


def main() -> None:
    parser = build_common_parser("Extract major regions from Excel using DeepSeek mapping.")
    args = parser.parse_args()
    report = run_extract_major_regions(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"extract_major_regions done: {report['output_records']}")


if __name__ == "__main__":
    main()
