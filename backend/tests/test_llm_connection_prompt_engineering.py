"""Connection / projection function prompt engineering tests (Step 10.6.9)."""

from __future__ import annotations

import uuid

import pytest

from app.services.llm_extraction_prompt_engineering import (
    DEFAULT_PAIRS_PER_PACK,
    build_compact_pair_records,
    build_connection_prompt_preview,
    determine_connection_extraction_status,
    make_pair_id,
    normalize_projection_extraction_response,
    pack_pair_records,
    prompt_display_name,
)
from app.services.llm_prompt_defaults import (
    PROJECTION_TO_FUNCTIONS_V1,
    SAME_GRANULARITY_CONNECTION_COMPLETION_V1,
)


def _fake_candidate(**kwargs):
    from app.models.candidate import CandidateBrainRegion

    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_atlas="Macro96",
        source_version="v1",
        raw_name="M1_L",
        en_name="Primary Motor Cortex",
        cn_name="初级运动皮层",
        std_name="M1",
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="rule_passed",
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def test_connection_prompt_contains_neuroscience_role():
    sp = SAME_GRANULARITY_CONNECTION_COMPLETION_V1.system_prompt
    assert "神经科学家" in sp
    assert "neuroscience" in sp.lower()


def test_projection_function_prompt_contains_expert_role():
    sp = PROJECTION_TO_FUNCTIONS_V1.system_prompt
    assert "脑区连接功能专家" in sp
    assert "neuroscience" in sp.lower()


def test_prompt_display_names():
    assert prompt_display_name("same_granularity_connection_completion_v1")
    assert "连接" in prompt_display_name("projection_to_functions_v1") or "Projection" in prompt_display_name("projection_to_functions_v1")  # noqa: E501
    assert prompt_display_name("connection_with_function")


def test_dry_run_prompt_preview_has_display_name():
    preview = build_connection_prompt_preview(
        prompt_key="same_granularity_connection_completion_v1",
        pair_count=2,
        packs=[[{"pair_id": "a::b"}]],
        system_prompt=SAME_GRANULARITY_CONNECTION_COMPLETION_V1.system_prompt,
        sample_user_prompt=SAME_GRANULARITY_CONNECTION_COMPLETION_V1.user_prompt_template,
    )
    assert preview["prompt_display_name"]
    assert preview["pack_count"] == 1
    assert "attributes" not in preview["compact_context_fields"]


def test_prompt_preview_excludes_full_attributes_in_compact_context():
    c1 = _fake_candidate()
    c2 = _fake_candidate()
    pairs = [(c1.id, c2.id)]
    records = build_compact_pair_records([c1, c2], pairs)
    assert records
    for key in records[0]:
        assert key not in {"attributes", "raw_payload_json", "normalized_payload_json"}


def test_4560_pairs_split_into_packs_without_loss():
    ids = [uuid.uuid4() for _ in range(96)]
    pairs = [(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))]
    assert len(pairs) == 4560
    records = [{"pair_id": make_pair_id(a, b)} for a, b in pairs]
    packs = pack_pair_records(records, pairs_per_pack=DEFAULT_PAIRS_PER_PACK)
    assert sum(len(p) for p in packs) == 4560
    assert len(packs) == (4560 + DEFAULT_PAIRS_PER_PACK - 1) // DEFAULT_PAIRS_PER_PACK


def test_reject_projection_missing_pair_id():
    src, tgt = uuid.uuid4(), uuid.uuid4()
    pair_id = make_pair_id(src, tgt)
    conns, _, warnings, handled = normalize_projection_extraction_response(
        {"projections": [{"source_region_candidate_id": str(src), "target_region_candidate_id": str(tgt)}]},
        allowed_pair_ids={pair_id},
        pair_id_to_endpoints={pair_id: (src, tgt)},
    )
    assert not conns
    assert any("missing pair_id" in w for w in warnings)
    assert not handled


def test_reject_unknown_pair_id():
    src, tgt = uuid.uuid4(), uuid.uuid4()
    pair_id = make_pair_id(src, tgt)
    other = make_pair_id(uuid.uuid4(), uuid.uuid4())
    conns, _, warnings, _ = normalize_projection_extraction_response(
        {
            "projections": [{
                "pair_id": other,
                "source_region_candidate_id": str(src),
                "target_region_candidate_id": str(tgt),
                "projection_type": "functional",
                "directionality": "directed",
                "confidence_score": 0.5,
                "evidence_level": "low",
            }]
        },
        allowed_pair_ids={pair_id},
        pair_id_to_endpoints={pair_id: (src, tgt)},
    )
    assert not conns
    assert any("unknown pair_id" in w for w in warnings)


def test_unprocessed_pairs_yield_partial_status():
    status = determine_connection_extraction_status(
        pair_count=10,
        connection_count=2,
        no_connection_count=3,
        unprocessed_pair_count=5,
        provider_failed=False,
    )
    assert status == "partially_succeeded"


def test_all_no_connections_is_succeeded_no_edges():
    status = determine_connection_extraction_status(
        pair_count=3,
        connection_count=0,
        no_connection_count=3,
        unprocessed_pair_count=0,
        provider_failed=False,
    )
    assert status == "succeeded_no_edges"


def test_zero_output_without_no_connections_is_not_succeeded():
    status = determine_connection_extraction_status(
        pair_count=3,
        connection_count=0,
        no_connection_count=0,
        unprocessed_pair_count=0,
        provider_failed=False,
    )
    assert status == "failed_no_output"


def test_valid_projection_accepted():
    src, tgt = uuid.uuid4(), uuid.uuid4()
    pair_id = make_pair_id(src, tgt)
    conns, no_conn, warnings, handled = normalize_projection_extraction_response(
        {
            "projections": [{
                "pair_id": pair_id,
                "source_region_candidate_id": str(src),
                "target_region_candidate_id": str(tgt),
                "projection_type": "functional",
                "directionality": "directed",
                "confidence_score": 0.4,
                "evidence_level": "low",
                "evidence_text": "literature prior",
            }],
            "no_connections": [],
        },
        allowed_pair_ids={pair_id},
        pair_id_to_endpoints={pair_id: (src, tgt)},
    )
    assert len(conns) == 1
    assert not no_conn
    assert pair_id in handled
    assert not any("rejected" in w for w in warnings)


def test_extraction_prompt_templates_api_includes_connection_prompt():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/llm-extraction/prompt-templates")
    assert resp.status_code == 200
    keys = [i["key"] for i in resp.json()["items"]]
    assert "same_granularity_connection_completion_v1" in keys
    assert "projection_to_functions_v1" in keys
    assert "connection_with_function" in keys
