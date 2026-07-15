"""Pydantic schemas for Resource Registry.

Enum validation mirrors backend/migrations/001_resource_registry.sql CHECK constraints.
Full audit_log persistence is deferred to Logging & Audit module.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

RESOURCE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ResourceType(str, Enum):
    atlas = "atlas"
    label_table = "label_table"
    ontology = "ontology"
    connectivity_matrix = "connectivity_matrix"
    literature = "literature"
    terminology = "terminology"


class Species(str, Enum):
    human = "human"
    mouse = "mouse"
    unknown = "unknown"


class GranularityLevel(str, Enum):
    macro = "macro"
    meso = "meso"
    micro = "micro"
    molecular = "molecular"
    fine_cyto = "fine_cyto"
    term = "term"


class GranularityFamily(str, Enum):
    macro_clinical = "macro_clinical"
    meso_anatomical = "meso_anatomical"
    subregion_connectivity = "subregion_connectivity"
    cytoarchitectonic = "cytoarchitectonic"
    fine_cyto = "fine_cyto"
    histological = "histological"
    molecular = "molecular"
    terminology = "terminology"


class TemplateSpace(str, Enum):
    MNI152 = "MNI152"
    fsaverage = "fsaverage"
    native = "native"
    unknown = "unknown"
    not_applicable = "not_applicable"


class ResourceStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    archived = "archived"


class ResourceCreate(BaseModel):
    resource_code: Annotated[str, Field(min_length=1, max_length=128)]
    source_atlas: Annotated[str, Field(min_length=1, max_length=128)]
    source_version: Annotated[str, Field(min_length=1, max_length=64)]
    resource_type: ResourceType = ResourceType.atlas
    species: Species = Species.human
    granularity_level: GranularityLevel
    granularity_family: GranularityFamily
    template_space: TemplateSpace = TemplateSpace.unknown
    cn_name: str | None = Field(default=None, max_length=500)
    en_name: str | None = Field(default=None, max_length=500)
    description: str | None = None
    remark: str | None = None
    status: ResourceStatus = ResourceStatus.active

    @field_validator("resource_code")
    @classmethod
    def validate_resource_code(cls, value: str) -> str:
        code = value.strip()
        if not RESOURCE_CODE_PATTERN.match(code):
            raise ValueError(
                "resource_code must match ^[a-z][a-z0-9_]*$ (e.g. aal3_v1_macro)"
            )
        return code

    @field_validator("source_atlas", "source_version")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class ResourceUpdate(BaseModel):
    source_atlas: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    source_version: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    resource_type: ResourceType | None = None
    species: Species | None = None
    granularity_level: GranularityLevel | None = None
    granularity_family: GranularityFamily | None = None
    template_space: TemplateSpace | None = None
    cn_name: str | None = Field(default=None, max_length=500)
    en_name: str | None = Field(default=None, max_length=500)
    description: str | None = None
    remark: str | None = None
    status: ResourceStatus | None = None

    @field_validator("source_atlas", "source_version")
    @classmethod
    def validate_non_empty_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class ResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource_code: str
    source_atlas: str
    source_version: str
    resource_type: ResourceType
    species: Species
    granularity_level: GranularityLevel
    granularity_family: GranularityFamily
    template_space: TemplateSpace
    cn_name: str | None
    en_name: str | None
    description: str | None
    remark: str | None
    status: ResourceStatus
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class ResourceListResponse(BaseModel):
    items: list[ResourceRead]
    total: int
    limit: int
    offset: int


class ResourceOptionsResponse(BaseModel):
    resource_type: list[str]
    species: list[str]
    granularity_level: list[str]
    granularity_family: list[str]
    template_space: list[str]
    status: list[str]
