"""Pydantic schemas + deterministic rule definitions for Rule Validation Module.

Reads candidate_brain_regions; produces validation runs + per-candidate results.
NO LLM. rule_passed != manual_approved != promoted_to_final.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class RuleValidationRunStatus(str, Enum):
    created = "created"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ValidationScope(str, Enum):
    candidate = "candidate"
    generation_run = "generation_run"
    batch = "batch"
    parse_run = "parse_run"


class RuleSeverity(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"


class CandidateRuleStatus(str, Enum):
    """Per-candidate overall outcome of a rule validation run."""

    passed = "passed"
    failed = "failed"


VALID_LATERALITY: frozenset[str] = frozenset(
    {"left", "right", "bilateral", "midline", "unknown"}
)


class RuleCheckResult(BaseModel):
    rule_id: str
    check_type: str
    severity: RuleSeverity
    passed: bool
    message: str


class RuleValidationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: ValidationScope
    batch_id: uuid.UUID
    resource_id: uuid.UUID
    generation_run_id: uuid.UUID | None
    parse_run_id: uuid.UUID | None
    target_candidate_id: uuid.UUID | None
    validator_key: str
    validator_version: str
    status: RuleValidationRunStatus
    candidate_count: int
    passed_count: int
    failed_count: int
    warning_count: int
    skipped_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CandidateRuleValidationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    validation_run_id: uuid.UUID
    candidate_id: uuid.UUID
    batch_id: uuid.UUID
    resource_id: uuid.UUID
    generation_run_id: uuid.UUID
    parse_run_id: uuid.UUID
    overall_status: CandidateRuleStatus
    error_count: int
    warning_count: int
    info_count: int
    checks: list[dict[str, Any]]
    created_at: datetime


class RuleValidationRunListResponse(BaseModel):
    items: list[RuleValidationRunRead]
    total: int
    limit: int
    offset: int


class CandidateRuleResultListResponse(BaseModel):
    items: list[CandidateRuleValidationResultRead]
    total: int
    limit: int
    offset: int


class ValidateCandidatesResponse(BaseModel):
    validation_run: RuleValidationRunRead
    candidate_count: int
    passed_count: int
    failed_count: int
    warning_count: int
    skipped_count: int


class RuleDefinition(BaseModel):
    rule_id: str
    check_type: str
    severity: RuleSeverity
    description: str


class RuleValidationOptionsResponse(BaseModel):
    scope: list[str]
    run_status: list[str]
    severity: list[str]
    candidate_rule_status: list[str]
    rules: list[RuleDefinition]


# Deterministic rule catalogue (no LLM). Each rule maps to a RuleDefinition; the
# service evaluates them against candidate_brain_regions rows.
RULE_CATALOGUE: list[RuleDefinition] = [
    RuleDefinition(
        rule_id="raw_name_not_empty",
        check_type="empty_name",
        severity=RuleSeverity.error,
        description="raw_name must be non-empty",
    ),
    RuleDefinition(
        rule_id="laterality_valid",
        check_type="laterality_validity",
        severity=RuleSeverity.error,
        description="laterality must be one of left/right/bilateral/midline/unknown",
    ),
    RuleDefinition(
        rule_id="granularity_present",
        check_type="granularity_coverage",
        severity=RuleSeverity.error,
        description="granularity_level and granularity_family must be present",
    ),
    RuleDefinition(
        rule_id="std_name_present",
        check_type="std_name_coverage",
        severity=RuleSeverity.warning,
        description="std_name should be present",
    ),
    RuleDefinition(
        rule_id="laterality_known",
        check_type="laterality_coverage",
        severity=RuleSeverity.warning,
        description="laterality should not be unknown",
    ),
    RuleDefinition(
        rule_id="source_id_present",
        check_type="source_id_coverage",
        severity=RuleSeverity.warning,
        description="source_label_id or label_value should be present",
    ),
    RuleDefinition(
        rule_id="unique_label_value_in_run",
        check_type="duplicate_label_value",
        severity=RuleSeverity.warning,
        description="label_value should be unique within the generation run (no auto-merge)",
    ),
    RuleDefinition(
        rule_id="unique_name_laterality_in_run",
        check_type="duplicate_name_laterality",
        severity=RuleSeverity.warning,
        description="region name + laterality should be unique within the run (no auto-merge)",
    ),
]
