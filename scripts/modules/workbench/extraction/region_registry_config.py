"""加载 configs/workbench/brain_region_registry.yaml（可选扩展）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set

import yaml

_DEFAULT: Dict[str, Any] = {
    "version": "0",
    "blacklist_terms": [],
    "stopwords": [],
    "column_semantics": {},
    "whitelist_terms": [],
}


def load_registry_overlay(root_dir: str) -> Dict[str, Any]:
    p = Path(root_dir) / "configs" / "workbench" / "brain_region_registry.yaml"
    if not p.exists():
        return dict(_DEFAULT)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return dict(_DEFAULT)
    out = dict(_DEFAULT)
    out.update({k: data.get(k, _DEFAULT[k]) for k in _DEFAULT})
    if isinstance(data.get("column_semantics"), dict):
        out["column_semantics"] = {**(_DEFAULT.get("column_semantics") or {}), **data["column_semantics"]}
    return out


def overlay_sets(overlay: Dict[str, Any]) -> Dict[str, Set[str]]:
    bl = {str(x).strip().lower() for x in (overlay.get("blacklist_terms") or []) if str(x).strip()}
    sw = {str(x).strip().lower() for x in (overlay.get("stopwords") or []) if str(x).strip()}
    wl = {str(x).strip().lower() for x in (overlay.get("whitelist_terms") or []) if str(x).strip()}
    return {"blacklist": bl, "stopwords": sw, "whitelist": wl}


def column_role_for_header(header_cell: str, overlay: Dict[str, Any]) -> str:
    """返回列角色：brain_region_primary | source | target | circuit | remark | method | unknown"""
    h = (header_cell or "").strip().lower()
    sem = overlay.get("column_semantics") or {}
    best_role = "unknown"
    best_len = 0
    for role, pats in sem.items():
        if not isinstance(pats, list):
            continue
        for pat in pats:
            pl = str(pat).lower()
            if pl and pl in h and len(pl) > best_len:
                best_len = len(pl)
                if role in ("source_region",):
                    best_role = "source"
                elif role in ("target_region",):
                    best_role = "target"
                elif role in ("circuit_pathway",):
                    best_role = "circuit"
                elif role in ("remark_note",):
                    best_role = "remark"
                elif role in ("method_assay",):
                    best_role = "method"
                else:
                    best_role = role
    if best_role == "unknown":
        for pat in ("region", "脑区", "brain", "nucleus", "area"):
            if pat in h:
                return "brain_region_primary"
    return best_role
