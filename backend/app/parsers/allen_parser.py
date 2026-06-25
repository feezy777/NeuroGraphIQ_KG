"""Allen Brain Atlas parser.

Supports:
  - Allen Human Brain Atlas gene expression CSV (from api.brain-map.org)
  - Columns: donor_id, structure_id, structure_acronym, structure_name,
             gene_symbol, gene_id, z-score / expression_level

Output:
  - molecular_records  ✓  (gene expression per structure)
  - region_records     ✓  (brain structures as regions)
  - mapping_candidates ✓  (structure → AAL3 candidate)
"""

import csv
import json
from pathlib import Path
from typing import Any

from app.parsers.base_parser import BaseParser, ParseResult


class AllenParser(BaseParser):
    PARSER_NAME = "allen_parser"
    RESOURCE_TYPE = "allen"

    # Allen API JSON structure fields
    _PROBES_KEY = "probes"
    _SAMPLES_KEY = "samples"
    _EXPRESSION_KEY = "expression"

    def parse(self, file_path: str) -> ParseResult:
        result = ParseResult()
        path = Path(file_path)
        self._log_step("init", f"Starting Allen Brain Atlas parse: {path.name}")

        result.resource_info = {
            "resource_name": "Allen Human Brain Atlas",
            "resource_type": "allen",
            "version": "v1",
            "source_url": "https://human.brain-map.org/",
            "granularity": "molecular",
            "data_type": "gene_expression",
        }

        result.file_records = [{
            "file_name": path.name,
            "file_path": str(path),
            "file_type": path.suffix.lstrip("."),
            "source_code": "AHBA",
            "source_version": "v1",
        }]

        ext = path.suffix.lower()
        if ext == ".csv":
            result.molecular_records, result.region_records = self._parse_csv(path, result)
        elif ext == ".json":
            result.molecular_records, result.region_records = self._parse_json(path, result)
        else:
            result.quality_report.append(
                self._qissue("unsupported_format", "error", f"Unsupported file type: {ext}. Expecting .csv or .json")
            )

        structure_names = {r["original_name"] for r in result.region_records}
        result.mapping_candidates = [
            {
                "task_id": self.task_id,
                "source_name": name,
                "source_atlas": "AHBA",
                "target_name": None,
                "target_atlas": "AAL3",
                "mapping_type": "broad",
                "confidence": 0.5,
            }
            for name in structure_names
        ]

        self._validate(result)
        self._log_step("done", f"Allen parse complete. {result.summary()}")
        return self._finalize(result)

    def _parse_csv(self, path: Path, result: ParseResult) -> tuple[list[dict], list[dict]]:
        molecular: list[dict] = []
        region_map: dict[str, dict] = {}

        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                structure_id = row.get("structure_id", "").strip()
                structure_acronym = row.get("structure_acronym", "").strip()
                structure_name = row.get("structure_name", "").strip()
                gene_symbol = row.get("gene_symbol", "").strip()
                gene_id = row.get("gene_id", "").strip()
                donor_id = row.get("donor_id", "").strip()
                specimen_id = row.get("specimen_id", row.get("well_id", "")).strip()

                raw_expr = row.get("z-score", row.get("expression_level", row.get("value", "")))
                try:
                    expr_level = float(raw_expr)
                except (ValueError, TypeError):
                    expr_level = None

                if structure_name and structure_name not in region_map:
                    region_map[structure_name] = {
                        "task_id": self.task_id,
                        "original_name": structure_name,
                        "abbr": structure_acronym or None,
                        "granularity": "micro",
                        "source_id": structure_id or None,
                        "extra_attrs": {"allen_structure_id": structure_id},
                    }

                if gene_symbol:
                    molecular.append({
                        "task_id": self.task_id,
                        "gene_symbol": gene_symbol,
                        "gene_id": gene_id or None,
                        "expression_level": expr_level,
                        "expression_unit": "z-score",
                        "region_ref": structure_name or structure_acronym,
                        "structure_id": structure_id or None,
                        "dataset_ref": "AHBA",
                        "specimen_id": specimen_id or None,
                        "extra_attrs": {"donor_id": donor_id} if donor_id else {},
                    })

        self._log_step("parse_csv", f"Parsed {len(molecular)} molecular records, {len(region_map)} structures")
        return molecular, list(region_map.values())

    def _parse_json(self, path: Path, result: ParseResult) -> tuple[list[dict], list[dict]]:
        """Parse Allen API JSON download format (probes × samples expression matrix)."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        probes = data.get(self._PROBES_KEY, [])
        samples = data.get(self._SAMPLES_KEY, [])
        expression_matrix = data.get(self._EXPRESSION_KEY, [])

        region_map: dict[str, dict] = {}
        molecular: list[dict] = []

        for sample in samples:
            struct = sample.get("structure", {})
            name = struct.get("name", "")
            acronym = struct.get("acronym", "")
            struct_id = str(struct.get("id", ""))
            if name and name not in region_map:
                region_map[name] = {
                    "task_id": self.task_id,
                    "original_name": name,
                    "abbr": acronym or None,
                    "granularity": "micro",
                    "source_id": struct_id or None,
                    "extra_attrs": {"allen_structure_id": struct_id},
                }

        for p_idx, probe in enumerate(probes):
            gene_symbol = probe.get("gene_symbol", "")
            gene_id = str(probe.get("gene_id", ""))
            if p_idx < len(expression_matrix):
                for s_idx, expr_val in enumerate(expression_matrix[p_idx]):
                    if s_idx < len(samples):
                        struct_name = samples[s_idx].get("structure", {}).get("name", "")
                        molecular.append({
                            "task_id": self.task_id,
                            "gene_symbol": gene_symbol,
                            "gene_id": gene_id or None,
                            "expression_level": float(expr_val) if expr_val is not None else None,
                            "expression_unit": "normalized",
                            "region_ref": struct_name,
                            "structure_id": str(samples[s_idx].get("structure", {}).get("id", "")),
                            "dataset_ref": "AHBA",
                            "extra_attrs": {},
                        })

        self._log_step("parse_json", f"Parsed {len(molecular)} molecular records from JSON")
        return molecular, list(region_map.values())

    def _validate(self, result: ParseResult) -> None:
        if not result.molecular_records:
            result.quality_report.append(
                self._qissue("no_data", "warning", "No molecular records parsed from Allen file")
            )
        for m in result.molecular_records:
            if not m.get("gene_symbol", "").strip():
                result.quality_report.append(
                    self._qissue("empty_gene_symbol", "warning", "Molecular record missing gene_symbol", affected_field="gene_symbol")
                )
                break
