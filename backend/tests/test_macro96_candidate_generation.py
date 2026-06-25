"""Tests for Macro96 candidate generation — no PostgreSQL required."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import candidate_service, macro96_candidate_service
from app.services.candidate_service import WrongCandidateGeneratorForMacro96Error
from app.services.macro96_candidate_service import (
    GENERATOR_KEY,
    WrongParserKeyError,
)
from app.services.workbench_pipeline_service import compute_next_allowed_actions
from app.utils.macro96_laterality import infer_macro96_laterality


# ─── Laterality inference ────────────────────────────────────────────────────

def test_laterality_left_en_prefix():
    assert infer_macro96_laterality("left lateral ventricle", None) == "left"


def test_laterality_right_en_prefix():
    assert infer_macro96_laterality("right insula", None) == "right"


def test_laterality_left_cn():
    assert infer_macro96_laterality("some region", "左侧脑室") == "left"


def test_laterality_right_cn():
    assert infer_macro96_laterality("some region", "右脑岛") == "right"


def test_laterality_bilateral_en():
    assert infer_macro96_laterality("bilateral hippocampus", None) == "bilateral"


def test_laterality_midline_white_matter():
    assert infer_macro96_laterality("white matter", "脑白质") == "midline"


def test_laterality_unknown():
    assert infer_macro96_laterality("frontal lobe", "额叶") == "unknown"


# ─── Pipeline actions ────────────────────────────────────────────────────────

def test_parsed_macro96_allows_generate_macro96_candidates():
    actions = compute_next_allowed_actions("parsed", parser_key="macro96_xlsx")
    assert len(actions) == 1
    assert actions[0].action == "generate_macro96_candidates"


def test_parsed_aal3_allows_generate_candidates():
    actions = compute_next_allowed_actions("parsed", parser_key="aal3_xml")
    assert len(actions) == 1
    assert actions[0].action == "generate_candidates"


# ─── Wrong generator guards ──────────────────────────────────────────────────

def test_aal3_generator_rejects_macro96_batch_parser_key():
    err = WrongCandidateGeneratorForMacro96Error(uuid.uuid4(), "macro96_xlsx")
    assert err.parser_key == "macro96_xlsx"


def test_macro96_generator_constants():
    assert GENERATOR_KEY == "macro96_candidate_v1"
    assert macro96_candidate_service.SOURCE_RAW_TABLE == "raw_macro96_region_rows"


# ─── Governance ──────────────────────────────────────────────────────────────

def test_macro96_candidate_service_governance_boundary():
    import app.services.macro96_candidate_service as mod

    assert not hasattr(mod, "FinalBrainRegion")
    assert macro96_candidate_service.SOURCE_RAW_TABLE == "raw_macro96_region_rows"


def test_migration_018_drops_aal3_only_fk():
    import pathlib

    p = pathlib.Path(__file__).parent.parent / "migrations" / "018_macro96_candidate_source.sql"
    assert p.exists()
    sql = p.read_text(encoding="utf-8")
    assert "DROP CONSTRAINT" in sql
    assert "source_raw_table" in sql


@pytest.mark.asyncio
async def test_generate_macro96_wrong_parser_key():
    batch_id = uuid.uuid4()
    mock_batch = MagicMock()
    mock_batch.parser_key = "aal3_xml"
    mock_batch.status = "parsed"

    mock_session = AsyncMock()
    with patch(
        "app.services.macro96_candidate_service.import_batch_service.get_batch",
        return_value=mock_batch,
    ):
        with pytest.raises(WrongParserKeyError):
            await macro96_candidate_service.generate_macro96_candidates_for_batch(
                mock_session, batch_id
            )


@pytest.mark.asyncio
async def test_aal3_generate_rejects_macro96_parser():
    batch_id = uuid.uuid4()
    mock_batch = MagicMock()
    mock_batch.parser_key = "macro96_xlsx"
    mock_batch.status = "parsed"

    mock_session = AsyncMock()
    with patch(
        "app.services.candidate_service.import_batch_service.get_batch",
        return_value=mock_batch,
    ):
        with pytest.raises(WrongCandidateGeneratorForMacro96Error) as exc_info:
            await candidate_service.generate_candidates_for_batch(mock_session, batch_id)
        assert exc_info.value.parser_key == "macro96_xlsx"
