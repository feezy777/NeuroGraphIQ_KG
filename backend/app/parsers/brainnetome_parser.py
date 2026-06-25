"""Brainnetome Atlas parser.

Supports:
  - BNA_subregions.xlsx  (official region table from http://atlas.brainnetome.org)
  - BNA_matrix_*.csv     (connectivity matrices)

Output:
  - region_records      ✓  (246 sub-regions)
  - connection_records  ✓  (from connectivity matrix)
  - mapping_candidates  ✓  (to AAL / Brodmann)
"""

import csv
import os
from pathlib import Path
from typing import Any

from app.parsers.base_parser import BaseParser, ParseResult

try:
    import openpyxl
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False


class BrainnetomeParser(BaseParser):
    PARSER_NAME = "brainnetome_parser"
    RESOURCE_TYPE = "brainnetome"

    def parse(self, file_path: str) -> ParseResult:
        result = ParseResult()
        path = Path(file_path)
        self._log_step("init", f"Starting Brainnetome parse: {path.name}")

        result.resource_info = {
            "resource_name": "Brainnetome Atlas",
            "resource_type": "brainnetome",
            "version": "BNA246",
            "source_url": "http://atlas.brainnetome.org",
            "granularity": "meso",
            "data_type": "atlas",
        }

        result.file_records = [{
            "file_name": path.name,
            "file_path": str(path),
            "file_type": path.suffix.lstrip("."),
            "source_code": "BNA",
            "source_version": "BNA246",
        }]

        ext = path.suffix.lower()
        if ext in (".xlsx", ".xls"):
            result.region_records = self._parse_xlsx(path, result)
        elif ext == ".csv":
            result.region_records = self._parse_csv_regions(path, result)
        else:
            result.quality_report.append(
                self._qissue("unsupported_format", "error", f"Unsupported file type: {ext}. Expecting .xlsx or .csv")
            )

        matrix_file = self._find_matrix_file(path)
        if matrix_file:
            self._log_step("parse_matrix", f"Parsing connectivity matrix: {matrix_file.name}")
            result.connection_records = self._parse_connectivity_matrix(matrix_file, result.region_records)

        result.mapping_candidates = self._build_mapping_candidates(result.region_records)
        self._validate(result)
        self._log_step("done", f"Brainnetome parse complete. {result.summary()}")
        return self._finalize(result)

    def _parse_xlsx(self, path: Path, result: ParseResult) -> list[dict]:
        if not _HAS_OPENPYXL:
            result.quality_report.append(
                self._qissue("missing_dependency", "error", "openpyxl is required to parse .xlsx files")
            )
            return []

        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        header = [str(c).strip().lower() if c else "" for c in rows[0]]
        regions: list[dict] = []

        for row in rows[1:]:
            if not any(row):
                continue
            record = dict(zip(header, row))

            # Normalize expected columns
            name = str(record.get("label name", "") or record.get("region", "") or "").strip()
            abbr = str(record.get("abbreviation", "") or record.get("abbr", "") or "").strip()
            hemi = str(record.get("hemisphere", "") or "").strip()
            lobe = str(record.get("lobe", "") or "").strip()
            brodmann = str(record.get("brodmann areas", "") or record.get("ba", "") or "").strip()
            idx = record.get("no.", "") or record.get("index", "")

            regions.append({
                "task_id": self.task_id,
                "original_name": name or abbr,
                "abbr": abbr,
                "full_name": name,
                "hemisphere": hemi or None,
                "parent_region": lobe or None,
                "granularity": "meso",
                "source_id": str(idx) if idx else None,
                "extra_attrs": {"brodmann_areas": brodmann} if brodmann else {},
            })

        self._log_step("parse_xlsx", f"Parsed {len(regions)} regions from xlsx")
        return regions

    def _parse_csv_regions(self, path: Path, result: ParseResult) -> list[dict]:
        regions: list[dict] = []
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            reader = csv.DictReader(fh)
            for i, row in enumerate(reader):
                name = row.get("label name", row.get("region", "")).strip()
                regions.append({
                    "task_id": self.task_id,
                    "original_name": name or f"Region_{i + 1}",
                    "abbr": row.get("abbreviation", row.get("abbr", "")).strip() or None,
                    "hemisphere": row.get("hemisphere", "").strip() or None,
                    "parent_region": row.get("lobe", "").strip() or None,
                    "granularity": "meso",
                    "source_id": row.get("no.", row.get("index", str(i + 1))).strip(),
                    "extra_attrs": {},
                })
        return regions

    def _find_matrix_file(self, path: Path) -> Path | None:
        for pattern in ["*matrix*.csv", "*connectivity*.csv", "*SC*.csv", "*FC*.csv"]:
            matches = list(path.parent.glob(pattern))
            if matches:
                return matches[0]
        return None

    def _parse_connectivity_matrix(self, path: Path, regions: list[dict]) -> list[dict]:
        connections: list[dict] = []
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                reader = csv.reader(fh)
                rows = list(reader)

            for i, row in enumerate(rows):
                for j, val in enumerate(row):
                    try:
                        strength = float(val)
                    except (ValueError, TypeError):
                        continue
                    if strength == 0 or i == j:
                        continue

                    from_name = regions[i]["original_name"] if i < len(regions) else f"Region_{i}"
                    to_name = regions[j]["original_name"] if j < len(regions) else f"Region_{j}"

                    connections.append({
                        "task_id": self.task_id,
                        "region_from": from_name,
                        "region_to": to_name,
                        "connection_type": "structural",
                        "strength": strength,
                        "directionality": "bidirectional",
                        "dataset_ref": "BNA246",
                    })
        except Exception as exc:
            self._log_step("parse_matrix", f"Warning: could not fully parse matrix: {exc}", "warning")

        self._log_step("parse_matrix", f"Extracted {len(connections)} connections")
        return connections

    def _build_mapping_candidates(self, regions: list[dict]) -> list[dict]:
        return [
            {
                "task_id": self.task_id,
                "source_name": r["original_name"],
                "source_atlas": "BNA246",
                "target_name": None,
                "target_atlas": "AAL3",
                "mapping_type": "broad",
                "confidence": 0.6,
            }
            for r in regions
        ]

    def _validate(self, result: ParseResult) -> None:
        for r in result.region_records:
            if not r.get("original_name", "").strip():
                result.quality_report.append(
                    self._qissue("empty_name", "error", "Empty region name", affected_field="original_name")
                )
