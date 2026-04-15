#!/usr/bin/env python3
"""
Offline OWL/RDF -> RuleSet JSON (artifacts-friendly).

Reads RDF/XML, Turtle, or N-Triples via rdflib and emits a compact ruleset.json.

Usage:
  python scripts/tools/convert_owl_to_ruleset.py --input path/to/ontology.ttl --output artifacts/ontology/ruleset.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/tools/convert_owl_to_ruleset.py` from repo root
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.modules.workbench.validation.owl_ruleset_convert import build_ruleset, load_graph_from_path, write_ruleset_json


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert OWL/RDF to NeuroGraphIQ ruleset JSON")
    ap.add_argument("--input", "-i", required=True, help="Path to .owl / .ttl / .rdf / .nt")
    ap.add_argument("--output", "-o", required=True, help="Output ruleset.json path")
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"Input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    g = load_graph_from_path(in_path)
    ruleset = build_ruleset(g, source_hint=in_path.name)
    out_path = Path(args.output)
    write_ruleset_json(out_path, ruleset)
    print(f"Wrote {out_path} ({len(ruleset['termMap'])} terms, {len(ruleset['parentRules'])} parentRules)")


if __name__ == "__main__":
    main()
