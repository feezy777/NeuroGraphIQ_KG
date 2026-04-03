from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.parse(io.BytesIO(zf.read("xl/sharedStrings.xml"))).getroot()
    values: list[str] = []
    for si in root.findall("a:si", NS):
        text_parts: list[str] = []
        direct = si.find("a:t", NS)
        if direct is not None and direct.text:
            text_parts.append(direct.text)
        for run in si.findall("a:r", NS):
            t = run.find("a:t", NS)
            if t is not None and t.text:
                text_parts.append(t.text)
        values.append("".join(text_parts))
    return values


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    value_node = cell.find("a:v", NS)
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text
    if cell_type == "s":
        idx = int(raw)
        if 0 <= idx < len(shared):
            return shared[idx]
    return raw


def _col_from_ref(cell_ref: str) -> str:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    return letters


def read_xlsx_rows(path: str | Path, sheet_index: int = 1, header_row: int = 1) -> list[dict[str, str]]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Excel file not found: {file_path}")
    if file_path.suffix.lower() != ".xlsx":
        raise ValueError("Only .xlsx files are supported by the built-in reader.")

    with zipfile.ZipFile(file_path, "r") as zf:
        shared = _read_shared_strings(zf)
        sheet_path = f"xl/worksheets/sheet{sheet_index}.xml"
        if sheet_path not in zf.namelist():
            raise ValueError(f"Sheet index {sheet_index} not found in workbook.")
        root = ET.parse(io.BytesIO(zf.read(sheet_path))).getroot()
        rows = root.findall(".//a:sheetData/a:row", NS)

        table_rows: list[dict[str, str]] = []
        headers: dict[str, str] = {}
        for row in rows:
            row_number = int(row.attrib.get("r", "0"))
            values_by_col: dict[str, str] = {}
            for cell in row.findall("a:c", NS):
                ref = cell.attrib.get("r", "")
                col = _col_from_ref(ref)
                values_by_col[col] = _cell_value(cell, shared)

            if row_number == header_row:
                headers = {col: value.strip() for col, value in values_by_col.items() if value.strip()}
                continue
            if row_number < header_row:
                continue
            if not headers:
                raise ValueError("Excel header row could not be parsed.")

            record: dict[str, str] = {}
            for col, header in headers.items():
                record[header] = values_by_col.get(col, "").strip()
            if any(v for v in record.values()):
                table_rows.append(record)
        return table_rows
