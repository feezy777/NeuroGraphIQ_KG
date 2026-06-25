"""Parse AAL3 / FSL-style atlas XML into normalized region dicts."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_LABEL_TAGS = frozenset({"label", "region", "roi", "parcel", "area"})
_HEMI_PATTERN = re.compile(r"_(L|R|Bi)$", re.IGNORECASE)


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1].lower()
    return tag.lower()


def _attr_float(attrs: dict[str, str], *keys: str) -> float | None:
    for k in keys:
        v = attrs.get(k) or attrs.get(k.upper()) or attrs.get(k.lower())
        if v is not None and str(v).strip() != "":
            try:
                return float(v)
            except ValueError:
                continue
    return None


def _child_text(elem: ET.Element, *local_names: str) -> str | None:
    want = {n.lower() for n in local_names}
    for child in elem:
        if _local_tag(child.tag) in want:
            t = (child.text or "").strip()
            if t:
                return t
    return None


def _extract_index(elem: ET.Element) -> int | None:
    attrs = elem.attrib
    for key in ("index", "id", "value", "label", "labelindex", "label_index"):
        raw = attrs.get(key) or attrs.get(key.upper())
        if raw is not None and str(raw).strip().isdigit():
            return int(str(raw).strip())
    idx_text = _child_text(elem, "index", "id", "value", "labelindex")
    if idx_text and idx_text.isdigit():
        return int(idx_text)
    return None


def _extract_name(elem: ET.Element) -> str:
    attrs = elem.attrib
    for key in ("name", "abbrev", "abbr", "labelname", "title"):
        v = attrs.get(key) or attrs.get(key.upper())
        if v and str(v).strip():
            return str(v).strip()
    for child_name in ("name", "abbrev", "abbr", "labelname", "title"):
        t = _child_text(elem, child_name)
        if t:
            return t
    text = (elem.text or "").strip()
    if text and not text.isdigit():
        return text
    tail = "".join(elem.itertext()).strip()
    if tail and not tail.isdigit():
        return tail.split("\n")[0].strip()
    return ""


def _extract_coords(elem: ET.Element) -> tuple[dict[str, float] | None, dict[str, Any] | None]:
    attrs = {k.lower(): v for k, v in elem.attrib.items()}
    x = _attr_float(attrs, "x", "xm", "centroid_x", "mni_x")
    y = _attr_float(attrs, "y", "ym", "centroid_y", "mni_y")
    z = _attr_float(attrs, "z", "zm", "centroid_z", "mni_z")
    if x is None:
        xt = _child_text(elem, "x", "xm", "mni_x")
        if xt:
            try:
                x = float(xt)
            except ValueError:
                pass
    if y is None:
        yt = _child_text(elem, "y", "ym", "mni_y")
        if yt:
            try:
                y = float(yt)
            except ValueError:
                pass
    if z is None:
        zt = _child_text(elem, "z", "zm", "mni_z")
        if zt:
            try:
                z = float(zt)
            except ValueError:
                pass

    coordinates = None
    if x is not None and y is not None and z is not None:
        coordinates = {"x": x, "y": y, "z": z}

    xmin = _attr_float(attrs, "xmin", "min_x")
    xmax = _attr_float(attrs, "xmax", "max_x")
    ymin = _attr_float(attrs, "ymin", "min_y")
    ymax = _attr_float(attrs, "ymax", "max_y")
    zmin = _attr_float(attrs, "zmin", "min_z")
    zmax = _attr_float(attrs, "zmax", "max_z")
    bounding = None
    if all(v is not None for v in (xmin, xmax, ymin, ymax, zmin, zmax)):
        bounding = {
            "min": {"x": xmin, "y": ymin, "z": zmin},
            "max": {"x": xmax, "y": ymax, "z": zmax},
        }
    return coordinates, bounding


def _hemisphere_from_abbr(abbr: str) -> str | None:
    m = _HEMI_PATTERN.search(abbr)
    if not m:
        return None
    suffix = m.group(1).upper()
    return {"L": "L", "R": "R", "BI": "bilateral"}.get(suffix)


def _iter_label_elements(root: ET.Element):
    for elem in root.iter():
        tag = _local_tag(elem.tag)
        if tag in _LABEL_TAGS:
            yield elem
        elif tag == "data":
            for child in elem:
                if _local_tag(child.tag) in _LABEL_TAGS or _extract_index(child) is not None:
                    yield child


def parse_aal3_xml(xml_path: str | Path) -> list[dict[str, Any]]:
    """Return raw region dicts from atlas XML (before task_id injection)."""
    path = Path(xml_path)
    tree = ET.parse(path)
    root = tree.getroot()

    records: list[dict[str, Any]] = []
    seen_indices: set[int] = set()

    for elem in _iter_label_elements(root):
        label_index = _extract_index(elem)
        if label_index is None:
            continue
        if label_index in seen_indices:
            continue
        seen_indices.add(label_index)

        name = _extract_name(elem)
        if not name:
            continue

        abbr = name
        full_name = name
        if " " in name and "_" not in name:
            abbr = name.replace(" ", "_")
        elif len(name) > 80:
            full_name = name
            parts = name.split(None, 1)
            abbr = parts[0] if parts else name

        coordinates_mni, bounding_box = _extract_coords(elem)
        extra: dict[str, Any] = {"xml_tag": elem.tag}
        for ak, av in elem.attrib.items():
            if ak.lower() not in ("index", "id", "x", "y", "z", "name"):
                extra[f"xml_{ak.lower()}"] = av

        records.append({
            "label_index": label_index,
            "original_name": abbr,
            "abbr": abbr,
            "full_name": full_name,
            "hemisphere": _hemisphere_from_abbr(abbr),
            "parent_region": None,
            "granularity": "macro",
            "source_id": str(label_index),
            "coordinates_mni": coordinates_mni,
            "bounding_box": bounding_box,
            "extra_attrs": extra,
        })

    records.sort(key=lambda r: r["label_index"])
    return records
