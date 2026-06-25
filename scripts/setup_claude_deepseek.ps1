# Configure Claude Code to use DeepSeek Anthropic-compatible API.
# Reads DEEPSEEK_API_KEY from backend/.env (never prints the key).
# Usage: .\scripts\setup_claude_deepseek.ps1 [-BudgetMode]

param(
    [ValidateSet('economy', 'balanced', 'quality')]
    [string]$BudgetMode = 'economy'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot 'backend\.env'

if (-not (Test-Path $EnvFile)) {
    Write-Error "Missing $EnvFile — set DEEPSEEK_API_KEY there first."
}

$apiKey = $null
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*DEEPSEEK_API_KEY\s*=\s*(.+)\s*$') {
        $apiKey = $Matches[1].Trim().Trim('"').Trim("'")
    }
}

if ([string]::IsNullOrWhiteSpace($apiKey)) {
    Write-Error 'DEEPSEEK_API_KEY is empty in backend\.env — recharge at https://platform.deepseek.com and paste your key.'
}

# economy: ~$5 balance — same model everywhere, lower effort
# balanced: main deepseek-chat, subagent flash (if available)
# quality: DeepSeek official Claude Code recommendation (higher cost)
$modelMain = 'deepseek-chat'
$modelFast = 'deepseek-chat'
$effort = 'medium'

switch ($BudgetMode) {
    'balanced' {
        $modelMain = 'deepseek-chat'
        $modelFast = 'deepseek-v4-flash'
        $effort = 'medium'
    }
    'quality' {
        $modelMain = 'deepseek-v4-pro[1m]'
        $modelFast = 'deepseek-v4-flash'
        $effort = 'max'
    }
}

$claudeDir = Join-Path $env:USERPROFILE '.claude'
New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null

$settings = [ordered]@{
    env = [ordered]@{
        ANTHROPIC_BASE_URL              = 'https://api.deepseek.com/anthropic'
        ANTHROPIC_AUTH_TOKEN            = $apiKey
        ANTHROPIC_API_KEY               = $apiKey
        ANTHROPIC_MODEL                 = $modelMain
        ANTHROPIC_DEFAULT_OPUS_MODEL    = $modelMain
        ANTHROPIC_DEFAULT_SONNET_MODEL  = $modelMain
        ANTHROPIC_DEFAULT_HAIKU_MODEL   = $modelFast
        CLAUDE_CODE_SUBAGENT_MODEL      = $modelFast
        CLAUDE_CODE_EFFORT_LEVEL        = $effort
        ENABLE_TOOL_SEARCH              = 'true'
    }
}

$settingsPath = Join-Path $claudeDir 'settings.json'
$settings | ConvertTo-Json -Depth 5 | Set-Content -Path $settingsPath -Encoding UTF8

Write-Host 'Claude Code configured for DeepSeek API.'
Write-Host "  Settings: $settingsPath"
Write-Host "  Budget mode: $BudgetMode"
Write-Host "  Main model: $modelMain"
Write-Host "  Fast/subagent model: $modelFast"
Write-Host ''
Write-Host 'Next steps:'
Write-Host '  1. Ensure DeepSeek balance at https://platform.deepseek.com/usage'
Write-Host '  2. Open a NEW terminal'
Write-Host '  3. cd to your project and run: claude'
Write-Host '  4. If prompted for auth, choose API key / skip Anthropic login (DeepSeek key is in settings)'
