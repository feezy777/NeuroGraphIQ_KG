"""
Register this machine's SSH public key on GitHub (via api.github.com), then git push.

Why: On some networks, HTTPS to github.com (20.205.243.166) times out, while
api.github.com and SSH over ssh.github.com:443 work.

Usage (PowerShell):
  $env:GITHUB_TOKEN = "ghp_xxxxxxxx"   # classic PAT with scope: admin:public_key
  python scripts/add_github_ssh_key_and_push.py

If GITHUB_TOKEN is unset, prints the public key — add it manually at:
  https://github.com/settings/keys
Then:
  git remote set-url origin git@github.com:feezy777/NeuroGraphIQ_KG.git
  git push origin HEAD:main --force
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KEY_PATH = Path(os.path.expanduser("~/.ssh/id_ed25519_neurograph.pub"))
REMOTE = "git@github.com:feezy777/NeuroGraphIQ_KG.git"


def ensure_remote_ssh() -> None:
    subprocess.run(
        ["git", "remote", "set-url", "origin", REMOTE],
        cwd=REPO_ROOT,
        check=False,
    )


def read_public_key() -> str:
    if not KEY_PATH.is_file():
        print(f"Missing SSH public key: {KEY_PATH}", file=sys.stderr)
        print("Generate with:", file=sys.stderr)
        print('  ssh-keygen -t ed25519 -f "%USERPROFILE%\\.ssh\\id_ed25519_neurograph" -N ""', file=sys.stderr)
        sys.exit(1)
    return KEY_PATH.read_text(encoding="utf-8").strip()


def post_user_key(token: str, public_key: str) -> None:
    body = json.dumps(
        {"title": "NeuroGraphIQ_KG_V2 auto (Windows)", "key": public_key}
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/user/keys",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"SSH key registered on GitHub (HTTP {resp.status}).")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        if e.code == 422 and ("already in use" in detail.lower() or "key is already" in detail.lower()):
            print("SSH key already exists on your account — continuing.")
            return
        print(f"GitHub API error {e.code}: {detail[:500]}", file=sys.stderr)
        sys.exit(1)


def git_push() -> None:
    subprocess.run(
        ["git", "push", "origin", "HEAD:main", "--force"],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> int:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    public_key = read_public_key()

    if not token:
        print("GITHUB_TOKEN is not set. Add this public key to GitHub, then push:\n")
        print(public_key)
        print("\nhttps://github.com/settings/keys\n")
        print("Then run:")
        print(f'  git -C "{REPO_ROOT}" remote set-url origin {REMOTE}')
        print(f'  git -C "{REPO_ROOT}" push origin HEAD:main --force')
        return 2

    ensure_remote_ssh()
    post_user_key(token, public_key)
    print("Pushing to origin (SSH, port 443 via ~/.ssh/config)...")
    git_push()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
