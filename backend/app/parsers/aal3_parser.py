"""AAL3 (Automated Anatomical Labeling 3) parser.

Phase-1: primary input is NIfTI + XML pair (XML for labels, names, hemisphere, spatial attrs).
"""

import logging
import re
from pathlib import Path
from typing import Any

from app.parsers.aal3_xml import parse_aal3_xml
from app.parsers.base_parser import BaseParser, ParseResult
from app.utils.hash_utils import sha256_file

_HEMI_PATTERN = re.compile(r"_(L|R|Bi)$", re.IGNORECASE)
PARSER_VERSION = "1.1.0"
logger = logging.getLogger(__name__)


class AAL3Parser(BaseParser):
    PARSER_NAME = "aal3_parser"
    RESOURCE_TYPE = "aal3"

    def parse_pair(self, nii_path: str, xml_path: str) -> ParseResult:
        """Parse AAL3 atlas from NIfTI (registration) + XML (labels & spatial metadata)."""
        nii = Path(nii_path).resolve()
        xml = Path(xml_path).resolve()
        result = ParseResult()

        if not nii.is_file():
            raise FileNotFoundError(f"NIfTI not found: {nii}")
        if not xml.is_file():
            raise FileNotFoundError(f"XML not found: {xml}")

        self._log_step("init", f"Starting AAL3 parse_pair: {nii.name} + {xml.name}")
        version = self._detect_version(nii)

        result.resource_info = {
            "resource_name": "AAL3",
            "resource_type": "aal3",
            "version": version,
            "source_url": "https://www.gin.cnrs.fr/en/tools/aal/",
            "granularity": "macro",
            "data_type": "atlas",
            "parser_version": PARSER_VERSION,
        }

        result.file_records = [
            self._file_record(nii, version, primary=True),
            self._file_record(xml, version, primary=False),
        ]

        try:
            raw_regions = parse_aal3_xml(xml)
            self._log_step("parse_xml", f"Parsed {len(raw_regions)} regions from XML")
        except Exception as exc:
            result.quality_report.append(
                self._qissue("xml_parse_failed", "error", str(exc), affected_field="xml_path")
            )
            raw_regions = []

        if not raw_regions:
            label_file = self._find_label_file(nii)
            if label_file:
                self._log_step("fallback_txt", f"XML empty/failed; using label file {label_file.name}")
                result.quality_report.append(
                    self._qissue(
                        "xml_fallback_txt",
                        "warning",
                        f"Used {label_file.name} because XML produced no regions",
                        affected_field="xml_path",
                    )
                )
                result.region_records, result.term_records = self._parse_label_file(label_file)
            else:
                result.quality_report.append(
                    self._qissue(
                        "no_regions",
                        "error",
                        "No regions from XML and no .txt/.csv label file found",
                        affected_field="xml_path",
                    )
                )
        else:
            result.region_records, result.term_records = self._regions_to_records(raw_regions)

        result.mapping_candidates = self._build_mapping_candidates(result.region_records)
        self._validate(result)
        self._log_step("done", f"AAL3 parse_pair complete. {result.summary()}")
        return self._finalize(result)

    def _parse_xml_only(self, xml_path: Path) -> ParseResult:
        """Parse label/metadata from AAL3 XML when only the XML is uploaded."""
        result = ParseResult()
        self._log_step("init", f"Starting AAL3 XML-only parse: {xml_path.name}")
        version = self._detect_version(xml_path)
        result.resource_info = {
            "resource_name": "AAL3",
            "resource_type": "aal3",
            "version": version,
            "source_url": "https://www.gin.cnrs.fr/en/tools/aal/",
            "granularity": "macro",
            "data_type": "atlas",
            "parser_version": PARSER_VERSION,
        }
        result.file_records = [self._file_record(xml_path, version, primary=True)]

        try:
            raw_regions = parse_aal3_xml(xml_path)
            self._log_step("parse_xml", f"Parsed {len(raw_regions)} regions from XML")
            sample = raw_regions[:2]
            logger.info(
                "[IMPORT][AAL3] labels_extracted file=%s count=%s sample=%s",
                xml_path.name,
                len(raw_regions),
                [(r.get("label_index"), r.get("original_name")) for r in sample],
            )
        except Exception as exc:
            result.quality_report.append(
                self._qissue("xml_parse_failed", "error", str(exc), affected_field="xml_path")
            )
            raw_regions = []

        if raw_regions:
            result.region_records, result.term_records = self._regions_to_records(raw_regions)
            logger.info(
                "[IMPORT][AAL3] brain_regions_built count=%s",
                len(result.region_records),
            )
        else:
            result.quality_report.append(
                self._qissue(
                    "no_regions",
                    "error",
                    f"No regions parsed from XML: {xml_path.name}",
                    affected_field="xml_path",
                )
            )

        result.mapping_candidates = self._build_mapping_candidates(result.region_records)
        self._validate(result)
        self._log_step("done", f"AAL3 XML-only complete. {result.summary()}")
        return self._finalize(result)

    def parse(self, file_path: str) -> ParseResult:
        """Legacy entry: if sibling XML exists, use parse_pair; else label-file-only path."""
        path = Path(file_path).resolve()

        if path.suffix.lower() == ".xml":
            return self._parse_xml_only(path)

        xml_candidate = path.with_suffix(".xml")
        if path.suffix.lower() in (".nii",) or path.name.endswith(".nii.gz"):
            if xml_candidate.is_file():
                return self.parse_pair(str(path), str(xml_candidate))
            stem_xml = path.parent / f"{path.stem.split('.')[0]}.xml"
            if stem_xml.is_file():
                return self.parse_pair(str(path), str(stem_xml))

        result = ParseResult()
        self._log_step("init", f"Starting AAL3 parse (legacy): {path.name}")
        version = self._detect_version(path)
        result.resource_info = {
            "resource_name": "AAL3",
            "resource_type": "aal3",
            "version": version,
            "source_url": "https://www.gin.cnrs.fr/en/tools/aal/",
            "granularity": "macro",
            "data_type": "atlas",
            "parser_version": PARSER_VERSION,
        }
        result.file_records = [self._file_record(path, version, primary=True)]

        label_file = self._find_label_file(path)
        if label_file:
            result.region_records, result.term_records = self._parse_label_file(label_file)
        elif path.suffix in (".txt", ".csv"):
            result.region_records, result.term_records = self._parse_label_file(path)
        else:
            result.quality_report.append(
                self._qissue(
                    "missing_label_file",
                    "warning",
                    f"No XML or label file for {path.name}",
                    affected_field="file_path",
                )
            )

        result.mapping_candidates = self._build_mapping_candidates(result.region_records)
        self._validate(result)
        return self._finalize(result)

    def _file_record(self, path: Path, version: str, *, primary: bool) -> dict[str, Any]:
        return {
            "file_name": path.name,
            "file_path": str(path),
            "file_type": path.suffix.lstrip(".") or "nii",
            "source_code": "AAL3",
            "source_version": version,
            "sha256": sha256_file(path),
            "file_size_bytes": path.stat().st_size,
            "extra_attrs": {"primary_atlas": primary},
        }

    def _regions_to_records(self, raw: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
        regions: list[dict] = []
        terms: list[dict] = []
        for r in raw:
            region = {**r, "task_id": self.task_id}
            regions.append(region)
            abbr = region["abbr"]
            full_name = region.get("full_name") or abbr
            terms.append({
                "task_id": self.task_id,
                "term": abbr,
                "definition": full_name,
                "synonyms": [full_name] if full_name != abbr else [],
                "ontology_source": "AAL3",
                "ontology_id": region.get("source_id"),
            })
        return regions, terms

    def _detect_version(self, path: Path) -> str:
        name_lower = path.stem.lower()
        if "v1_1" in name_lower or "v1.1" in name_lower:
            return "AAL3v1_1"
        return "AAL3v1"

    def _find_label_file(self, path: Path) -> Path | None:
        for ext in (".txt", ".csv"):
            candidate = path.with_suffix(ext)
            if candidate.exists():
                return candidate
            candidate2 = path.parent / (path.stem.split(".")[0] + ext)
            if candidate2.exists():
                return candidate2
        return None

    def _parse_label_file(self, path: Path) -> tuple[list[dict], list[dict]]:
        regions: list[dict] = []
        terms: list[dict] = []

        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = re.split(r"\s+", line, maxsplit=2)
                if len(parts) < 2:
                    continue

                idx_str, abbr = parts[0], parts[1]
                full_name = parts[2].strip() if len(parts) > 2 else abbr
                if full_name.isdigit():
                    full_name = abbr

                try:
                    label_index = int(idx_str)
                except ValueError:
                    continue

                hemi = self._extract_hemisphere(abbr)
                region: dict[str, Any] = {
                    "task_id": self.task_id,
                    "original_name": abbr,
                    "abbr": abbr,
                    "full_name": full_name,
                    "hemisphere": hemi,
                    "parent_region": None,
                    "granularity": "macro",
                    "source_id": str(label_index),
                    "label_index": label_index,
                    "extra_attrs": {"aal3_full_name": full_name, "source": "txt_fallback"},
                }
                regions.append(region)
                terms.append({
                    "task_id": self.task_id,
                    "term": abbr,
                    "definition": full_name,
                    "synonyms": [full_name] if full_name != abbr else [],
                    "ontology_source": "AAL3",
                })

        return regions, terms

    def _extract_hemisphere(self, abbr: str) -> str | None:
        m = _HEMI_PATTERN.search(abbr)
        if m:
            suffix = m.group(1).upper()
            return {"L": "L", "R": "R", "BI": "bilateral"}.get(suffix)
        return None

    def _build_mapping_candidates(self, regions: list[dict]) -> list[dict]:
        candidates = []
        seen: dict[str, str] = {}

        for r in regions:
            base = _HEMI_PATTERN.sub("", r["abbr"])
            if base not in seen:
                seen[base] = r["abbr"]
            else:
                candidates.append({
                    "task_id": self.task_id,
                    "source_name": r["abbr"],
                    "source_atlas": "AAL3",
                    "target_name": seen[base],
                    "target_atlas": "AAL3",
                    "mapping_type": "contralateral_pair",
                    "confidence": 0.95,
                })
        return candidates

    def _validate(self, result: ParseResult) -> None:
        seen_names: set[str] = set()
        for r in result.region_records:
            if not r.get("original_name", "").strip():
                result.quality_report.append(
                    self._qissue("empty_name", "error", "Region with empty name detected", affected_field="original_name")
                )
            if r["original_name"] in seen_names:
                result.quality_report.append(
                    self._qissue("duplicate_name", "warning", f"Duplicate region name: {r['original_name']}", affected_field="original_name")
                )
            seen_names.add(r["original_name"])
