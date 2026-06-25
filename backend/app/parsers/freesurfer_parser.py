"""FreeSurfer parcellation parser.

Supports:
  - aparc.annot label files (Desikan-Killiany, Destrieux)
  - FreeSurferColorLUT.txt  (full lookup table)
  - stats/*.stats files    (morphometric summary)

Output:
  - region_records  ✓  (surface parcellation labels)
"""

import re
from pathlib import Path
from typing import Any

from app.parsers.base_parser import BaseParser, ParseResult

# e.g. "1000  ctx-lh-bankssts  R  G  B  A  full name"
_LUT_PATTERN = re.compile(
    r"^\s*(\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)(?:\s+(.*))?$"
)

# e.g. "lh_bankssts_thickness 2.456 ..."
_STATS_ROW_PATTERN = re.compile(r"^(\S+)\s+([\d.]+)")


class FreeSurferParser(BaseParser):
    PARSER_NAME = "freesurfer_parser"
    RESOURCE_TYPE = "freesurfer"

    def parse(self, file_path: str) -> ParseResult:
        result = ParseResult()
        path = Path(file_path)
        self._log_step("init", f"Starting FreeSurfer parse: {path.name}")

        result.resource_info = {
            "resource_name": "FreeSurfer Parcellation",
            "resource_type": "freesurfer",
            "version": "unknown",
            "source_url": "https://surfer.nmr.mgh.harvard.edu/",
            "granularity": "meso",
            "data_type": "parcellation",
        }

        result.file_records = [{
            "file_name": path.name,
            "file_path": str(path),
            "file_type": path.suffix.lstrip("."),
            "source_code": "FreeSurfer",
            "source_version": "unknown",
        }]

        name_lower = path.name.lower()
        ext = path.suffix.lower()

        if "colorlut" in name_lower or "lut" in name_lower:
            result.region_records = self._parse_lut(path, result)
        elif ext == ".stats":
            result.region_records = self._parse_stats(path, result)
        elif ext in (".txt", ".csv"):
            result.region_records = self._parse_lut(path, result)
        else:
            result.quality_report.append(
                self._qissue("unsupported_format", "warning",
                             f"Attempting to parse {path.name} as FreeSurfer LUT")
            )
            result.region_records = self._parse_lut(path, result)

        result.mapping_candidates = self._build_mapping_candidates(result.region_records)
        self._validate(result)
        self._log_step("done", f"FreeSurfer parse complete. {result.summary()}")
        return self._finalize(result)

    def _parse_lut(self, path: Path, result: ParseResult) -> list[dict]:
        regions: list[dict] = []
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = _LUT_PATTERN.match(line)
                if not m:
                    continue

                label_index = int(m.group(1))
                name = m.group(2)
                long_name = m.group(7).strip() if m.group(7) else name

                hemi = None
                if name.startswith("lh-") or name.startswith("ctx-lh-"):
                    hemi = "L"
                elif name.startswith("rh-") or name.startswith("ctx-rh-"):
                    hemi = "R"

                regions.append({
                    "task_id": self.task_id,
                    "original_name": name,
                    "abbr": None,
                    "full_name": long_name,
                    "hemisphere": hemi,
                    "granularity": "meso",
                    "source_id": str(label_index),
                    "label_index": label_index,
                    "extra_attrs": {
                        "r": int(m.group(3)),
                        "g": int(m.group(4)),
                        "b": int(m.group(5)),
                    },
                })

        self._log_step("parse_lut", f"Parsed {len(regions)} entries from LUT")
        return regions

    def _parse_stats(self, path: Path, result: ParseResult) -> list[dict]:
        """Parse a FreeSurfer *.stats file (e.g. lh.aparc.stats)."""
        regions: list[dict] = []
        hemi: str | None = None

        if "lh." in path.name:
            hemi = "L"
        elif "rh." in path.name:
            hemi = "R"

        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()

        # Find data table (after the last comment block)
        data_start = 0
        for i, line in enumerate(lines):
            if not line.startswith("#"):
                data_start = i
                break

        # Read header
        col_names: list[str] = []
        for i in range(data_start - 1, -1, -1):
            if lines[i].startswith("# ColHeaders"):
                col_names = lines[i].replace("# ColHeaders", "").split()
                break

        for line in lines[data_start:]:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if not parts:
                continue

            name = parts[0]
            thickness = None
            if col_names and "ThickAvg" in col_names:
                idx = col_names.index("ThickAvg")
                try:
                    thickness = float(parts[idx])
                except (IndexError, ValueError):
                    pass

            regions.append({
                "task_id": self.task_id,
                "original_name": name,
                "abbr": name,
                "hemisphere": hemi,
                "granularity": "meso",
                "source_id": None,
                "extra_attrs": {"thickness_avg": thickness} if thickness else {},
            })

        self._log_step("parse_stats", f"Parsed {len(regions)} regions from .stats file")
        return regions

    def _build_mapping_candidates(self, regions: list[dict]) -> list[dict]:
        return [
            {
                "task_id": self.task_id,
                "source_name": r["original_name"],
                "source_atlas": "FreeSurfer",
                "target_name": None,
                "target_atlas": "AAL3",
                "mapping_type": "broad",
                "confidence": 0.5,
            }
            for r in regions
        ]

    def _validate(self, result: ParseResult) -> None:
        if not result.region_records:
            result.quality_report.append(
                self._qissue("no_regions", "warning", "No regions extracted from FreeSurfer file")
            )
