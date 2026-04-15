from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path


def make_id(prefix: str) -> str:
    """Generate a globally unique ID by combining a millisecond timestamp with a UUID4 fragment.

    Using uuid4 instead of a SHA1 of the timestamp ensures that IDs created
    within the same millisecond (e.g. inside a tight parse/chunk loop) are
    always distinct, preventing ON CONFLICT overwrites in PostgreSQL.
    """
    stamp = str(int(time.time() * 1000))
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}_{stamp}_{suffix}"


def file_hash(path: str) -> str:
    h = hashlib.sha1()
    p = Path(path)
    if not p.exists():
        return ""
    with p.open("rb") as fh:
        while True:
            chunk = fh.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def file_type_from_name(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower().strip(".")
    return ext or "unknown"
