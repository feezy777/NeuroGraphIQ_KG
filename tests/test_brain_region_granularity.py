"""三层颗粒度（major/sub/allen）策略与校验的单元测试。"""
from __future__ import annotations

import json
import unittest

from scripts.modules.workbench.extraction.brain_region_granularity import (
    GRANULARITY_ALLEN,
    GRANULARITY_MAJOR,
    GRANULARITY_SUB,
    dedupe_key,
    detect_non_brain_entity,
    empty_unified_record,
    row_to_unified_schema,
    staging_gate_reason,
    strip_laterality_from_name,
    validate_unified_record,
)


class TestBrainRegionGranularity(unittest.TestCase):
    def test_major_root_no_parent(self) -> None:
        u = empty_unified_record()
        u["granularity"] = GRANULARITY_MAJOR
        u["canonical_name_en"] = "Frontal lobe"
        u["primary_parent_granularity"] = "root"
        u["primary_parent_name"] = ""
        self.assertEqual(detect_non_brain_entity(u), None)
        self.assertEqual(validate_unified_record(u), [])

    def test_sub_requires_major_parent(self) -> None:
        u = empty_unified_record()
        u["granularity"] = GRANULARITY_SUB
        u["canonical_name_en"] = "Superior frontal gyrus"
        u["primary_parent_granularity"] = "major"
        u["primary_parent_name"] = "Frontal lobe"
        self.assertEqual(validate_unified_record(u), [])

    def test_sub_missing_parent_errors(self) -> None:
        u = empty_unified_record()
        u["granularity"] = GRANULARITY_SUB
        u["canonical_name_en"] = "Some subregion"
        u["primary_parent_granularity"] = "major"
        u["primary_parent_name"] = ""
        errs = validate_unified_record(u)
        self.assertIn("sub_requires_primary_parent_name", errs)

    def test_allen_allen_source_and_sub_parent(self) -> None:
        u = empty_unified_record()
        u["granularity"] = GRANULARITY_ALLEN
        u["canonical_name_en"] = "VISp"
        u["source"] = "Allen"
        u["source_id"] = "385"
        u["source_acronym"] = "VISp"
        u["primary_parent_granularity"] = "sub"
        u["primary_parent_name"] = "Primary visual area"
        self.assertEqual(validate_unified_record(u), [])

    def test_allen_missing_source_id(self) -> None:
        u = empty_unified_record()
        u["granularity"] = GRANULARITY_ALLEN
        u["source"] = "Allen"
        u["source_id"] = ""
        u["primary_parent_granularity"] = "sub"
        u["primary_parent_name"] = "Visual areas"
        errs = validate_unified_record(u)
        self.assertTrue(any("allen_source_id" in e for e in errs))

    def test_excluded_functional_network(self) -> None:
        u = empty_unified_record()
        u["canonical_name_en"] = "default mode network"
        u["canonical_name_cn"] = "默认模式网络"
        self.assertEqual(detect_non_brain_entity(u), "functional_network")

    def test_excluded_circuit_keyword(self) -> None:
        u = empty_unified_record()
        u["canonical_name_en"] = "Papez circuit"
        self.assertEqual(detect_non_brain_entity(u), "circuit")

    def test_excluded_ventricle(self) -> None:
        u = empty_unified_record()
        u["canonical_name_en"] = "lateral ventricle"
        self.assertEqual(detect_non_brain_entity(u), "ventricle")

    def test_ambiguous_major_with_allen_like_name_review(self) -> None:
        """歧义：名称像细粒度但无 Allen ID — 不自动标 allen（由模型设 review_required；此处仅校验层级。"""
        u = empty_unified_record()
        u["granularity"] = GRANULARITY_MAJOR
        u["canonical_name_en"] = "Hippocampus"
        u["review_required"] = True
        self.assertEqual(validate_unified_record(u), [])

    def test_major_with_parent_name_invalid(self) -> None:
        u = empty_unified_record()
        u["granularity"] = GRANULARITY_MAJOR
        u["primary_parent_granularity"] = "root"
        u["primary_parent_name"] = "Brain"
        errs = validate_unified_record(u)
        self.assertIn("major_must_not_have_named_parent", errs)

    def test_dedupe_key_triple(self) -> None:
        u = empty_unified_record()
        u["canonical_name_en"] = "Hippocampus"
        u["granularity"] = GRANULARITY_MAJOR
        u["laterality"] = "left"
        k1 = dedupe_key(u)
        u2 = dict(u)
        u2["laterality"] = "right"
        k2 = dedupe_key(u2)
        self.assertNotEqual(k1, k2)

    def test_staging_gate_review_required(self) -> None:
        note = json.dumps(
            {"brain_region_classification": {"review_required": True, "granularity": "allen"}},
            ensure_ascii=False,
        )
        self.assertEqual(staging_gate_reason(note), "granularity_review_required")

    def test_staging_gate_excluded(self) -> None:
        note = json.dumps(
            {
                "brain_region_classification": {
                    "review_reason": "excluded_non_brain:functional_network",
                }
            },
            ensure_ascii=False,
        )
        self.assertEqual(staging_gate_reason(note), "excluded_non_brain_entity")

    def test_strip_laterality_suffix(self) -> None:
        self.assertEqual(strip_laterality_from_name("Hippocampus (left)"), "Hippocampus")
        self.assertEqual(strip_laterality_from_name("Caudate nucleus, left"), "Caudate nucleus")

    def test_row_legacy_keys_map_to_unified(self) -> None:
        row = {
            "en_name_candidate": "Amygdala",
            "cn_name_candidate": "杏仁核",
            "granularity_candidate": "major",
            "laterality_candidate": "unknown",
        }
        u = row_to_unified_schema(row)
        self.assertEqual(u["canonical_name_en"], "Amygdala")
        self.assertEqual(u["granularity"], GRANULARITY_MAJOR)


if __name__ == "__main__":
    unittest.main()
