# Push NeuroGraphIQ_KG to GitHub when HTTPS to github.com is blocked.
# Prerequisites: ~/.ssh/config routes github.com -> ssh.github.com:443 (see docs/GITHUB_PUBLISH.md)
#
# Option A — PAT registers SSH key then pushes (one-time):
#   $env:GITHUB_TOKEN = "ghp_..."   # classic PAT, scope: admin:public_key
#   python scripts/add_github_ssh_key_and_push.py
#
# Option B — add ~/.ssh/id_ed25519_neurograph.pub at https://github.com/settings/keys then:
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
git remote set-url origin "git@github.com:feezy777/NeuroGraphIQ_KG.git"
git push origin HEAD:main --force
