from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path


def make_id(prefix: str) -> str:
    stamp = str(int(time.time() * 1000))
    suffix = hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:8]
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
