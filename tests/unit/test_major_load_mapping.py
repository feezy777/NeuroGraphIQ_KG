from __future__ import annotations

from scripts.load.load_major_connections_to_pg import map_major_connection_to_db
from scripts.load.load_major_regions_to_pg import map_major_region_to_db
from scripts.utils.constants import DIV_NON_LOBE_DIVISION_BRAIN_ID, ORG_HUMAN_ID


def test_map_major_region_to_db_defaults() -> None:
    payload = map_major_region_to_db(
        {
            "major_region_id": "REG_MAJOR_PFC_LEFT",
            "region_code": "REG_CODE_MAJOR_PFC_LEFT",
            "en_name": "PFC",
            "alias": ["PFC"],
            "laterality": "left",
        }
    )
    assert payload["major_region_id"] == "REG_MAJOR_PFC_LEFT"
    assert payload["organism_id"] == ORG_HUMAN_ID
    assert payload["division_id"] == DIV_NON_LOBE_DIVISION_BRAIN_ID


def test_map_major_connection_to_db() -> None:
    payload = map_major_connection_to_db(
        {
            "major_connection_id": "CONN_MAJOR_PFC_LEFT_AMY_LEFT_STRUCTURAL",
            "connection_code": "CONN_MAJOR_PFC_LEFT_AMY_LEFT_STRUCTURAL",
            "connection_modality": "structural",
            "source_major_region_id": "REG_MAJOR_PFC_LEFT",
            "target_major_region_id": "REG_MAJOR_AMY_LEFT",
        }
    )
    assert payload["major_connection_id"] == "CONN_MAJOR_PFC_LEFT_AMY_LEFT_STRUCTURAL"
    assert payload["source_major_region_id"] == "REG_MAJOR_PFC_LEFT"
    assert payload["target_major_region_id"] == "REG_MAJOR_AMY_LEFT"

