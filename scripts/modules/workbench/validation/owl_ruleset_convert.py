"""
OWL/RDF -> RuleSet JSON (shared by CLI tool and workbench upload).

Requires rdflib.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

try:
    from rdflib import Graph
    from rdflib.namespace import OWL, RDF, RDFS, SKOS
except ImportError as e:
    raise ImportError("owl_ruleset_convert requires rdflib. Install with: pip install rdflib") from e


def _local_name(uri: str) -> str:
    s = str(uri).rstrip("/#")
    if "#" in s:
        return s.rsplit("#", 1)[-1]
    return s.rsplit("/", 1)[-1]


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "term"


def _collect_labels(g: Graph, node) -> List[str]:
    out: Set[str] = set()
    for _, _, lit in g.triples((node, RDFS.label, None)):
        if hasattr(lit, "value"):
            out.add(str(lit.value).strip())
        else:
            out.add(str(lit).strip())
    for _, _, lit in g.triples((node, SKOS.altLabel, None)):
        if hasattr(lit, "value"):
            out.add(str(lit.value).strip())
        else:
            out.add(str(lit).strip())
    return sorted(out)


def load_graph_from_path(path: Path) -> Graph:
    g = Graph()
    g.parse(str(path))
    return g


def build_ruleset(g: Graph, source_hint: str) -> Dict[str, Any]:
    term_map: Dict[str, Any] = {}
    parent_rules: Dict[str, Dict[str, List[str]]] = {}
    synonym_map: Dict[str, str] = {}

    for cls in g.subjects(RDF.type, OWL.Class):
        ln = _local_name(cls)
        key = f"term:{_slug(ln)}"
        labels = _collect_labels(g, cls)
        if not labels:
            labels = [ln.replace("_", " ")]
        term_map[key] = {"canonical": labels[0], "labels": labels}

    for cls in g.subjects(RDF.type, RDFS.Class):
        if str(cls) in term_map:
            continue
        ln = _local_name(cls)
        key = f"term:{_slug(ln)}"
        labels = _collect_labels(g, cls)
        if not labels:
            labels = [ln.replace("_", " ")]
        term_map[key] = {"canonical": labels[0], "labels": labels}

    for child, _, parent in g.triples((None, RDFS.subClassOf, None)):
        if str(parent) == str(OWL.Thing):
            continue
        c_lab = _collect_labels(g, child)
        p_lab = _collect_labels(g, parent)
        c_key = (c_lab[0] if c_lab else _local_name(child)).lower()
        p_name = (p_lab[0] if p_lab else _local_name(parent)).lower()
        slot = parent_rules.setdefault(c_key, {"allowedParents": []})
        if p_name not in slot["allowedParents"]:
            slot["allowedParents"].append(p_name)

    for a, _, b in g.triples((None, OWL.sameAs, None)):
        la = _collect_labels(g, a)
        lb = _collect_labels(g, b)
        na = (la[0] if la else _local_name(a)).lower()
        nb = (lb[0] if lb else _local_name(b)).lower()
        synonym_map[na] = nb
        synonym_map[nb] = na

    return {
        "version": f"owl-import-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "source": source_hint,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "termMap": term_map,
        "parentRules": parent_rules,
        "classRules": {
            "region": {"allowed": ["brain_region", "structure"]},
            "circuit": {"allowedKinds": ["structural", "functional", "inferred", "unknown"]},
            "connection": {"allowedModalities": ["structural", "functional", "effective", "unknown"]},
        },
        "granularityRules": {"region": {}, "crossGranularityEdges": []},
        "relationRules": {"connection": []},
        "synonymMap": synonym_map,
    }


def write_ruleset_json(path: Path, ruleset: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ruleset, ensure_ascii=False, indent=2), encoding="utf-8")
