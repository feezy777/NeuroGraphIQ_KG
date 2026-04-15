from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib import error, request


OWNER = "feezy777"
REPO = "NeuroGraphIQ_KG"
BRANCH = "main"
API_BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
ROOT = Path(__file__).resolve().parent.parent


def load_token() -> str:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        return token

    creds_path = Path.home() / ".git-credentials"
    if creds_path.exists():
        raw = creds_path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"https://[^:]+:([^@]+)@github\.com", raw)
        if m:
            return m.group(1)
    raise RuntimeError("github_token_missing")


def api_json(
    token: str,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "NeuroGraphIQ-KG-sync",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"github_api_{exc.code}: {detail[:800]}") from exc


def tracked_files() -> list[tuple[str, str]]:
    proc = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    items: list[tuple[str, str]] = []
    for row in out.split("\x00"):
        if not row.strip():
            continue
        meta, path = row.split("\t", 1)
        mode = meta.split(" ", 1)[0]
        items.append((mode, path))
    return items


def create_blob(token: str, file_path: str) -> str:
    abs_path = ROOT / file_path
    content = abs_path.read_bytes()
    payload = {
        "content": base64.b64encode(content).decode("ascii"),
        "encoding": "base64",
    }
    resp = api_json(token, "POST", f"{API_BASE}/git/blobs", payload)
    return resp["sha"]


def main() -> int:
    token = load_token()
    ref = api_json(token, "GET", f"{API_BASE}/git/ref/heads/{BRANCH}")
    parent_sha = ref["object"]["sha"]
    files = tracked_files()
    if not files:
        raise RuntimeError("no_tracked_files")

    tree_entries: list[dict[str, str]] = []
    total = len(files)
    for idx, (mode, path) in enumerate(files, start=1):
        sha = create_blob(token, path)
        tree_entries.append(
            {
                "path": path.replace("\\", "/"),
                "mode": mode,
                "type": "blob",
                "sha": sha,
            }
        )
        if idx == 1 or idx == total or idx % 10 == 0:
            print(f"[blob] {idx}/{total} {path}")

    tree = api_json(token, "POST", f"{API_BASE}/git/trees", {"tree": tree_entries})
    commit = api_json(
        token,
        "POST",
        f"{API_BASE}/git/commits",
        {
            "message": "sync: overwrite remote main with local workspace snapshot",
            "tree": tree["sha"],
            "parents": [parent_sha],
        },
    )
    api_json(
        token,
        "PATCH",
        f"{API_BASE}/git/refs/heads/{BRANCH}",
        {"sha": commit["sha"], "force": True},
    )
    print(f"SUCCESS ref=refs/heads/{BRANCH} commit={commit['sha']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
