from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.parsers.macro96_xlsx import Macro96IntermediateInvalidError, Macro96ParseError
from app.schemas.macro96_raw_parsing import (
    ParseMacro96Response,
    RawMacro96RegionRowListResponse,
    RawMacro96RegionRowRead,
)
from app.schemas.raw_parsing import (
    Laterality,
    ParseAal3Response,
    ParseRunStatus,
    ParserKey,
    RawAal3LabelListResponse,
    RawAal3RegionLabelRead,
    RawParseRunListResponse,
    RawParseRunRead,
    RawParsingOptionsResponse,
)
from app.services import raw_parsing_service

router = APIRouter()
batch_router = APIRouter()
parse_run_router = APIRouter()


@router.get("/options", response_model=RawParsingOptionsResponse)
async def get_raw_parsing_options():
    return RawParsingOptionsResponse(
        parser_key=[e.value for e in ParserKey],
        parse_run_status=[e.value for e in ParseRunStatus],
        laterality=[e.value for e in Laterality],
    )


@batch_router.post("/{batch_id}/parse-aal3", response_model=ParseAal3Response)
async def parse_aal3_batch(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        run = await raw_parsing_service.parse_aal3_for_batch(session, batch_id)
    except raw_parsing_service.BoundFileNotActiveError as exc:
        raise HTTPException(
            status_code=409,
            detail=raw_parsing_service.bound_file_not_active_detail(exc),
        ) from exc
    except raw_parsing_service.BatchNotRunnableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except raw_parsing_service.NoLabelFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except raw_parsing_service.NoAal3XmlLabelDictionaryError as exc:
        raise HTTPException(
            status_code=400,
            detail=raw_parsing_service.no_aal3_xml_label_dictionary_detail(exc),
        ) from exc
    except raw_parsing_service.DuplicateParseError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "successful parse already exists for this batch and parser_key",
                "batch_id": str(exc.batch_id),
                "parser_key": exc.parser_key,
                "existing_parse_run_id": str(exc.existing_run_id),
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    data = raw_parsing_service.parse_run_to_read(run)
    return ParseAal3Response(
        parse_run=RawParseRunRead.model_validate(data),
        output_count=run.output_count,
        warning_count=run.warning_count,
    )


@batch_router.get("/{batch_id}/parse-runs", response_model=RawParseRunListResponse)
async def list_batch_parse_runs(
    batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    from app.services import import_batch_service

    try:
        await import_batch_service.get_batch(session, batch_id)
    except import_batch_service.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="import batch not found") from exc

    runs = await raw_parsing_service.list_parse_runs_for_batch(session, batch_id)
    items = [
        RawParseRunRead.model_validate(raw_parsing_service.parse_run_to_read(r)) for r in runs
    ]
    return RawParseRunListResponse(items=items, total=len(items))


@parse_run_router.get("/{parse_run_id}", response_model=RawParseRunRead)
async def get_parse_run_detail(
    parse_run_id: uuid.UUID, session: AsyncSession = Depends(get_db)
):
    try:
        run = await raw_parsing_service.get_parse_run(session, parse_run_id)
    except raw_parsing_service.ParseRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="parse run not found") from exc
    return RawParseRunRead.model_validate(raw_parsing_service.parse_run_to_read(run))


@parse_run_router.get("/{parse_run_id}/aal3-labels", response_model=RawAal3LabelListResponse)
async def list_parse_run_aal3_labels(
    parse_run_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    laterality: Laterality | None = None,
    session: AsyncSession = Depends(get_db),
):
    try:
        await raw_parsing_service.get_parse_run(session, parse_run_id)
    except raw_parsing_service.ParseRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="parse run not found") from exc

    items, total = await raw_parsing_service.list_aal3_labels(
        session,
        parse_run_id=parse_run_id,
        laterality=laterality.value if laterality else None,
        limit=limit,
        offset=offset,
    )
    return RawAal3LabelListResponse(
        items=[RawAal3RegionLabelRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/aal3-labels", response_model=RawAal3LabelListResponse)
async def list_raw_aal3_labels(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    parse_run_id: uuid.UUID | None = None,
    laterality: Laterality | None = None,
    granularity_level: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await raw_parsing_service.list_aal3_labels(
        session,
        parse_run_id=parse_run_id,
        batch_id=batch_id,
        resource_id=resource_id,
        laterality=laterality.value if laterality else None,
        granularity_level=granularity_level,
        limit=limit,
        offset=offset,
    )
    return RawAal3LabelListResponse(
        items=[RawAal3RegionLabelRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/macro96-rows", response_model=RawMacro96RegionRowListResponse)
async def list_raw_macro96_rows(
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    parse_run_id: uuid.UUID | None = None,
    source_file_id: uuid.UUID | None = None,
    granularity_level: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    items, total = await raw_parsing_service.list_macro96_rows(
        session,
        parse_run_id=parse_run_id,
        batch_id=batch_id,
        resource_id=resource_id,
        source_file_id=source_file_id,
        granularity_level=granularity_level,
        limit=limit,
        offset=offset,
    )
    return RawMacro96RegionRowListResponse(
        items=[RawMacro96RegionRowRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@batch_router.post("/{batch_id}/parse-macro96", response_model=ParseMacro96Response)
async def parse_macro96_batch(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    try:
        result = await raw_parsing_service.parse_macro96_for_batch(session, batch_id)
    except raw_parsing_service.BoundFileNotActiveError as exc:
        raise HTTPException(
            status_code=409,
            detail=raw_parsing_service.bound_file_not_active_detail(exc),
        ) from exc
    except raw_parsing_service.BatchNotRunnableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except raw_parsing_service.WrongParserKeyError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "WRONG_PARSER_KEY",
                "message": str(exc),
                "batch_id": str(exc.batch_id),
                "expected": exc.expected,
                "actual": exc.actual,
            },
        ) from exc
    except raw_parsing_service.NoMacro96PoolSourceError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "NO_MACRO96_POOL_SOURCE",
                "message": str(exc),
                "batch_id": str(exc.batch_id),
                "suggestion": (
                    "Bind a file with file_role_in_batch=macro_region_pool_source "
                    "to this batch before parsing."
                ),
            },
        ) from exc
    except raw_parsing_service.NoMacro96IntermediateError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "NO_MACRO96_INTERMEDIATE",
                "message": str(exc),
                "file_id": str(exc.file_id),
                "batch_id": str(exc.batch_id),
                "suggestion": (
                    "Open File Center, select the file, and run normalization "
                    "to generate the macro_region_table intermediate artifact."
                ),
            },
        ) from exc
    except raw_parsing_service.DuplicateParseError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DUPLICATE_PARSE",
                "message": "macro96 parser already succeeded for this batch",
                "batch_id": str(exc.batch_id),
                "parser_key": exc.parser_key,
                "existing_parse_run_id": str(exc.existing_run_id),
            },
        ) from exc
    except (Macro96ParseError, Macro96IntermediateInvalidError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result
