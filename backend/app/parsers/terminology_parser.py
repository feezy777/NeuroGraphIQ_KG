"""BrainInfo / InterLex / NeuroNames terminology parser.

Supports:
  - InterLex CSV export  (id, label, definition, synonyms, type, ontology)
  - BrainInfo JSON
  - Generic term TSV / CSV with (term, definition, synonyms) columns

Output:
  - term_records        ✓
  - mapping_candidates  ✓ (ontology cross-links)
"""

import csv
import json
import re
from pathlib import Path
from typing import Any

from app.parsers.base_parser import BaseParser, ParseResult


class TerminologyParser(BaseParser):
    PARSER_NAME = "terminology_parser"
    RESOURCE_TYPE = "interlex"

    def parse(self, file_path: str) -> ParseResult:
        result = ParseResult()
        path = Path(file_path)
        self._log_step("init", f"Starting terminology parse: {path.name}")

        source_name = self._detect_source(path)
        result.resource_info = {
            "resource_name": source_name,
            "resource_type": "interlex" if "interlex" in source_name.lower() else "braininfo",
            "version": "unknown",
            "source_url": self._source_url(source_name),
            "granularity": "term",
            "data_type": "ontology",
        }

        result.file_records = [{
            "file_name": path.name,
            "file_path": str(path),
            "file_type": path.suffix.lstrip("."),
            "source_code": source_name,
            "source_version": "unknown",
        }]

        ext = path.suffix.lower()
        if ext == ".json":
            result.term_records = self._parse_json(path, result)
        elif ext in (".csv", ".tsv", ".txt"):
            sep = "\t" if ext == ".tsv" else ","
            result.term_records = self._parse_csv(path, result, sep=sep)
        else:
            result.quality_report.append(
                self._qissue("unsupported_format", "error", f"Unsupported file type: {ext}")
            )

        result.mapping_candidates = self._build_mapping_candidates(result.term_records, source_name)
        self._validate(result)
        self._log_step("done", f"Terminology parse complete. {result.summary()}")
        return self._finalize(result)

    def _detect_source(self, path: Path) -> str:
        name_lower = path.name.lower()
        if "interlex" in name_lower:
            return "InterLex"
        if "braininfo" in name_lower:
            return "BrainInfo"
        if "neuronames" in name_lower:
            return "NeuroNames"
        return "TerminologySource"

    def _source_url(self, source: str) -> str:
        urls = {
            "InterLex": "https://scicrunch.org/scicrunch/interlex/dashboard",
            "BrainInfo": "https://braininfo.rprc.washington.edu/",
            "NeuroNames": "https://braininfo.rprc.washington.edu/",
        }
        return urls.get(source, "")

    def _parse_csv(self, path: Path, result: ParseResult, sep: str = ",") -> list[dict]:
        terms: list[dict] = []

        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            reader = csv.DictReader(fh, delimiter=sep)
            for row in reader:
                term = (
                    row.get("label", "") or row.get("term", "") or row.get("name", "")
                ).strip()

                if not term:
                    continue

                definition = (
                    row.get("definition", "") or row.get("desc", "") or row.get("description", "")
                ).strip() or None

                raw_synonyms = (
                    row.get("synonyms", "") or row.get("synonym", "") or row.get("aliases", "")
                ).strip()
                synonyms = [s.strip() for s in re.split(r"[|;,]", raw_synonyms) if s.strip()] if raw_synonyms else []

                ontology_id = (
                    row.get("id", "") or row.get("ontology_id", "") or row.get("ilx_id", "")
                ).strip() or None

                ontology_source = (
                    row.get("ontology", "") or row.get("source", "") or row.get("type", "")
                ).strip() or None

                parent_term = (
                    row.get("parent", "") or row.get("superclass", "") or row.get("broader", "")
                ).strip() or None

                source_url = (row.get("uri", "") or row.get("url", "")).strip() or None

                terms.append({
                    "task_id": self.task_id,
                    "term": term,
                    "definition": definition,
                    "synonyms": synonyms,
                    "ontology_id": ontology_id,
                    "ontology_source": ontology_source,
                    "parent_term": parent_term,
                    "source_url": source_url,
                    "extra_attrs": {},
                })

        self._log_step("parse_csv", f"Parsed {len(terms)} terms from CSV/TSV")
        return terms

    def _parse_json(self, path: Path, result: ParseResult) -> list[dict]:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        items = data if isinstance(data, list) else data.get("terms", data.get("results", []))
        terms: list[dict] = []

        for item in items:
            term = (item.get("label", "") or item.get("term", "") or item.get("name", "")).strip()
            if not term:
                continue

            raw_syn = item.get("synonyms", item.get("synonym", []))
            if isinstance(raw_syn, str):
                synonyms = [s.strip() for s in re.split(r"[|;,]", raw_syn) if s.strip()]
            else:
                synonyms = [str(s).strip() for s in raw_syn if s]

            terms.append({
                "task_id": self.task_id,
                "term": term,
                "definition": item.get("definition") or item.get("description"),
                "synonyms": synonyms,
                "ontology_id": str(item.get("id", "") or item.get("ilx_id", "") or "").strip() or None,
                "ontology_source": item.get("type") or item.get("ontology"),
                "parent_term": item.get("superclass") or item.get("broader") or item.get("parent"),
                "source_url": item.get("uri") or item.get("url"),
                "extra_attrs": {},
            })

        self._log_step("parse_json", f"Parsed {len(terms)} terms from JSON")
        return terms

    def _build_mapping_candidates(self, terms: list[dict], source: str) -> list[dict]:
        candidates = []
        for t in terms:
            if t.get("ontology_id"):
                candidates.append({
                    "task_id": self.task_id,
                    "source_name": t["term"],
                    "source_atlas": source,
                    "target_name": None,
                    "target_atlas": "NeuroGraphIQ_KG",
                    "mapping_type": "exact",
                    "confidence": 0.7,
                    "evidence": f"ontology_id: {t['ontology_id']}",
                })
        return candidates

    def _validate(self, result: ParseResult) -> None:
        for t in result.term_records:
            if not t.get("term", "").strip():
                result.quality_report.append(
                    self._qissue("empty_term", "error", "Term entry with empty label", affected_field="term")
                )
        if not result.term_records:
            result.quality_report.append(
                self._qissue("no_terms", "warning", "No terms extracted from terminology file")
            )
