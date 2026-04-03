from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.services.ontology_gate import detect_relation_type
from scripts.utils.deepseek_client import DeepSeekClient
from scripts.utils.id_utils import connection_id
from scripts.utils.io_utils import read_jsonl, write_json, write_jsonl
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id
from scripts.validate.major_crosscheck import crosscheck_connections

VALID_RELATION_TYPES = {
    "direct_structural_connection",
    "indirect_pathway_connection",
    "same_circuit_member",
}


def _try_parse_json_text(value: str) -> Any:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
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
    if isinstance(result, dict):
        for key in ("items", "data", "records", "rows", "result", "connections", "payload"):
            candidate = result.get(key)
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, str):
                parsed = _try_parse_json_text(candidate)
                if isinstance(parsed, list):
                    return parsed
        if any(k in result for k in ("source_major_region_id", "target_major_region_id")):
            return [result]
    return None


def _response_shape(result: Any) -> str:
    if isinstance(result, dict):
        return f"dict(keys={list(result.keys())[:10]})"
    if isinstance(result, list):
        return f"list(len={len(result)})"
    return type(result).__name__


def _response_preview(result: Any, limit: int = 320) -> str:
    try:
        text = json.dumps(result, ensure_ascii=False)
    except Exception:
        text = str(result)
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "..."


def _to_confidence(value: Any, default: float = 0.5) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    lexical = {
        "high": 0.85,
        "medium": 0.6,
        "mid": 0.6,
        "low": 0.35,
        "unknown": default,
    }
    if text in lexical:
        return lexical[text]
    try:
        return float(text)
    except Exception:
        return default


