# Check PostgreSQL connectivity using the same parameters as backend/.env
# Usage: .\scripts\db_check_connection.ps1

$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_db_env.ps1"

$cfg = Get-ProjectDbConfig
$psql = Get-PsqlExecutable

function Write-Check([string]$Key, [string]$Value) {
    Write-Host "[DB_CHECK] $Key=$Value"
}

Write-Check 'env_file' $cfg.EnvFile
Write-Check 'env_exists' $cfg.EnvFileExists
Write-Check 'host' $cfg.DbHost
Write-Check 'port' $cfg.Port
Write-Check 'user' $cfg.User
Write-Check 'workbench_db' $cfg.WorkbenchDatabase
Write-Check 'candidate_db' $cfg.CandidateDatabase

# TCP
$tcpOk = $false
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect($cfg.DbHost, $cfg.Port, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(3000, $false)
    if ($ok -and $client.Connected) { $tcpOk = $true }
    $client.Close()
} catch { $tcpOk = $false }
Write-Check 'tcp_ok' $tcpOk

if (-not $tcpOk) {
    Write-Host '[DB_CHECK] HINT: No service on this port. Windows PostgreSQL vs Docker: see docs/dbeaver_postgres_connection.md' -ForegroundColor Yellow
    exit 1
}

if (-not $cfg.Password) {
    Write-Host '[DB_CHECK] HINT: Set POSTGRES_PASSWORD in backend/.env or env PGPASSWORD' -ForegroundColor Yellow
}

$env:PGPASSWORD = $cfg.Password
$loginOk = $false
$loginOut = & $psql -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d postgres -tAc 'SELECT 1' 2>&1
if ($LASTEXITCODE -eq 0 -and "$loginOut".Trim() -eq '1') { $loginOk = $true }
Write-Check 'login_ok' $loginOk

if (-not $loginOk) {
    Write-Host "[DB_CHECK] login_error=$loginOut" -ForegroundColor Red
    Write-Host '[DB_CHECK] HINT: Password mismatch? Run scripts/db_fix_postgres_password.ps1 or fix DBeaver saved password.' -ForegroundColor Yellow
    Write-Host '[DB_CHECK] HINT: .env.example uses postgres/postgres for local dev; your DBeaver profile may still say password.' -ForegroundColor Yellow
    exit 1
}

$dbExists = $false
$ex = (& $psql -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d postgres -tAc `
    "SELECT 1 FROM pg_database WHERE datname='$($cfg.WorkbenchDatabase)'" 2>&1).Trim()
if ($LASTEXITCODE -eq 0 -and $ex -eq '1') { $dbExists = $true }
Write-Check 'database_exists' $dbExists

if (-not $dbExists) {
    Write-Host "[DB_CHECK] HINT: Create DB with .\scripts\init-workbench-database.ps1" -ForegroundColor Yellow
}

# Python / SQLAlchemy (same as backend)
$alembicOk = $false
$backendRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend'
$py = Join-Path $backendRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$pyScript = @"
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal
async def main():
    async with AsyncSessionLocal() as s:
        await s.execute(text('SELECT 1'))
asyncio.run(main())
print('ok')
"@
$prev = $env:PYTHONPATH
$env:PYTHONPATH = $backendRoot
try {
    $pyOut = & $py -c $pyScript 2>&1
    if ($LASTEXITCODE -eq 0 -and ($pyOut -join '') -match 'ok') { $alembicOk = $true }
} finally {
    $env:PYTHONPATH = $prev
}
Write-Check 'backend_sqlalchemy_ok' $alembicOk

if (-not $alembicOk) {
    Write-Host "[DB_CHECK] backend_error=$($pyOut -join ' ')" -ForegroundColor Red
}

Write-Host ''
Write-Host 'DBeaver (workbench):' -ForegroundColor Cyan
Write-Host "  Host=$($cfg.DbHost) Port=$($cfg.Port) Database=$($cfg.WorkbenchDatabase) Username=$($cfg.User) Password=(same as backend/.env POSTGRES_PASSWORD or DATABASE_URL)"
Write-Host '  Maintenance DB for first connect: postgres'

if ($tcpOk -and $loginOk -and $dbExists -and $alembicOk) {
    Write-Host '[DB_CHECK] ALL_OK=true' -ForegroundColor Green
    exit 0
}
exit 1
