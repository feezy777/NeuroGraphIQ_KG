"""JSON-safe value conversion for JSONB columns and API responses."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


def to_jsonable(value: Any) -> Any:
    """Recursively convert values to JSON-serializable Python types."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return repr(value)

    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]

    if hasattr(value, "hex") and hasattr(value, "int"):
        # UUID-like without isinstance check for some drivers
        try:
            return str(value)
        except Exception:
            pass

    return str(value)


def json_dumps_safe(value: Any, **kwargs: Any) -> str:
    """json.dumps after to_jsonable conversion."""
    return json.dumps(to_jsonable(value), **kwargs)
