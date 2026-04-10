from __future__ import annotations

from typing import Any, Dict, List

from ..common.id_utils import make_id
from ..common.models import GranularityMapping


class GranularityService:
    def classify(self, file_id: str, candidates: Dict[str, Any]) -> GranularityMapping:
        entities: List[Dict[str, Any]] = candidates.get("candidate_entities", [])
        relations: List[Dict[str, Any]] = candidates.get("candidate_relations", [])
        connections: List[Dict[str, Any]] = candidates.get("candidate_connections", [])
        circuits: List[Dict[str, Any]] = candidates.get("candidate_circuits", [])

        major_regions = [{"name": "REG_MAJOR_PLACEHOLDER", "source": entities[0]["entity_id"]}] if entities else []
        sub_regions = []
        allen_regions = []
        functions = [{"name": "FUNCTION_PLACEHOLDER", "confidence": 0.5}] if entities else []
        evidences = [{"fragment": "evidence placeholder", "source": entities[0]["entity_id"]}] if entities else []
        cross = [{"from": "major_region", "to": "connection", "type": "supports"}] if connections else []

        return GranularityMapping(
            mapping_id=make_id("map"),
            file_id=file_id,
            major_regions=major_regions,
            sub_regions=sub_regions,
            allen_regions=allen_regions,
            connections=connections,
            circuits=circuits,
            functions=functions,
            evidences=evidences,
            cross_granularity_edges=cross,
        )
