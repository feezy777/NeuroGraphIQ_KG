"""Julich-Brain / siibra-python parser.

Supports:
  - siibra JSON export (atlas.parcellations export)
  - Julich-Brain cytoarchitectonic map CSV
  - siibra region tree JSON

Output:
  - region_records      ✓  (Julich-Brain cytoarchitectonic areas)
  - connection_records  partial  (if siibra connectivity data provided)
  - mapping_candidates  ✓
"""

import csv
import json
from pathlib import Path
from typing import Any

from app.parsers.base_parser import BaseParser, ParseResult


class SiibraParser(BaseParser):
    PARSER_NAME = "siibra_parser"
    RESOURCE_TYPE = "julich_brain"

    def parse(self, file_path: str) -> ParseResult:
        result = ParseResult()
        path = Path(file_path)
        self._log_step("init", f"Starting Julich-Brain/siibra parse: {path.name}")

        result.resource_info = {
            "resource_name": "Julich-Brain Cytoarchitectonic Atlas",
            "resource_type": "julich_brain",
            "version": "v3.0.3",
            "source_url": "https://julich-brain-atlas.de/",
            "granularity": "micro",
            "data_type": "atlas",
        }

        result.file_records = [{
            "file_name": path.name,
            "file_path": str(path),
            "file_type": path.suffix.lstrip("."),
            "source_code": "Julich-Brain",
            "source_version": "v3.0.3",
        }]

        ext = path.suffix.lower()
        if ext == ".json":
            result.region_records, result.connection_records = self._parse_siibra_json(path, result)
        elif ext == ".csv":
            result.region_records = self._parse_csv(path, result)
        else:
            result.quality_report.append(
                self._qissue("unsupported_format", "error", f"Unsupported file type: {ext}. Expecting .json or .csv")
            )

        result.mapping_candidates = self._build_mapping_candidates(result.region_records)
        self._validate(result)
        self._log_step("done", f"Julich-Brain parse complete. {result.summary()}")
        return self._finalize(result)

    def _parse_siibra_json(self, path: Path, result: ParseResult) -> tuple[list[dict], list[dict]]:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        regions: list[dict] = []
        connections: list[dict] = []

        # siibra region tree: list of region dicts with optional children
        region_list = data if isinstance(data, list) else data.get("regions", [])
        self._flatten_region_tree(region_list, regions, parent=None)

        # Optional connectivity block
        conn_data = data.get("connectivity", []) if isinstance(data, dict) else []
        for entry in conn_data:
            connections.append({
                "task_id": self.task_id,
                "region_from": entry.get("source", ""),
                "region_to": entry.get("target", ""),
                "connection_type": entry.get("type", "structural"),
                "strength": entry.get("strength"),
                "directionality": entry.get("direction", "bidirectional"),
                "evidence": entry.get("reference"),
                "dataset_ref": "Julich-Brain",
            })

        self._log_step("parse_json", f"Extracted {len(regions)} regions, {len(connections)} connections from siibra JSON")
        return regions, connections

    def _flatten_region_tree(
        self, nodes: list[dict], out: list[dict], parent: str | None, depth: int = 0
    ) -> None:
        for node in nodes:
            name = node.get("name", node.get("label", "")).strip()
            if not name:
                continue

            hemi = None
            name_lower = name.lower()
            if "left" in name_lower or " l " in name_lower or name_lower.endswith("-l"):
                hemi = "L"
            elif "right" in name_lower or " r " in name_lower or name_lower.endswith("-r"):
                hemi = "R"

            out.append({
                "task_id": self.task_id,
                "original_name": name,
                "abbr": node.get("abbreviation") or node.get("shortname"),
                "hemisphere": hemi,
                "parent_region": parent,
                "granularity": "micro" if depth > 1 else "meso",
                "source_id": str(node.get("id", "")) or None,
                "ontology_id": node.get("ontology_id") or node.get("ebrains_id"),
                "extra_attrs": {},
            })

            children = node.get("children", [])
            if children:
                self._flatten_region_tree(children, out, parent=name, depth=depth + 1)

    def _parse_csv(self, path: Path, result: ParseResult) -> list[dict]:
        regions: list[dict] = []
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                name = (row.get("name", "") or row.get("region", "")).strip()
                if not name:
                    continue
                regions.append({
                    "task_id": self.task_id,
                    "original_name": name,
                    "abbr": row.get("abbreviation", row.get("abbr", "")).strip() or None,
                    "hemisphere": row.get("hemisphere", "").strip() or None,
                    "parent_region": row.get("parent", row.get("lobe", "")).strip() or None,
                    "granularity": "micro",
                    "source_id": row.get("id", row.get("index", "")).strip() or None,
                    "ontology_id": row.get("ontology_id", "").strip() or None,
                    "extra_attrs": {},
                })
        self._log_step("parse_csv", f"Parsed {len(regions)} regions from CSV")
        return regions

    def _build_mapping_candidates(self, regions: list[dict]) -> list[dict]:
        return [
            {
                "task_id": self.task_id,
                "source_name": r["original_name"],
                "source_atlas": "Julich-Brain",
                "target_name": None,
                "target_atlas": "AAL3",
                "mapping_type": "related",
                "confidence": 0.5,
            }
            for r in regions
        ]

    def _validate(self, result: ParseResult) -> None:
        if not result.region_records:
            result.quality_report.append(
                self._qissue("no_regions", "error", "No regions extracted from Julich-Brain file")
            )
