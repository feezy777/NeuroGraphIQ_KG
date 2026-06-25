"""Tests for the robust LLM JSON parser (no DB / no HTTP / no DeepSeek)."""

from __future__ import annotations

import uuid

import pytest

from app.services.llm_json_utils import (
    LlmJsonParseError,
    extract_json_object_from_text,
    normalize_connection_completion_payload,
    parse_connection_completion_response,
    parse_llm_json_response,
    raw_response_preview,
)
from app.services.llm_extraction_prompt_engineering import (
    make_pair_id,
    normalize_connection_extraction_payload,
)


def test_parse_plain_json_object():
    parsed = parse_llm_json_response('{"projections": [], "no_connections": []}')
    assert parsed["projections"] == []


def test_parse_json_fenced_block():
    raw = "```json\n{\"projections\": [{\"pair_id\": \"a\"}], \"no_connections\": []}\n```"
    parsed = parse_llm_json_response(raw)
    assert parsed["projections"][0]["pair_id"] == "a"


def test_parse_bare_fenced_block():
    raw = "```\n{\"projections\": []}\n```"
    parsed = parse_llm_json_response(raw)
    assert parsed["projections"] == []


def test_parse_json_with_surrounding_text():
    raw = '好的，这是结果：\n{"projections": [], "no_connections": []}\n以上为分析结论。'
    parsed = parse_llm_json_response(raw)
    assert "projections" in parsed


def test_parse_trailing_comma_repair():
    raw = '{"projections": [{"pair_id": "a"},], "no_connections": [],}'
    parsed = parse_llm_json_response(raw)
    assert parsed["projections"][0]["pair_id"] == "a"


def test_parse_truncated_array_salvage():
    # Truncated mid-array (the dominant DeepSeek failure with large packs).
    raw = '{"projections": [{"pair_id": "a"}, {"pair_id": "b"}, {"pair_id": "c'
    parsed = parse_llm_json_response(raw)
    pids = {p.get("pair_id") for p in parsed.get("projections", [])}
    assert "a" in pids and "b" in pids


def test_parse_unparseable_raises_with_preview():
    raw = "完全不是 JSON 的自然语言回答，没有任何大括号结构。"
    with pytest.raises(LlmJsonParseError) as exc:
        parse_llm_json_response(raw)
    assert exc.value.error_type == "json_decode_error"
    assert exc.value.preview


def test_top_level_array_wrapped():
    parsed = parse_llm_json_response('[{"pair_id": "a"}]')
    assert parsed["_array"][0]["pair_id"] == "a"


def test_extract_returns_error_for_garbage():
    parsed, err = extract_json_object_from_text("no json here")
    assert parsed is None
    assert err


def test_raw_response_preview_bounded():
    preview = raw_response_preview("x" * 5000, limit=100)
    assert len(preview) <= 140
    assert "truncated" in preview


def test_normalize_connections_alias_to_projections():
    payload = normalize_connection_extraction_payload({"connections": [{"pair_id": "a"}]})
    assert payload["projections"][0]["pair_id"] == "a"


def test_normalize_edges_alias_to_projections():
    payload = normalize_connection_extraction_payload({"edges": [{"pair_id": "a"}]})
    assert payload["projections"][0]["pair_id"] == "a"


def test_normalize_no_edges_alias():
    payload = normalize_connection_extraction_payload({"no_edges": [{"pair_id": "a"}]})
    assert payload["no_connections"][0]["pair_id"] == "a"


def test_normalize_top_level_array():
    payload = normalize_connection_extraction_payload([{"pair_id": "a"}])
    assert payload["projections"][0]["pair_id"] == "a"


def test_normalize_recovers_pair_id_from_endpoints():
    src, tgt = uuid.uuid4(), uuid.uuid4()
    pid = make_pair_id(src, tgt)
    endpoints = {pid: (src, tgt)}
    payload = normalize_connection_extraction_payload(
        {"projections": [{"source_region_candidate_id": str(src), "target_region_candidate_id": str(tgt)}]},
        pair_id_to_endpoints=endpoints,
    )
    assert payload["projections"][0]["pair_id"] == pid


def test_parse_links_alias_via_connection_completion():
    parsed = parse_connection_completion_response(
        '{"links": [{"pair_id": "a"}], "no_relations": [{"pair_id": "b", "reason": "x"}]}'
    )
    assert parsed["projections"][0]["pair_id"] == "a"
    assert parsed["no_connections"][0]["pair_id"] == "b"


def test_parse_prefers_schema_object_among_multiple_blocks():
    raw = (
        '说明：{"note": "ignore me"} 以下是结果 '
        '{"projections": [], "no_connections": [{"pair_id": "p1"}], "warnings": []}'
    )
    parsed = parse_connection_completion_response(raw)
    assert parsed["no_connections"][0]["pair_id"] == "p1"


def test_parse_connection_top_level_array():
    parsed = parse_connection_completion_response('[{"pair_id": "a", "projection_type": "anatomical"}]')
    assert parsed["projections"][0]["pair_id"] == "a"
    assert parsed["no_connections"] == []


def test_normalize_links_alias():
    payload = normalize_connection_extraction_payload({"links": [{"pair_id": "a"}]})
    assert payload["projections"][0]["pair_id"] == "a"
