# Create an empty Postgres database for the KG workbench DDL and apply init_schema.sql.
# Use when DATABASE_URL pointed at another project DB (tables like file_registry missing → API 500).
# Optional: set PSQL_EXE to psql.exe full path if not on PATH.

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_db_env.ps1"
$cfg = Get-ProjectDbConfig
$Root = Split-Path -Parent $PSScriptRoot
$Schema = Join-Path $Root 'backend\migrations\init_schema.sql'
$DbLower = $cfg.WorkbenchDatabase
$env:PGPASSWORD = $cfg.Password
$psqlExe = Get-PsqlExecutable

$exists = (& $psqlExe -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DbLower'" 2>$null).Trim()
if ($exists -ne '1') {
    Write-Host "Creating database $DbLower ..." -ForegroundColor Green
    & $psqlExe -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DbLower;"
} else {
    Write-Host "Database $DbLower already exists." -ForegroundColor DarkGray
}

Write-Host "Applying schema: $Schema" -ForegroundColor Green
& $psqlExe -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d $DbLower -v ON_ERROR_STOP=1 -f $Schema

Write-Host ''
Write-Host "backend/.env should use host=$($cfg.DbHost) port=$($cfg.Port) db=$DbLower user=$($cfg.User)" -ForegroundColor Cyan
Write-Host 'See docs/dbeaver_postgres_connection.md' -ForegroundColor Cyan
