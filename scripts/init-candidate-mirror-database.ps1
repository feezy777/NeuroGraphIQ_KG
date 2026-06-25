# Create candidate mirror DB (same DDL as workbench: staging + kg_* + registry).
# Phase-1 AAL3 scripts write here via CANDIDATE_DATABASE_URL / --db-url.

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_db_env.ps1"
$cfg = Get-ProjectDbConfig
$Root = Split-Path -Parent $PSScriptRoot
$Schema = Join-Path $Root 'backend\migrations\init_schema.sql'
$DbLower = $cfg.CandidateDatabase
$env:PGPASSWORD = $cfg.Password
$psqlExe = Get-PsqlExecutable

$existsRaw = & $psqlExe -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DbLower'" 2>$null
$exists = if ($null -eq $existsRaw) { '' } else { "$existsRaw".Trim() }
if ($exists -ne '1') {
    Write-Host "Creating database $DbLower ..." -ForegroundColor Green
    & $psqlExe -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DbLower;"
} else {
    Write-Host "Database $DbLower already exists." -ForegroundColor DarkGray
}

Write-Host "Applying schema: $Schema" -ForegroundColor Green
& $psqlExe -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d $DbLower -v ON_ERROR_STOP=1 -f $Schema

Write-Host ''
Write-Host "backend/.env CANDIDATE_DATABASE_URL -> host=$($cfg.DbHost) port=$($cfg.Port) db=$DbLower" -ForegroundColor Cyan
Write-Host 'See docs/dbeaver_postgres_connection.md' -ForegroundColor Cyan
