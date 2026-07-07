"""Pricing API routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.pricing.loader import get_all_entries, get_version

router = APIRouter()


@router.get("/pricing/models")
async def list_pricing_models():
    """Return all configured provider/model pricing entries."""
    return {
        "version": get_version(),
        "models": get_all_entries(),
    }
