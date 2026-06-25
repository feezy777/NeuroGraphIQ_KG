from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParseResult:
    """Standard output contract for every resource parser.

    Fields not produced by a specific resource should be left as empty lists.
    """

    resource_info: dict[str, Any] = field(default_factory=dict)
    """Top-level metadata about the resource (name, version, source, etc.)"""

    file_records: list[dict[str, Any]] = field(default_factory=list)
    """Metadata about the raw files consumed during parsing."""

    region_records: list[dict[str, Any]] = field(default_factory=list)
    """Brain region / parcellation entries. Used by AAL3, Brainnetome, HCP-MMP, etc."""

    connection_records: list[dict[str, Any]] = field(default_factory=list)
    """Connectivity entries (structural / functional). Used by Brainnetome."""

    function_records: list[dict[str, Any]] = field(default_factory=list)
    """Functional annotation entries."""

    molecular_records: list[dict[str, Any]] = field(default_factory=list)
    """Gene-expression / molecular attribute entries. Used by Allen."""

    term_records: list[dict[str, Any]] = field(default_factory=list)
    """Ontology term / definition entries. Used by InterLex / BrainInfo."""

    mapping_candidates: list[dict[str, Any]] = field(default_factory=list)
    """Cross-atlas mapping candidates produced during parsing."""

    quality_report: list[dict[str, Any]] = field(default_factory=list)
    """Quality issues detected by the parser itself."""

    import_log: list[dict[str, Any]] = field(default_factory=list)
    """Step-by-step log entries for audit trail."""

    def summary(self) -> dict[str, int]:
        return {
            "regions": len(self.region_records),
            "connections": len(self.connection_records),
            "functions": len(self.function_records),
            "molecular": len(self.molecular_records),
            "terms": len(self.term_records),
            "mappings": len(self.mapping_candidates),
            "quality_issues": len(self.quality_report),
        }


class BaseParser(ABC):
    """Abstract base class that every resource-specific parser must implement."""

    PARSER_NAME: str = "base"
    RESOURCE_TYPE: str = "other"

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._log: list[dict[str, Any]] = []

    def _log_step(self, step: str, message: str, level: str = "info") -> None:
        self._log.append({"step": step, "message": message, "level": level})

    def _qissue(
        self,
        check_type: str,
        severity: str,
        message: str,
        affected_id: str | None = None,
        affected_field: str | None = None,
    ) -> dict[str, Any]:
        return {
            "check_type": check_type,
            "severity": severity,
            "message": message,
            "affected_id": affected_id,
            "affected_field": affected_field,
            "auto_fixable": False,
        }

    @abstractmethod
    def parse(self, file_path: str) -> ParseResult:
        """Parse the resource file and return a standard ParseResult.

        Args:
            file_path: Absolute path to the primary input file.

        Returns:
            A populated ParseResult instance.
        """
        ...

    def _finalize(self, result: ParseResult) -> ParseResult:
        result.import_log = self._log
        return result
