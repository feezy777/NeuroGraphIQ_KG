"""Workbench database administration API.

List / validate / switch PostgreSQL databases for local development.
Does NOT create databases, drop databases, or run migrations.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.database_admin import (
    DatabaseConnectionInfo,
    DatabaseListResponse,
    DatabaseSwitchRequest,
    DatabaseSwitchResponse,
    DatabaseValidationResponse,
)
from app.services import database_admin_service

router = APIRouter()


@router.get("/status", response_model=DatabaseConnectionInfo)
async def get_database_status():
    data = await database_admin_service.get_connection_status()
    return DatabaseConnectionInfo.model_validate(data)


@router.get("/databases", response_model=DatabaseListResponse)
async def list_databases():
    data = await database_admin_service.list_postgres_databases()
    return DatabaseListResponse.model_validate(data)


@router.get("/validate", response_model=DatabaseValidationResponse)
async def validate_database(database: str = Query(min_length=1, max_length=128)):
    data = await database_admin_service.validate_database_schema(database)
    return DatabaseValidationResponse.model_validate(data)


@router.post("/switch", response_model=DatabaseSwitchResponse)
async def switch_database(body: DatabaseSwitchRequest):
    try:
        data = await database_admin_service.switch_database(body.database)
    except database_admin_service.DatabaseSwitchNotAllowedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": exc.reason,
                "database": exc.database,
                "schema_status": exc.status.value,
            },
        ) from exc
    return DatabaseSwitchResponse.model_validate(data)
