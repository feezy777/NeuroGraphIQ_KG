from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from scripts.utils.deepseek_client import DeepSeekClient
from scripts.utils.id_utils import circuit_id
from scripts.utils.io_utils import read_jsonl, write_json, write_jsonl
from scripts.utils.runtime import build_common_parser, load_optional_config, resolve_run_id


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
        preferred_keys = ("items", "data", "rows", "result", "families", "instances", "circuits", "payload")
        for key in preferred_keys:
            candidate = result.get(key)
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, str):
                parsed = _try_parse_json_text(candidate)
                if isinstance(parsed, list):
                    return parsed
        if any(k in result for k in ("circuit_family", "circuit_name", "nodes")):
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


def _norm_token(value: str) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _score(value: Any, default: float = 0.55) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    lexical = {"high": 0.85, "medium": 0.65, "mid": 0.65, "low": 0.4}
    if text in lexical:
        return lexical[text]
    try:
        return float(text)
    except Exception:
        return default


def _normalize_kind(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    mapping = {
        "structural": "structural",
        "anatomical": "structural",
        "functional": "functional",
        "regulatory": "functional",
        "pathway": "inferred",
        "inferred": "inferred",
        "unknown": "unknown",
    }
    return mapping.get(text, "unknown")


def _normalize_loop_type(value: Any) -> str:
    text = str(value or "inferred").strip().lower()
    mapping = {
        "strict": "strict",
        "closed": "strict",
        "inferred": "inferred",
        "pathway": "inferred",
        "functional": "functional",
    }
    return mapping.get(text, "inferred")


def _semantics_to_kind(loop_semantics: str) -> str:
    value = str(loop_semantics or "").strip().lower()
    if value == "pathway":
        return "structural"
    if value == "functional":
        return "functional"
    if value == "regulatory":
        return "inferred"
    return "inferred"


def _load_family_templates(config: dict[str, Any]) -> list[dict[str, Any]]:
    configured = str(config.get("pipeline", {}).get("circuit_families_path", "")).strip()
    if configured:
        path = Path(configured)
    else:
        path = Path(__file__).resolve().parents[2] / "configs" / "pipeline" / "circuit_families.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Circuit family config not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    families = payload.get("families", [])
    if not isinstance(families, list):
        return []
    return [item for item in families if isinstance(item, dict) and str(item.get("circuit_family") or "").strip()]


def _build_region_catalog(regions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    catalog: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for region in regions:
        region_id = str(region.get("major_region_id") or "").strip()
        if not region_id:
            continue
        row = {
            "major_region_id": region_id,
            "en_name": str(region.get("en_name") or "").strip(),
            "cn_name": str(region.get("cn_name") or "").strip(),
            "laterality": str(region.get("laterality") or "").strip(),
        }
        catalog.append(row)
        by_id[region_id] = row
    return catalog, by_id


def _region_match_tokens(region: dict[str, Any]) -> set[str]:
    tokens = {
        _norm_token(region.get("major_region_id", "")),
        _norm_token(region.get("en_name", "")),
        _norm_token(region.get("cn_name", "")),
    }
    tokens.discard("")
    return tokens


def _alias_match(alias: str, region: dict[str, Any]) -> bool:
    alias_token = _norm_token(alias)
    if not alias_token:
        return False
    for candidate in _region_match_tokens(region):
        if alias_token in candidate or candidate in alias_token:
            return True
    return False


def _match_alias_group(alias_group: list[str], catalog: list[dict[str, Any]]) -> list[str]:
    matched: list[str] = []
    for region in catalog:
        if any(_alias_match(alias, region) for alias in alias_group):
            matched.append(str(region["major_region_id"]))
    return sorted(set(matched))


def _heuristic_family_recall(
    catalog: list[dict[str, Any]],
    families: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recalls: list[dict[str, Any]] = []
    for family in families:
        family_id = str(family.get("circuit_family") or "")
        core_groups = [group for group in family.get("core_node_aliases", []) if isinstance(group, list)]
        optional_groups = [group for group in family.get("optional_node_aliases", []) if isinstance(group, list)]

        matched_nodes: set[str] = set()
        missing_groups: list[str] = []
        core_hits = 0
        for group in core_groups:
            group_hits = _match_alias_group([str(x) for x in group], catalog)
            if group_hits:
                core_hits += 1
                matched_nodes.update(group_hits)
            else:
                missing_groups.append(str(group[0]) if group else "unknown")

        optional_hits = 0
        for group in optional_groups:
            group_hits = _match_alias_group([str(x) for x in group], catalog)
            if group_hits:
                optional_hits += 1
                matched_nodes.update(group_hits)

        if len(matched_nodes) < 2:
            continue

        confidence = min(0.95, 0.45 + 0.12 * core_hits + 0.05 * optional_hits)
        recalls.append(
            {
                "circuit_family": family_id,
                "functional_domain": str(family.get("functional_domain") or "unknown"),
                "involved_input_regions": sorted(matched_nodes),
                "why_relevant": (
                    f"core_hits={core_hits}/{max(1, len(core_groups))}, "
                    f"optional_hits={optional_hits}/{max(1, len(optional_groups))}"
                ),
                "confidence": round(confidence, 4),
                "expected_missing_nodes": missing_groups,
                "priority_for_literature_search": "high" if missing_groups else "medium",
            }
        )
    recalls.sort(key=lambda x: (-_score(x.get("confidence"), 0.0), x.get("circuit_family", "")))
    return recalls


def _deepseek_family_recall(
    catalog: list[dict[str, Any]],
    families: list[dict[str, Any]],
    target_count: int,
) -> list[dict[str, Any]]:
    client = DeepSeekClient()
    family_payload = [
        {
            "circuit_family": str(f.get("circuit_family") or ""),
            "functional_domain": str(f.get("functional_domain") or ""),
            "aliases": f.get("aliases", []),
            "core_node_aliases": f.get("core_node_aliases", []),
            "optional_node_aliases": f.get("optional_node_aliases", []),
        }
        for f in families
    ]
    system_prompt = (
        "You are doing circuit family recall for major brain regions.\n"
        "Return strict JSON array only.\n"
        "Each item keys:\n"
        "- circuit_family\n"
        "- involved_input_regions (array of major_region_id)\n"
        "- functional_domain\n"
        "- why_relevant\n"
        "- confidence\n"
        "- expected_missing_nodes (array)\n"
        "- priority_for_literature_search\n"
    )
    user_prompt = (
        "Recall as many relevant circuit families as possible for coverage.\n"
        f"Target count >= {max(8, target_count)}.\n"
        "Input JSON:\n"
        + json.dumps(
            {
                "families": family_payload,
                "region_catalog": catalog,
            },
            ensure_ascii=False,
        )
    )
    result = client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.15, max_tokens=3500)
    rows = _extract_array_payload(result)
    if rows is None:
        raise ValueError(
            "DeepSeek family recall response must be JSON array. "
            f"shape={_response_shape(result)} preview={_response_preview(result)}"
        )
    out: list[dict[str, Any]] = []
    catalog_ids = {str(item.get("major_region_id") or "") for item in catalog}
    for row in rows:
        if not isinstance(row, dict):
            continue
        family = str(row.get("circuit_family") or "").strip()
        regions = [str(x) for x in row.get("involved_input_regions", []) if str(x)]
        regions = [x for x in regions if x in catalog_ids]
        if not family or len(regions) < 2:
            continue
        out.append(
            {
                "circuit_family": family,
                "functional_domain": str(row.get("functional_domain") or "unknown"),
                "involved_input_regions": sorted(set(regions)),
                "why_relevant": str(row.get("why_relevant") or ""),
                "confidence": round(_score(row.get("confidence"), default=0.6), 4),
                "expected_missing_nodes": [str(x) for x in row.get("expected_missing_nodes", []) if str(x)],
                "priority_for_literature_search": str(row.get("priority_for_literature_search") or "medium"),
            }
        )
    return out


def _merge_recall(heuristic: list[dict[str, Any]], llm: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in heuristic + llm:
        key = str(item.get("circuit_family") or "")
        if not key:
            continue
        existed = merged.get(key)
        if not existed:
            merged[key] = dict(item)
            continue
        existed_regions = set(existed.get("involved_input_regions", []))
        existed_regions.update(item.get("involved_input_regions", []))
        existed["involved_input_regions"] = sorted(existed_regions)
        existed["confidence"] = round(max(_score(existed.get("confidence")), _score(item.get("confidence"))), 4)
        existing_missing = set(existed.get("expected_missing_nodes", []))
        existing_missing.update(item.get("expected_missing_nodes", []))
        existed["expected_missing_nodes"] = sorted(existing_missing)
        if len(str(item.get("why_relevant") or "")) > len(str(existed.get("why_relevant") or "")):
            existed["why_relevant"] = str(item.get("why_relevant") or "")
        if str(item.get("priority_for_literature_search") or "").lower() == "high":
            existed["priority_for_literature_search"] = "high"
    rows = list(merged.values())
    rows.sort(key=lambda x: (-_score(x.get("confidence"), 0.0), str(x.get("circuit_family") or "")))
    return rows


def _build_seed_windows(seed_region_id: str, nodes: list[str]) -> list[list[str]]:
    ordered = [str(x) for x in nodes if str(x)]
    if seed_region_id not in ordered:
        return []
    others = [item for item in ordered if item != seed_region_id]
    windows: list[list[str]] = []

    # Always keep one compact seed-first window.
    windows.append([seed_region_id] + others[:2])

    # Expand to broader windows for richer relation decomposition.
    if len(others) >= 3:
        windows.append([seed_region_id] + others[:3])
    if len(others) >= 4:
        windows.append([seed_region_id] + others[:4])

    # Keep one original-order window (forcing seed to the first position).
    if len(ordered) > 2:
        original = ordered[:5]
        if original[0] != seed_region_id:
            original = [seed_region_id] + [x for x in original if x != seed_region_id]
        windows.append(original)

    deduped: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for window in windows:
        uniq: list[str] = []
        for node_id in window:
            if node_id not in uniq:
                uniq.append(node_id)
        if len(uniq) < 2:
            continue
        key = tuple(uniq)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(uniq)
    return deduped


def _build_instances_by_seed_traversal(
    seed_region_ids: list[str],
    recalls: list[dict[str, Any]],
    families_by_id: dict[str, dict[str, Any]],
    target_count: int,
    per_seed_cap: int,
    hard_cap: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    instances: list[dict[str, Any]] = []
    traversal_rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for seed_region_id in seed_region_ids:
        attempted_families = len(families_by_id)
        seed_recalls = [
            item
            for item in recalls
            if seed_region_id in [str(x) for x in item.get("involved_input_regions", []) if str(x)]
        ]
        seed_recalls.sort(key=lambda x: (-_score(x.get("confidence"), 0.0), str(x.get("circuit_family") or "")))

        built_for_seed = 0
        matched_families: list[str] = []
        for recall in seed_recalls:
            if len(instances) >= hard_cap:
                break
            if built_for_seed >= per_seed_cap:
                break

            family_id = str(recall.get("circuit_family") or "")
            if not family_id:
                continue
            matched_families.append(family_id)
            family = families_by_id.get(family_id, {})
            nodes = [str(x) for x in recall.get("involved_input_regions", []) if str(x)]
            windows = _build_seed_windows(seed_region_id=seed_region_id, nodes=nodes)
            if not windows:
                continue

            for index, window in enumerate(windows, start=1):
                if len(instances) >= hard_cap:
                    break
                if built_for_seed >= per_seed_cap:
                    break

                key = f"{seed_region_id}|{family_id}|{'->'.join(window)}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                missing_key_nodes = [str(x) for x in recall.get("expected_missing_nodes", []) if str(x)]
                compressed = bool(missing_key_nodes)
                loop_semantics = str(family.get("loop_semantics") or "functional")
                confidence = _score(recall.get("confidence"), default=0.55)
                if compressed:
                    confidence = max(0.3, confidence - 0.08)

                instances.append(
                    {
                        "instance_key": key,
                        "seed_region_id": seed_region_id,
                        "circuit_name": f"{family_id}_{seed_region_id.lower()}_{index}",
                        "circuit_family": family_id,
                        "nodes_present": window,
                        "missing_key_nodes": missing_key_nodes,
                        "compressed": compressed,
                        "loop_semantics": loop_semantics,
                        "confidence": round(confidence, 4),
                        "rationale_short": str(recall.get("why_relevant") or ""),
                        "recommended_search_queries": family.get("recommended_search_queries", []),
                    }
                )
                built_for_seed += 1

        traversal_rows.append(
            {
                "seed_region_id": seed_region_id,
                "attempted_families": attempted_families,
                "matched_families": sorted(set(matched_families)),
                "matched_family_count": len(set(matched_families)),
                "built_instances": built_for_seed,
                "status": "matched" if built_for_seed > 0 else "uncovered",
            }
        )

    return instances, traversal_rows


def _build_instances(
    recalls: list[dict[str, Any]],
    families_by_id: dict[str, dict[str, Any]],
    target_count: int,
) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for recall in recalls:
        family_id = str(recall.get("circuit_family") or "")
        family = families_by_id.get(family_id, {})
        nodes = [str(x) for x in recall.get("involved_input_regions", []) if str(x)]
        if len(nodes) < 2:
            continue

        base_nodes = nodes[: min(6, len(nodes))]
        windows: list[list[str]] = [base_nodes]
        for width in (3, 4, 5):
            if len(nodes) < width:
                continue
            for i in range(0, len(nodes) - width + 1):
                windows.append(nodes[i : i + width])

        index = 1
        for window in windows:
            uniq_nodes: list[str] = []
            for node_id in window:
                if node_id not in uniq_nodes:
                    uniq_nodes.append(node_id)
            if len(uniq_nodes) < 2:
                continue

            key = f"{family_id}|{'->'.join(uniq_nodes)}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            missing_key_nodes = [str(x) for x in recall.get("expected_missing_nodes", []) if str(x)]
            compressed = bool(missing_key_nodes)
            loop_semantics = str(family.get("loop_semantics") or "functional")
            confidence = _score(recall.get("confidence"), default=0.55)
            if compressed:
                confidence = max(0.3, confidence - 0.08)

            instances.append(
                {
                    "instance_key": key,
                    "circuit_name": f"{family_id}_inst_{index}",
                    "circuit_family": family_id,
                    "nodes_present": uniq_nodes,
                    "missing_key_nodes": missing_key_nodes,
                    "compressed": compressed,
                    "loop_semantics": loop_semantics,
                    "confidence": round(confidence, 4),
                    "rationale_short": str(recall.get("why_relevant") or ""),
                    "recommended_search_queries": family.get("recommended_search_queries", []),
                }
            )
            index += 1
            if len(instances) >= target_count:
                return instances
    return instances


def _decompose_connections(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decomposed: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for instance in instances:
        circuit_key = str(instance.get("instance_key") or "")
        confidence = _score(instance.get("confidence"), default=0.5)
        nodes = [str(node) for node in instance.get("nodes_present", []) if str(node)]
        if len(nodes) < 2:
            continue

        # Adjacent edges as direct candidate.
        for idx in range(len(nodes) - 1):
            source = nodes[idx]
            target = nodes[idx + 1]
            relation_type = "direct_structural_connection"
            modality = "structural"
            key = (source, target, modality, relation_type)
            if key not in seen:
                seen.add(key)
                decomposed.append(
                    {
                        "source_major_region_id": source,
                        "target_major_region_id": target,
                        "connection_modality": modality,
                        "relation_type": relation_type,
                        "directionality": "forward",
                        "supported_by_circuit": circuit_key,
                        "confidence": round(confidence, 4),
                        "need_literature_verification": bool(instance.get("compressed")),
                        "rationale_short": "Adjacent nodes in circuit instance.",
                    }
                )

        # Skip-one-or-more nodes as indirect pathway.
        for left in range(len(nodes)):
            for right in range(left + 2, len(nodes)):
                source = nodes[left]
                target = nodes[right]
                relation_type = "indirect_pathway_connection"
                modality = "unknown"
                key = (source, target, modality, relation_type)
                if key not in seen:
                    seen.add(key)
                    decomposed.append(
                        {
                            "source_major_region_id": source,
                            "target_major_region_id": target,
                            "connection_modality": modality,
                            "relation_type": relation_type,
                            "directionality": "forward",
                            "supported_by_circuit": circuit_key,
                            "confidence": round(max(0.25, confidence - 0.1), 4),
                            "need_literature_verification": True,
                            "rationale_short": "Non-adjacent nodes inside same circuit path.",
                        }
                    )

        # Same-circuit membership.
        for left in range(len(nodes)):
            for right in range(left + 1, len(nodes)):
                source = nodes[left]
                target = nodes[right]
                relation_type = "same_circuit_member"
                modality = "unknown"
                key = (source, target, modality, relation_type)
                if key not in seen:
                    seen.add(key)
                    decomposed.append(
                        {
                            "source_major_region_id": source,
                            "target_major_region_id": target,
                            "connection_modality": modality,
                            "relation_type": relation_type,
                            "directionality": "bidirectional",
                            "supported_by_circuit": circuit_key,
                            "confidence": round(max(0.2, confidence - 0.2), 4),
                            "need_literature_verification": True,
                            "rationale_short": "Nodes co-occur in same circuit instance.",
                        }
                    )
    return decomposed


def _convert_instances_to_records(instances: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, item in enumerate(instances, start=1):
        nodes = [str(node) for node in item.get("nodes_present", []) if str(node)]
        if len(nodes) < 2:
            continue
        name = str(item.get("circuit_name") or f"major_circuit_{index}")
        semantics = str(item.get("loop_semantics") or "functional")
        circuit_kind = _semantics_to_kind(semantics)
        record = {
            "major_circuit_id": circuit_id(name, index),
            "circuit_code": circuit_id(name, index),
            "instance_key": str(item.get("instance_key") or ""),
            "en_name": name,
            "cn_name": "",
            "alias": [str(item.get("circuit_family") or "")],
            "description": f"Circuit candidate from family {item.get('circuit_family', '')}.",
            "circuit_kind": _normalize_kind(circuit_kind),
            "loop_type": _normalize_loop_type("inferred" if bool(item.get("compressed")) else "functional"),
            "cycle_verified": False,
            "confidence_circuit": round(_score(item.get("confidence"), default=0.5), 6),
            "validation_status_circuit": "unverified",
            "node_count": len(nodes),
            "connection_count": max(0, len(nodes) - 1),
            "data_source": "deepseek",
            "status": "active",
            "remark": f"family={item.get('circuit_family', '')};compressed={bool(item.get('compressed'))}",
            "node_ids": nodes,
            "circuit_family": str(item.get("circuit_family") or ""),
            "loop_semantics": semantics,
            "missing_key_nodes": item.get("missing_key_nodes", []),
            "compressed": bool(item.get("compressed")),
            "recommended_search_queries": item.get("recommended_search_queries", []),
            "decomposed_relations": [],
            "run_id": run_id,
        }
        records.append(record)
    return records


def _attach_decomposed_relations(
    records: list[dict[str, Any]],
    decomposed: list[dict[str, Any]],
) -> None:
    by_key: dict[str, list[dict[str, Any]]] = {}
    for relation in decomposed:
        instance_key = str(relation.get("supported_by_circuit") or "")
        if not instance_key:
            continue
        by_key.setdefault(instance_key, []).append(relation)
    for item in records:
        instance_key = str(item.get("instance_key") or "")
        item["decomposed_relations"] = by_key.get(instance_key, [])


def run_extract_circuits(
    input_path: str | Path,
    output_path: str | Path,
    config_path: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    config = load_optional_config(config_path)
    resolved_run_id = resolve_run_id(run_id)
    regions = read_jsonl(input_path)
    if not regions:
        raise ValueError("major regions input is empty")

    families = _load_family_templates(config)
    if not families:
        raise ValueError("No circuit families found in config.")
    families_by_id = {str(item.get("circuit_family") or ""): item for item in families}
    catalog, _ = _build_region_catalog(regions)
    region_count = len(catalog)

    pipeline_cfg = config.get("pipeline", {})
    target_multiplier = float(pipeline_cfg.get("major_circuit_target_multiplier", 1.8))
    explicit_target = int(pipeline_cfg.get("major_circuit_target_count", 0))
    target_count = explicit_target if explicit_target > 0 else int(round(max(10.0, region_count * target_multiplier)))
    per_seed_cap = int(pipeline_cfg.get("major_circuit_seed_instance_cap", 4) or 4)
    hard_cap = int(pipeline_cfg.get("major_circuit_hard_cap", 2000) or 2000)
    target_count = max(region_count, target_count)
    target_count = max(10, min(hard_cap, target_count))

    heuristic_recall = _heuristic_family_recall(catalog=catalog, families=families)
    llm_recall: list[dict[str, Any]] = []
    deepseek_calls = 0
    use_deepseek = bool(config.get("llm", {}).get("use_deepseek", True))
    if use_deepseek:
        llm_recall = _deepseek_family_recall(catalog=catalog, families=families, target_count=len(families))
        deepseek_calls += 1
    recalls = _merge_recall(heuristic_recall, llm_recall)
    if not recalls:
        raise ValueError("No circuit family recalled from region catalog.")

    seed_region_ids = [str(item.get("major_region_id") or "") for item in catalog if str(item.get("major_region_id") or "")]
    instances, traversal_rows = _build_instances_by_seed_traversal(
        seed_region_ids=seed_region_ids,
        recalls=recalls,
        families_by_id=families_by_id,
        target_count=target_count,
        per_seed_cap=per_seed_cap,
        hard_cap=hard_cap,
    )
    if not instances:
        raise ValueError("No circuit instances built from recalled families.")

    decomposed = _decompose_connections(instances)
    records = _convert_instances_to_records(instances=instances, run_id=resolved_run_id)
    _attach_decomposed_relations(records=records, decomposed=decomposed)

    output = Path(output_path)
    output_count = write_jsonl(output, records)
    write_json(output.with_name(output.stem + ".family_recall.json"), recalls)
    write_jsonl(output.with_name(output.stem + ".instance_build.jsonl"), instances)
    write_jsonl(output.with_name(output.stem + ".connection_decompose.jsonl"), decomposed)
    write_json(output.with_name(output.stem + ".seed_traversal_report.json"), traversal_rows)

    covered_regions: set[str] = set()
    for item in records:
        for node in item.get("node_ids", []):
            covered_regions.add(str(node))
    coverage_ratio = (len(covered_regions) / region_count) if region_count else 0.0
    uncovered_regions = sorted(
        [row.get("seed_region_id", "") for row in traversal_rows if int(row.get("built_instances", 0) or 0) == 0]
    )
    uncovered_payload = {
        "run_id": resolved_run_id,
        "region_count": region_count,
        "uncovered_region_count": len(uncovered_regions),
        "uncovered_regions": uncovered_regions,
    }
    write_json(output.with_name(output.stem + ".uncovered_regions.json"), uncovered_payload)
    attempted_region_count = len(seed_region_ids)
    matched_region_count = len([row for row in traversal_rows if int(row.get("built_instances", 0) or 0) > 0])

    report = {
        "stage": "extract_major_circuits",
        "run_id": resolved_run_id,
        "input_records": len(regions),
        "target_records": target_count,
        "family_recall_records": len(recalls),
        "instance_records": len(instances),
        "decomposed_relation_records": len(decomposed),
        "output_records": output_count,
        "covered_regions": len(covered_regions),
        "region_count": region_count,
        "coverage_ratio": round(coverage_ratio, 6),
        "seed_region_count": len(seed_region_ids),
        "attempted_region_count": attempted_region_count,
        "matched_region_count": matched_region_count,
        "uncovered_region_count": len(uncovered_regions),
        "uncovered_regions": uncovered_regions,
        "deepseek_calls": deepseek_calls,
        "output_path": str(output),
        "family_recall_path": str(output.with_name(output.stem + ".family_recall.json")),
        "instance_build_path": str(output.with_name(output.stem + ".instance_build.jsonl")),
        "connection_decompose_path": str(output.with_name(output.stem + ".connection_decompose.jsonl")),
        "seed_traversal_path": str(output.with_name(output.stem + ".seed_traversal_report.json")),
        "uncovered_regions_path": str(output.with_name(output.stem + ".uncovered_regions.json")),
    }
    write_json(output.with_suffix(".report.json"), report)
    return report


def main() -> None:
    parser = build_common_parser("Extract major circuits with family recall -> instance build -> connection decompose.")
    args = parser.parse_args()
    report = run_extract_circuits(
        input_path=args.input,
        output_path=args.output,
        config_path=args.config,
        run_id=args.run_id,
    )
    print(f"extract_major_circuits done: {report['output_records']}")


if __name__ == "__main__":
    main()
