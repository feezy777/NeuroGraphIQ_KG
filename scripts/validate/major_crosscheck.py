from __future__ import annotations

from typing import Any


def connection_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record.get("source_major_region_id") or ""),
        str(record.get("target_major_region_id") or ""),
        str(record.get("connection_modality") or ""),
        str(record.get("relation_type") or ""),
    )


def _to_score(value: Any, default: float = 0.0) -> float:
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


def _merge_base(derived_item: dict[str, Any] | None, direct_item: dict[str, Any] | None) -> dict[str, Any]:
    if derived_item and direct_item:
        merged = dict(derived_item)
        for key in ("description", "direction_label", "remark"):
            if not merged.get(key):
                merged[key] = direct_item.get(key)
        merged["confidence"] = max(_to_score(derived_item.get("confidence")), _to_score(direct_item.get("confidence")))
        merged["data_source"] = "deepseek_crosscheck"
        return merged
    if derived_item:
        return dict(derived_item)
    if direct_item:
        return dict(direct_item)
    return {}


def _collect_circuit_support(
    circuits: list[dict[str, Any]],
    direct_by_key: dict[tuple[str, str, str, str], dict[str, Any]],
    high_confidence_threshold: float,
    ratio_threshold: float,
    min_hit_count: int,
) -> dict[str, dict[str, Any]]:
    direct_high_keys = {
        key
        for key, item in direct_by_key.items()
        if _to_score(item.get("confidence"), default=0.0) >= high_confidence_threshold
    }
    support: dict[str, dict[str, Any]] = {}
    for circuit in circuits:
        circuit_id = str(circuit.get("major_circuit_id") or "").strip()
        if not circuit_id:
            continue
        relation_keys: set[tuple[str, str, str, str]] = set()
        for rel in circuit.get("decomposed_relations", []):
            if not isinstance(rel, dict):
                continue
            relation_type = str(rel.get("relation_type") or "")
            if relation_type not in {"direct_structural_connection", "indirect_pathway_connection"}:
                continue
            key = (
                str(rel.get("source_major_region_id") or ""),
                str(rel.get("target_major_region_id") or ""),
                str(rel.get("connection_modality") or ""),
                relation_type,
            )
            if key[0] and key[1]:
                relation_keys.add(key)
        total = len(relation_keys)
        hit_count = len(relation_keys & direct_high_keys)
        hit_ratio = (hit_count / total) if total else 0.0
        supported = total > 0 and (hit_ratio >= ratio_threshold or hit_count >= min_hit_count)
        support[circuit_id] = {
            "supported": supported,
            "hit_count": hit_count,
            "total": total,
            "hit_ratio": round(hit_ratio, 6),
        }
    return support


def crosscheck_connections(
    derived: list[dict[str, Any]],
    direct: list[dict[str, Any]],
    circuits: list[dict[str, Any]],
    high_confidence_threshold: float = 0.70,
    ratio_threshold: float = 0.50,
    min_hit_count: int = 2,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    by_key_derived = {connection_key(item): item for item in derived}
    by_key_direct = {connection_key(item): item for item in direct}
    circuit_support = _collect_circuit_support(
        circuits=circuits,
        direct_by_key=by_key_direct,
        high_confidence_threshold=high_confidence_threshold,
        ratio_threshold=ratio_threshold,
        min_hit_count=min_hit_count,
    )

    pass_records: list[dict[str, Any]] = []
    fail_only_derived: list[dict[str, Any]] = []
    fail_only_direct: list[dict[str, Any]] = []
    fail_both_low_support: list[dict[str, Any]] = []
    merged_all: list[dict[str, Any]] = []
    pass_by_high_conf_circuit = 0
    pass_by_high_conf_connection = 0

    all_keys = set(by_key_derived.keys()) | set(by_key_direct.keys())
    for key in sorted(all_keys):
        d = by_key_derived.get(key)
        c = by_key_direct.get(key)
        merged = _merge_base(d, c)
        if not merged:
            continue

        support_ids = sorted(
            {
                str(cid)
                for cid in (
                    list(d.get("supported_by_circuit_ids", [])) if isinstance(d, dict) else []
                )
                if str(cid)
            }
        )
        derived_support_conf = _to_score(
            d.get("supported_by_circuit_confidence", d.get("confidence")) if isinstance(d, dict) else None,
            default=0.0,
        )
        support_high_conf_circuit = bool(support_ids and derived_support_conf >= high_confidence_threshold)
        support_high_conf_connection = any(bool(circuit_support.get(cid, {}).get("supported", False)) for cid in support_ids)

        if support_high_conf_circuit:
            pass_by_high_conf_circuit += 1
        if support_high_conf_connection:
            pass_by_high_conf_connection += 1

        is_pass = support_high_conf_circuit or support_high_conf_connection
        merged["support_by_high_conf_circuit"] = support_high_conf_circuit
        merged["support_by_high_conf_connection"] = support_high_conf_connection
        merged["supported_by_circuit_ids"] = support_ids

        if is_pass:
            merged["crosscheck_bucket"] = "cross_pass"
            merged["validation_status"] = "cross_pass_unverified"
            merged["extraction_method"] = "deepseek_crosscheck"
            merged["remark"] = "support_pass(circuit_or_connection)"
            pass_records.append(merged)
            merged_all.append(merged)
            continue

        if d and not c:
            merged["crosscheck_bucket"] = "cross_fail_only_derived"
            merged["validation_status"] = "cross_fail_unverified"
            merged["extraction_method"] = "deepseek_circuit_derived"
            merged["remark"] = "only_in_derived_without_support"
            fail_only_derived.append(merged)
            merged_all.append(merged)
            continue
        if c and not d:
            merged["crosscheck_bucket"] = "cross_fail_only_direct"
            merged["validation_status"] = "cross_fail_unverified"
            merged["extraction_method"] = "deepseek_direct"
            merged["remark"] = "only_in_direct_without_support"
            fail_only_direct.append(merged)
            merged_all.append(merged)
            continue

        merged["crosscheck_bucket"] = "cross_fail_both_low_support"
        merged["validation_status"] = "cross_fail_unverified"
        merged["extraction_method"] = "deepseek_crosscheck"
        merged["remark"] = "both_present_but_low_support"
        fail_both_low_support.append(merged)
        merged_all.append(merged)

    summary = {
        "high_confidence_threshold": high_confidence_threshold,
        "ratio_threshold": ratio_threshold,
        "min_hit_count": min_hit_count,
        "pass_by_high_conf_circuit": pass_by_high_conf_circuit,
        "pass_by_high_conf_connection": pass_by_high_conf_connection,
        "circuit_support": circuit_support,
    }
    return merged_all, pass_records, fail_only_derived, fail_only_direct, fail_both_low_support, summary
