"""Parser-aware file binding validation for import batches."""

from __future__ import annotations

from app.models.resource_file import ResourceFile
from app.schemas.import_batch import FileRoleInBatch


class ParserFileBindingError(ValueError):
    pass


def validate_parser_file_binding(
    parser_key: str | None,
    file_role_in_batch: str,
    resource_file: ResourceFile,
) -> None:
    """Raise ParserFileBindingError when parser_key and file role/type mismatch."""
    pk = (parser_key or "").strip()
    role = file_role_in_batch

    if pk == "macro96_xlsx":
        if role != FileRoleInBatch.macro_region_pool_source.value:
            raise ParserFileBindingError(
                "macro96_xlsx requires file_role_in_batch=macro_region_pool_source"
            )
        ext = (resource_file.file_ext or "").lower()
        name = resource_file.original_filename.lower()
        is_spreadsheet = (
            resource_file.file_type == "spreadsheet"
            or ext in (".xlsx", ".xls")
            or name.endswith(".xlsx")
            or name.endswith(".xls")
        )
        if not is_spreadsheet:
            raise ParserFileBindingError("macro96_xlsx requires spreadsheet file")
        return

    if pk in ("aal3_xml", "aal3_label_table"):
        if role != FileRoleInBatch.label_dictionary.value:
            raise ParserFileBindingError("aal3_xml requires file_role_in_batch=label_dictionary")
        ext = (resource_file.file_ext or "").lower()
        name = resource_file.original_filename.lower()
        is_xml_label = resource_file.file_type == "label_table" and (
            ext == ".xml" or name.endswith(".xml")
        )
        if not is_xml_label:
            raise ParserFileBindingError("aal3_xml requires XML label dictionary file")
        return
