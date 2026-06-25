from pathlib import Path

from app.parsers.aal3_parser import AAL3Parser
from app.parsers.aal3_xml import parse_aal3_xml

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_aal3_xml_sample():
    rows = parse_aal3_xml(FIXTURES / "AAL3v1_1mm_sample.xml")
    assert len(rows) == 3
    assert rows[0]["label_index"] == 1
    assert rows[0]["abbr"] == "Precentral_L"
    assert rows[0]["hemisphere"] == "L"
    assert rows[0]["coordinates_mni"]["x"] == -38.5
    assert rows[0]["bounding_box"] is not None


def test_parse_pair_with_fixture(tmp_path):
    nii = tmp_path / "AAL3v1_1mm.nii"
    nii.write_bytes(b"\x00")
    xml = FIXTURES / "AAL3v1_1mm_sample.xml"
    result = AAL3Parser(task_id="test").parse_pair(str(nii), str(xml))
    assert len(result.region_records) == 3
    assert result.region_records[0]["full_name"] == "Precentral_L"
    assert not any(q["severity"] == "error" for q in result.quality_report)
