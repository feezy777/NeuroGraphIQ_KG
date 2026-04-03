from __future__ import annotations

import hashlib
import re
from typing import Any

ALLOWED_LATERALITY = {"left", "right", "midline", "bilateral"}
ALLOWED_MODALITY = {"structural", "functional", "effective", "unknown"}

_LATERALITY_MAP = {
    "l": "left",
    "left": "left",
    "r": "right",
    "right": "right",
    "midline": "midline",
    "mid": "midline",
    "bilateral": "bilateral",
    "bi": "bilateral",
    "both": "bilateral",
}


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_alias(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items: list[str]
    if isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        text = str(value)
        if ";" in text:
            raw_items = text.split(";")
        elif "," in text:
            raw_items = text.split(",")
        else:
            raw_items = [text]

    seen: set[str] = set()
    result: list[str] = []
    for item in raw_items:
        cleaned = item.strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(cleaned)
    return result


def normalize_region_code(value: Any) -> str | None:
    text = normalize_text(value)
    if text is None:
        return None
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.upper()


def normalize_laterality(value: Any) -> str | None:
    text = normalize_text(value)
    if text is None:
        return None
    return _LATERALITY_MAP.get(text.lower())


def normalize_connection_modality(value: Any) -> str:
    text = normalize_text(value)
    if text is None:
        return "unknown"
    lowered = text.lower()
    if lowered in ALLOWED_MODALITY:
        return lowered
    return "unknown"


def _hash_suffix(parts: list[str]) -> str:
    joined = "|".join(parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:10]


def normalize_major_region_record(raw: dict[str, Any]) -> dict[str, Any]:
    region_code = normalize_region_code(raw.get("region_code"))
    return {
        "region_code": region_code,
        "en_name": normalize_text(raw.get("en_name")),
        "cn_name": normalize_text(raw.get("cn_name")),
        "alias": normalize_alias(raw.get("alias")),
        "description": normalize_text(raw.get("description")),
        "laterality": normalize_laterality(raw.get("laterality")),
        "region_category": normalize_text(raw.get("region_category")),
        "ontology_source": normalize_text(raw.get("ontology_source")),
        "data_source": normalize_text(raw.get("data_source")),
        "status": normalize_text(raw.get("status")),
        "remark": normalize_text(raw.get("remark")),
        "dedupe_key": region_code,
    }


def normalize_evidence_record(raw: dict[str, Any], fallback_source: str) -> dict[str, Any]:
    evidence_text = normalize_text(raw.get("evidence_text"))
    pmid = normalize_text(raw.get("pmid"))
    doi = normalize_text(raw.get("doi"))
    code = normalize_region_code(raw.get("evidence_code"))
    if code is None:
        source_bits = [
            pmid or "",
            doi or "",
            evidence_text or "",
            normalize_text(raw.get("source_title")) or "",
        ]
        code = f"EVID_{_hash_suffix(source_bits)}"

    year = raw.get("publication_year")
    pub_year: int | None = None
    if year is not None and str(year).strip():
        try:
            pub_year = int(year)
        except (TypeError, ValueError):
            pub_year = None

    return {
        "evidence_code": code,
        "en_name": normalize_text(raw.get("en_name")) or code,
        "cn_name": normalize_text(raw.get("cn_name")),
        "alias": normalize_alias(raw.get("alias")),
        "description": normalize_text(raw.get("description")),
        "evidence_text": evidence_text,
        "source_title": normalize_text(raw.get("source_title")),
        "pmid": pmid,
        "doi": doi,
        "section": normalize_text(raw.get("section")),
        "publication_year": pub_year,
        "journal": normalize_text(raw.get("journal")),
        "evidence_type": (normalize_text(raw.get("evidence_type")) or "paper").lower(),
        "data_source": normalize_text(raw.get("data_source")) or fallback_source,
        "status": normalize_text(raw.get("status")) or "active",
        "remark": normalize_text(raw.get("remark")),
    }


def normalize_major_connection_record(raw: dict[str, Any]) -> dict[str, Any]:
    source = normalize_region_code(raw.get("source_region_code"))
    target = normalize_region_code(raw.get("target_region_code"))
    modality = normalize_connection_modality(raw.get("connection_modality"))
    code = normalize_region_code(raw.get("connection_code"))
    if code is None and source and target:
        code = f"MC_{source}_{target}_{modality.upper()}"

    confidence = raw.get("confidence")
    score: float | None = None
    if confidence is not None and str(confidence).strip():
        try:
            score = float(confidence)
        except (TypeError, ValueError):
            score = None

    data_source = normalize_text(raw.get("data_source")) or "manual_import"
    evidence_raw = raw.get("evidence") if isinstance(raw.get("evidence"), list) else []
    evidence = [normalize_evidence_record(item, data_source) for item in evidence_raw if isinstance(item, dict)]

    dedupe_key = f"{source}->{target}:{modality}" if source and target else None
    return {
        "connection_code": code,
        "en_name": normalize_text(raw.get("en_name")) or code,
        "cn_name": normalize_text(raw.get("cn_name")),
        "alias": normalize_alias(raw.get("alias")),
        "description": normalize_text(raw.get("description")),
        "connection_modality": modality,
        "source_region_code": source,
        "target_region_code": target,
        "confidence": score,
        "validation_status": normalize_text(raw.get("validation_status")),
        "direction_label": normalize_text(raw.get("direction_label")),
        "extraction_method": normalize_text(raw.get("extraction_method")),
        "data_source": data_source,
        "status": normalize_text(raw.get("status")),
        "remark": normalize_text(raw.get("remark")),
        "evidence": evidence,
        "dedupe_key": dedupe_key,
    }
