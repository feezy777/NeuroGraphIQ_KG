from __future__ import annotations

import hashlib
import re


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = _NON_ALNUM.sub("_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def semantic_id(prefix: str, *parts: str) -> str:
    normalized = [slugify(part).upper() for part in parts if part and part.strip()]
    if not normalized:
        normalized = ["UNKNOWN"]
    return f"{prefix}_{'_'.join(normalized)}"


def parse_laterality(en_name: str) -> str:
    lowered = en_name.strip().lower()
    if lowered.startswith("left "):
        return "left"
    if lowered.startswith("right "):
        return "right"
    if " bilateral " in f" {lowered} ":
        return "bilateral"
    if " midline " in f" {lowered} ":
        return "midline"
    return "midline"


def strip_laterality_prefix(en_name: str) -> str:
    lowered = en_name.strip()
    for prefix in ("left ", "right "):
        if lowered.lower().startswith(prefix):
            return lowered[len(prefix) :].strip()
    return lowered


def major_region_id(en_name: str, laterality: str) -> str:
    base = strip_laterality_prefix(en_name)
    return semantic_id("REG_MAJOR", base, laterality)


def major_region_code(en_name: str, laterality: str) -> str:
    base = strip_laterality_prefix(en_name)
    return semantic_id("REG_CODE_MAJOR", base, laterality)


def connection_id(
    source_major_region_id: str,
    target_major_region_id: str,
    modality: str,
    relation_type: str = "",
) -> str:
    src = source_major_region_id.replace("REG_MAJOR_", "")
    tgt = target_major_region_id.replace("REG_MAJOR_", "")
    if relation_type:
        return semantic_id("CONN_MAJOR", src, tgt, modality, relation_type)
    return semantic_id("CONN_MAJOR", src, tgt, modality)


def circuit_id(circuit_name: str, sequence: int) -> str:
    return semantic_id("CIR_MAJOR", circuit_name, str(sequence))


def evidence_id(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8].upper()
    return f"EVID_DS_{digest}"