def _normalize_modality(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    mapping = {
        "structural": "structural",
        "anatomical": "structural",
        "tract": "structural",
        "functional": "functional",
        "fc": "functional",
        "effective": "effective",
        "causal": "effective",
        "unknown": "unknown",
    }
    return mapping.get(text, "unknown")


def _normalize_relation_type(value: Any) -> str:
    detected = detect_relation_type(str(value or ""))
    if detected:
        return detected
    return "indirect_pathway_connection"


def _derive_connections_from_circuits(circuits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for circuit in circuits:
        circuit_id_value = str(circuit.get("major_circuit_id") or "")
        circuit_conf = _to_confidence(circuit.get("confidence_circuit"), default=0.5)
        circuit_kind = str(circuit.get("circuit_kind") or "unknown")

        decomposed = circuit.get("decomposed_relations", [])
        if isinstance(decomposed, list) and decomposed:
            relation_rows = [item for item in decomposed if isinstance(item, dict)]
        else:
            # Backward compatibility: derive from node_ids if decomposed relations are absent.
            relation_rows = []
            nodes = [str(n) for n in circuit.get("node_ids", []) if n]
            for idx in range(len(nodes) - 1):
                relation_rows.append(
                    {
                        "source_major_region_id": nodes[idx],
                        "target_major_region_id": nodes[idx + 1],
                        "connection_modality": "structural" if circuit_kind == "structural" else "unknown",
                        "relation_type": "direct_structural_connection",
                        "directionality": "forward",
                        "confidence": circuit_conf,
                        "rationale_short": "Derived from adjacent circuit nodes.",
                    }
                )

        for relation in relation_rows:
            source = str(relation.get("source_major_region_id") or "").strip()
            target = str(relation.get("target_major_region_id") or "").strip()
            if not source or not target or source == target:
                continue
            modality = _normalize_modality(relation.get("connection_modality"))
            relation_type = _normalize_relation_type(relation.get("relation_type"))
            key = (source, target, modality, relation_type)
            confidence = _to_confidence(relation.get("confidence"), default=circuit_conf)

            record = out.get(key)
            if not record:
                conn_id = connection_id(source, target, modality, relation_type)
                out[key] = {
                    "major_connection_id": conn_id,
                    "connection_code": conn_id,
                    "en_name": f"{source} to {target}",
                    "cn_name": "",
                    "alias": [],
                    "description": str(relation.get("rationale_short") or "Derived from circuit framework."),
                    "connection_modality": modality,
                    "relation_type": relation_type,
                    "source_major_region_id": source,
                    "target_major_region_id": target,
                    "confidence": confidence,
                    "validation_status": "cross_fail_unverified",
                    "direction_label": str(relation.get("directionality") or f"{source}->{target}"),
                    "extraction_method": "deepseek_circuit_derived",
                    "data_source": "deepseek",
                    "status": "active",
                    "remark": f"derived_from={circuit_id_value}",
                    "supported_by_circuit_ids": [circuit_id_value] if circuit_id_value else [],
                    "supported_by_circuit_confidence": circuit_conf,
                    "need_literature_verification": bool(relation.get("need_literature_verification", False)),
                    "evidence": [],
                }
                continue

            record["confidence"] = max(_to_confidence(record.get("confidence"), 0.0), confidence)
            existing_ids = set(record.get("supported_by_circuit_ids", []))
            if circuit_id_value:
                existing_ids.add(circuit_id_value)
            record["supported_by_circuit_ids"] = sorted(existing_ids)
            record["supported_by_circuit_confidence"] = max(
                _to_confidence(record.get("supported_by_circuit_confidence"), 0.0),
                circuit_conf,
            )
    return list(out.values())


def _deepseek_direct_connections(regions: list[dict[str, Any]], circuits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    client = DeepSeekClient()
    region_payload = [
        {
            "major_region_id": item.get("major_region_id"),
            "en_name": item.get("en_name"),
            "cn_name": item.get("cn_name"),
        }
        for item in regions
    ]
    circuit_payload = [
        {
            "major_circuit_id": item.get("major_circuit_id"),
            "circuit_family": item.get("circuit_family"),
            "node_ids": item.get("node_ids", []),
            "confidence_circuit": item.get("confidence_circuit"),
        }
        for item in circuits[:300]
    ]
    system_prompt = (
        "Generate major-region relationship candidates in JSON array only.\n"
        "Each item keys:\n"
        "- source_major_region_id\n"
        "- target_major_region_id\n"
        "- connection_modality (structural|functional|effective|unknown)\n"
        "- relation_type (direct_structural_connection|indirect_pathway_connection|same_circuit_member)\n"
        "- confidence\n"
        "- directionality\n"
        "- description\n"
    )
    user_prompt = (
        "Use region catalog and circuit candidates to generate direct relationship candidates.\n"
        "Prefer high-coverage but avoid hallucinating unknown region ids.\n"
        "Input JSON:\n"
        + json.dumps(
            {
                "region_catalog": region_payload,
                "circuit_candidates": circuit_payload,
            },
            ensure_ascii=False,
        )
    )
    result = client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.2, max_tokens=3500)
    rows = _extract_array_payload(result)
    if rows is None:
        raise ValueError(
            "DeepSeek direct connection response must be JSON array. "
            f"shape={_response_shape(result)} preview={_response_preview(result)}"
        )

    allowed_region_ids = {str(item.get("major_region_id") or "").strip() for item in regions if item.get("major_region_id")}
    out: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source_major_region_id") or "").strip()
        target = str(row.get("target_major_region_id") or "").strip()
        if not source or not target or source == target:
            continue
        if source not in allowed_region_ids or target not in allowed_region_ids:
            continue
        modality = _normalize_modality(row.get("connection_modality"))
        relation_type = _normalize_relation_type(row.get("relation_type"))
        if relation_type not in VALID_RELATION_TYPES:
            continue
        key = (source, target, modality, relation_type)
        confidence = _to_confidence(row.get("confidence"), default=0.52)
        if key in out and _to_confidence(out[key].get("confidence"), 0.0) >= confidence:
            continue
        conn_id = connection_id(source, target, modality, relation_type)
        out[key] = {
            "major_connection_id": conn_id,
            "connection_code": conn_id,
            "en_name": f"{source} to {target}",
            "cn_name": "",
            "alias": [],
            "description": str(row.get("description") or "Direct deepseek extraction."),
            "connection_modality": modality,
            "relation_type": relation_type,
            "source_major_region_id": source,
            "target_major_region_id": target,
            "confidence": confidence,
            "validation_status": "cross_fail_unverified",
            "direction_label": str(row.get("directionality") or f"{source}->{target}"),
            "extraction_method": "deepseek_direct",
            "data_source": "deepseek",
            "status": "active",
            "remark": "direct_connection",
            "supported_by_circuit_ids": [],
            "supported_by_circuit_confidence": 0.0,
            "need_literature_verification": bool(row.get("need_literature_verification", False)),
            "evidence": [],
        }
    return list(out.values())


def run_extract_major_connections(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
    circuits_path: str | Path | None = None,
    regions_path: str | Path | None = None,
) -> dict[str, Any]:
    config = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    input_dir = Path(input_path)

    configured_circuits = circuits_path or config.get("pipeline", {}).get("major_circuits_path", "")
    configured_regions = regions_path or config.get("pipeline", {}).get("major_regions_path", "")
    circuits_path = Path(configured_circuits) if configured_circuits else input_dir / "major_circuits.validated.jsonl"
    regions_path = Path(configured_regions) if configured_regions else input_dir / "major_regions.validated.jsonl"
    if not circuits_path.exists():
        circuits_path = input_dir / "major_circuits.raw.jsonl"
    if not regions_path.exists():
        regions_path = input_dir / "major_regions.validated.jsonl"

    circuits = read_jsonl(circuits_path)
    regions = read_jsonl(regions_path)
    derived = _derive_connections_from_circuits(circuits)
    direct = _deepseek_direct_connections(regions, circuits) if bool(config.get("llm", {}).get("use_deepseek", True)) else []

    cross_cfg = config.get("pipeline", {})
    high_conf = float(cross_cfg.get("major_crosscheck_high_confidence", 0.70))
    ratio_threshold = float(cross_cfg.get("major_crosscheck_circuit_hit_ratio", 0.50))
    min_hit_count = int(cross_cfg.get("major_crosscheck_circuit_hit_min", 2))

    merged_all, pass_records, only_derived, only_direct, low_support_both, cross_summary = crosscheck_connections(
        derived=derived,
        direct=direct,
        circuits=circuits,
        high_confidence_threshold=high_conf,
        ratio_threshold=ratio_threshold,
        min_hit_count=min_hit_count,
    )
    for item in merged_all:
        item["run_id"] = resolved_run_id

    output = Path(output_path)
    write_jsonl(output, merged_all)
    write_jsonl(output.with_name(output.stem + ".derived.jsonl"), derived)
    write_jsonl(output.with_name(output.stem + ".direct.jsonl"), direct)
    write_jsonl(output.with_name(output.stem + ".cross_pass.jsonl"), pass_records)
    write_jsonl(output.with_name(output.stem + ".cross_fail_only_derived.jsonl"), only_derived)
    write_jsonl(output.with_name(output.stem + ".cross_fail_only_direct.jsonl"), only_direct)
    write_jsonl(output.with_name(output.stem + ".cross_fail_both_low_support.jsonl"), low_support_both)

    relation_counts: dict[str, int] = {}
    for item in merged_all:
        key = str(item.get("relation_type") or "unknown")
        relation_counts[key] = relation_counts.get(key, 0) + 1

    report = {
        "stage": "extract_major_connections",
        "run_id": resolved_run_id,
        "derived_records": len(derived),
        "direct_records": len(direct),
        "cross_pass_records": len(pass_records),
        "cross_fail_only_derived_records": len(only_derived),
        "cross_fail_only_direct_records": len(only_direct),
        "cross_fail_both_low_support_records": len(low_support_both),
        "relation_type_counts": relation_counts,
        "cross_summary": cross_summary,
        "output_records": len(merged_all),
        "output_path": str(output),
    }
    write_json(output.with_suffix(".report.json"), report)
    return report


def main() -> None:
    parser = build_common_parser("Extract major connections (circuit-derived + direct + support-crosscheck).")
    args = parser.parse_args()
    report = run_extract_major_connections(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"extract_major_connections done: {report['output_records']}")


if __name__ == "__main__":
    main()
