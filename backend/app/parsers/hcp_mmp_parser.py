"""HCP Multi-Modal Parcellation (HCP-MMP1.0) parser.

Supports:
  - Q1-Q6_RelatedValidation210.txt  (label file bundled with HCP MMP atlas)
  - HCPMMP1_on_MNI152_ICBM2009a_nlin.nii.gz  (NIfTI volume)
  - Glasser2016_Table1.csv  (supplementary table with area descriptions)

Output:
  - region_records  ✓  (360 cortical areas, 180 per hemisphere)
"""

import csv
import re
from pathlib import Path
from typing import Any

from app.parsers.base_parser import BaseParser, ParseResult

_HEMI_MAP = {"L": "L", "R": "R", "lh": "L", "rh": "R"}


class HCPMMPParser(BaseParser):
    PARSER_NAME = "hcp_mmp_parser"
    RESOURCE_TYPE = "hcp_mmp"

    def parse(self, file_path: str) -> ParseResult:
        result = ParseResult()
        path = Path(file_path)
        self._log_step("init", f"Starting HCP-MMP parse: {path.name}")

        result.resource_info = {
            "resource_name": "HCP Multi-Modal Parcellation 1.0",
            "resource_type": "hcp_mmp",
            "version": "MMP1.0",
            "source_url": "https://www.humanconnectome.org/study/hcp-young-adult",
            "granularity": "meso",
            "data_type": "parcellation",
        }

        result.file_records = [{
            "file_name": path.name,
            "file_path": str(path),
            "file_type": path.suffix.lstrip("."),
            "source_code": "HCP-MMP",
            "source_version": "MMP1.0",
        }]

        ext = path.suffix.lower()
        name_lower = path.name.lower()

        if "table" in name_lower or ext == ".csv":
            result.region_records = self._parse_glasser_table(path, result)
        elif ext == ".txt" or "label" in name_lower:
            result.region_records = self._parse_label_file(path, result)
        elif ext in (".nii", ".gz"):
            self._log_step("nifti_detected", "NIfTI detected — label file required for region names")
            result.quality_report.append(
                self._qissue("missing_label_file", "warning",
                             "Provide the accompanying .txt label file for full region extraction")
            )
        else:
            result.quality_report.append(
                self._qissue("unsupported_format", "error", f"Unsupported file type: {ext}")
            )

        result.mapping_candidates = self._build_mapping_candidates(result.region_records)
        self._validate(result)
        self._log_step("done", f"HCP-MMP parse complete. {result.summary()}")
        return self._finalize(result)

    def _parse_label_file(self, path: Path, result: ParseResult) -> list[dict]:
        """Parse the FSL/Freesurfer-style label text file."""
        regions: list[dict] = []
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = re.split(r"\s+", line, maxsplit=5)
                if len(parts) < 2:
                    continue

                idx_str, name = parts[0], parts[1]
                try:
                    label_index = int(idx_str)
                except ValueError:
                    continue

                hemi = self._infer_hemisphere(name)
                regions.append({
                    "task_id": self.task_id,
                    "original_name": name,
                    "abbr": name,
                    "hemisphere": hemi,
                    "granularity": "meso",
                    "source_id": str(label_index),
                    "label_index": label_index,
                    "extra_attrs": {},
                })

        self._log_step("parse_label", f"Parsed {len(regions)} regions from label file")
        return regions

    def _parse_glasser_table(self, path: Path, result: ParseResult) -> list[dict]:
        """Parse Glasser et al. 2016 supplementary table (CSV)."""
        regions: list[dict] = []
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                name = (row.get("Area Name", "") or row.get("region", "") or row.get("label", "")).strip()
                abbr = (row.get("Abbreviation", "") or row.get("abbr", "")).strip()
                hemi = (row.get("Hemisphere", "") or row.get("hemi", "")).strip()
                parent = (row.get("Lobe", "") or row.get("parent", "")).strip()
                idx = row.get("Index", row.get("index", "")).strip()

                if not name:
                    continue

                regions.append({
                    "task_id": self.task_id,
                    "original_name": abbr or name,
                    "abbr": abbr or None,
                    "full_name": name,
                    "hemisphere": _HEMI_MAP.get(hemi, hemi) or None,
                    "parent_region": parent or None,
                    "granularity": "meso",
                    "source_id": idx or None,
                    "extra_attrs": {"full_name_glasser": name},
                })

        self._log_step("parse_table", f"Parsed {len(regions)} regions from Glasser table")
        return regions

    def _infer_hemisphere(self, name: str) -> str | None:
        for prefix in ("L_", "R_", "lh_", "rh_"):
            if name.startswith(prefix):
                return _HEMI_MAP.get(prefix.rstrip("_"))
        for suffix in ("_L", "_R"):
            if name.endswith(suffix):
                return _HEMI_MAP.get(suffix.lstrip("_"))
        return None

    def _build_mapping_candidates(self, regions: list[dict]) -> list[dict]:
        return [
            {
                "task_id": self.task_id,
                "source_name": r["original_name"],
                "source_atlas": "HCP-MMP1.0",
                "target_name": None,
                "target_atlas": "AAL3",
                "mapping_type": "broad",
                "confidence": 0.55,
            }
            for r in regions
        ]

    def _validate(self, result: ParseResult) -> None:
        expected = 360
        actual = len(result.region_records)
        if actual > 0 and abs(actual - expected) > 20:
            result.quality_report.append(
                self._qissue("unexpected_region_count", "warning",
                             f"HCP-MMP expected ~{expected} regions, got {actual}")
            )
