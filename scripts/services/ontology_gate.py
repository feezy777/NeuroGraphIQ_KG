from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import yaml

from scripts.utils.io_utils import write_json

RELATION_TYPES = {
    "direct_structural_connection",
    "indirect_pathway_connection",
    "same_circuit_member",
}

CORE_REQUIRED_CLASSES = {
    "Organism",
    "AnatomicalSystem",
    "Organ",
    "BrainDivision",
    "MajorBrainRegion",
    "MajorBrainRegionConnection",
    "MajorBrainRegionCircuit",
    "EvidenceEntity",
}

CORE_REQUIRED_PROPERTIES = {
    "has_source",
    "has_target",
    "has_node",
    "has_connection",
}


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _entity_tail(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "#" in text:
        return text.rsplit("#", 1)[1]
    if "/" in text:
        return text.rstrip("/").rsplit("/", 1)[1]
    return text


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(payload, dict):
        return payload
    return {}


def load_ontology_baseline(ontology_path: str | Path, ontology_config_dir: str | Path) -> dict[str, Any]:
    ontology_file = Path(ontology_path)
    config_dir = Path(ontology_config_dir)

    classes: set[str] = set()
    object_properties: set[str] = set()
    parse_errors: list[str] = []
    if ontology_file.exists():
        try:
            root = ET.parse(ontology_file).getroot()
            for elem in root.iter():
                name = _local_name(elem.tag)
                if name == "Class":
                    for attr_name, attr_val in elem.attrib.items():
                        attr_tail = _local_name(attr_name)
                        if attr_tail in {"about", "ID", "resource"}:
                            tail = _entity_tail(attr_val)
                            if tail:
                                classes.add(tail)
                if name == "ObjectProperty":
                    for attr_name, attr_val in elem.attrib.items():
                        attr_tail = _local_name(attr_name)
                        if attr_tail in {"about", "ID", "resource"}:
                            tail = _entity_tail(attr_val)
                            if tail:
                                object_properties.add(tail)
        except Exception as exc:
            parse_errors.append(f"ontology_parse_error:{exc}")
    else:
        parse_errors.append(f"ontology_missing:{ontology_file}")

    class_mapping = _read_yaml(config_dir / "class_mapping.yaml")
    property_mapping = _read_yaml(config_dir / "property_mapping.yaml")
    constraint_mapping = _read_yaml(config_dir / "constraint_mapping.yaml")

    enum_values: dict[str, set[str]] = {}
    checks = constraint_mapping.get("checks", {}) if isinstance(constraint_mapping, dict) else {}
    if isinstance(checks, dict):
        for key, item in checks.items():
            if isinstance(item, dict):
                values = item.get("values")
                if isinstance(values, list):
                    enum_values[key] = {str(v) for v in values}

    class_keys = set()
    class_entries = class_mapping.get("classes", {}) if isinstance(class_mapping, dict) else {}
    if isinstance(class_entries, dict):
        class_keys = {str(k) for k in class_entries.keys()}

    property_keys = set()
    property_entries = property_mapping.get("object_properties", {}) if isinstance(property_mapping, dict) else {}
    if isinstance(property_entries, dict):
        property_keys = {str(k) for k in property_entries.keys()}

    return {
        "ontology_path": str(ontology_file),
        "classes": sorted(classes),
        "object_properties": sorted(object_properties),
        "class_keys": sorted(class_keys),
        "property_keys": sorted(property_keys),
        "enum_values": {k: sorted(v) for k, v in enum_values.items()},
        "parse_errors": parse_errors,
    }


def _issue(code: str, severity: str, message: str, sample: Any = None) -> dict[str, Any]:
    item = {"code": code, "severity": severity, "message": message}
    if sample is not None:
        item["sample"] = sample
    return item


def _support_warnings(circuits: list[dict[str, Any]], connections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warns: list[dict[str, Any]] = []
    compressed_count = 0
    missing_node_count = 0
    for circuit in circuits:
        if bool(circuit.get("compressed")):
            compressed_count += 1
        if isinstance(circuit.get("missing_key_nodes"), list) and circuit.get("missing_key_nodes"):
            missing_node_count += 1

    if compressed_count:
        warns.append(
            _issue(
                "compressed_circuit_warning",
                "WARN",
                f"{compressed_count} circuits are marked compressed=true; keep as candidate until evidence backfill.",
            )
        )
    if missing_node_count:
        warns.append(
            _issue(
                "missing_key_nodes_warning",
                "WARN",
                f"{missing_node_count} circuits contain missing_key_nodes; should remain candidate-level.",
            )
        )

    evidence_need_count = 0
    low_conf_count = 0
    for conn in connections:
        if bool(conn.get("need_literature_verification")):
            evidence_need_count += 1
        confidence = conn.get("confidence")
        try:
            score = float(confidence) if confidence is not None else 0.0
        except Exception:
            score = 0.0
        if score < 0.5:
            low_conf_count += 1

    if evidence_need_count:
        warns.append(
            _issue(
                "evidence_insufficient_warning",
                "WARN",
                f"{evidence_need_count} connections request literature verification.",
            )
        )
    if low_conf_count:
        warns.append(
            _issue(
                "low_confidence_warning",
                "WARN",
                f"{low_conf_count} connections have confidence lower than 0.5.",
            )
        )
    return warns


def run_ontology_gate(
    regions: list[dict[str, Any]],
    circuits: list[dict[str, Any]],
    connections: list[dict[str, Any]],
    ontology_path: str | Path,
    ontology_config_dir: str | Path,
    output_path: str | Path,
    run_id: str,
) -> dict[str, Any]:
    baseline = load_ontology_baseline(ontology_path=ontology_path, ontology_config_dir=ontology_config_dir)
    blocks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []

    if baseline.get("parse_errors"):
        warns.append(
            _issue(
                "ontology_parse_warning",
                "WARN",
                "Ontology parsing has issues; YAML fallback is used for hard gate.",
                sample=baseline.get("parse_errors"),
            )
        )

    class_keys = set(baseline.get("class_keys", []))
    missing_class_mappings = sorted(CORE_REQUIRED_CLASSES - class_keys)
    if missing_class_mappings:
        blocks.append(
            _issue(
                "illegal_class_mapping",
                "BLOCK",
                "Required class mappings are missing.",
                sample=missing_class_mappings,
            )
        )

    property_keys = set(baseline.get("property_keys", []))
    missing_property_mappings = sorted(CORE_REQUIRED_PROPERTIES - property_keys)
    if missing_property_mappings:
        blocks.append(
            _issue(
                "illegal_relation_mapping",
                "BLOCK",
                "Required relation mappings are missing.",
                sample=missing_property_mappings,
            )
        )

    ontology_classes = set(baseline.get("classes", []))
    if ontology_classes:
        missing_in_ontology = sorted(CORE_REQUIRED_CLASSES - ontology_classes)
        if missing_in_ontology:
            blocks.append(
                _issue(
                    "class_not_in_ontology",
                    "BLOCK",
                    "Mapped classes are not present in ontology classes.",
                    sample=missing_in_ontology,
                )
            )

    connection_modality_values = set(baseline.get("enum_values", {}).get("connection_modality", []))
    if not connection_modality_values:
        connection_modality_values = {"structural", "functional", "effective", "unknown"}

    region_ids = {str(r.get("major_region_id") or "").strip() for r in regions if str(r.get("major_region_id") or "").strip()}
    relation_type_invalid: list[dict[str, Any]] = []
    modality_invalid: list[dict[str, Any]] = []
    fk_invalid: list[dict[str, Any]] = []

    for conn in connections:
        relation_type = str(conn.get("relation_type") or "").strip()
        if relation_type not in RELATION_TYPES:
            relation_type_invalid.append(
                {
                    "major_connection_id": conn.get("major_connection_id"),
                    "relation_type": relation_type,
                }
            )
        modality = str(conn.get("connection_modality") or "").strip()
        if modality not in connection_modality_values:
            modality_invalid.append(
                {
                    "major_connection_id": conn.get("major_connection_id"),
                    "connection_modality": modality,
                }
            )
        source = str(conn.get("source_major_region_id") or "").strip()
        target = str(conn.get("target_major_region_id") or "").strip()
        if source not in region_ids or target not in region_ids:
            fk_invalid.append(
                {
                    "major_connection_id": conn.get("major_connection_id"),
                    "source_major_region_id": source,
                    "target_major_region_id": target,
                }
            )

    if relation_type_invalid:
        blocks.append(
            _issue(
                "relation_type_illegal",
                "BLOCK",
                "Found illegal relation_type in major_connection records.",
                sample=relation_type_invalid[:10],
            )
        )
    if modality_invalid:
        blocks.append(
            _issue(
                "enum_illegal_connection_modality",
                "BLOCK",
                "Found illegal connection_modality values.",
                sample=modality_invalid[:10],
            )
        )
    if fk_invalid:
        blocks.append(
            _issue(
                "key_fk_unmappable",
                "BLOCK",
                "Found source/target major_region_id not mappable to validated major regions.",
                sample=fk_invalid[:10],
            )
        )

    warns.extend(_support_warnings(circuits=circuits, connections=connections))

    gate_decision = {
        "allow_preview": True,
        "allow_extract": True,
        "allow_load": len(blocks) == 0,
        "blocked_on_load": len(blocks) > 0,
        "block_reason": "; ".join(item["code"] for item in blocks[:6]) if blocks else "",
    }

    report = {
        "stage": "ontology_gate_major",
        "run_id": run_id,
        "ontology_path": str(ontology_path),
        "ontology_gate_summary": {
            "block_count": len(blocks),
            "warn_count": len(warns),
            "allow_load": gate_decision["allow_load"],
        },
        "core_block_issues": blocks,
        "extension_warn_issues": warns,
        "gate_decision": gate_decision,
        "coverage_counts": {
            "major_regions": len(regions),
            "major_circuits": len(circuits),
            "major_connections": len(connections),
        },
        "baseline": baseline,
    }
    write_json(output_path, report)
    return report


def relation_type_counts(connections: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in connections:
        key = str(item.get("relation_type") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def circuit_family_counts(circuits: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in circuits:
        key = str(item.get("circuit_family") or "unassigned")
        counts[key] = counts.get(key, 0) + 1
    return counts


def detect_relation_type(text: str) -> str:
    value = str(text or "").strip().lower()
    if value in RELATION_TYPES:
        return value
    compact = re.sub(r"[^a-z_]", "", value.replace("-", "_").replace(" ", "_"))
    aliases = {
        "direct": "direct_structural_connection",
        "direct_structural": "direct_structural_connection",
        "direct_structural_connection": "direct_structural_connection",
        "indirect": "indirect_pathway_connection",
        "indirect_pathway": "indirect_pathway_connection",
        "indirect_pathway_connection": "indirect_pathway_connection",
        "same_circuit": "same_circuit_member",
        "same_member": "same_circuit_member",
        "same_circuit_member": "same_circuit_member",
    }
    return aliases.get(compact, "")
