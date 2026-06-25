# Reset local dev postgres user password and ensure project databases exist.
# Safe for development; does not drop volumes unless you use -RecreateDockerVolume (dangerous).
#
# Usage:
#   .\scripts\db_fix_postgres_password.ps1
#   .\scripts\db_fix_postgres_password.ps1 -NewPassword postgres
#   .\scripts\db_fix_postgres_password.ps1 -UseDocker

param(
    [string]$NewPassword = 'postgres',
    [switch]$UseDocker,
    [switch]$RecreateDockerVolume
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_db_env.ps1"

$cfg = Get-ProjectDbConfig
$psql = Get-PsqlExecutable
$root = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $root 'docker-compose.yml'

function Invoke-PsqlAdmin {
    param([string]$Sql, [string]$Db = 'postgres')
    if ($script:DockerMode) {
        docker compose -f $composeFile exec -T postgres psql -U postgres -d $Db -v ON_ERROR_STOP=1 -c $Sql
    } else {
        $env:PGPASSWORD = $script:AdminPassword
        & $psql -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d $Db -v ON_ERROR_STOP=1 -c $Sql
    }
}

$script:DockerMode = $false
$script:AdminPassword = $cfg.Password

if ($UseDocker -or (Test-Path $composeFile)) {
    $dockerOk = $null -ne (Get-Command docker -ErrorAction SilentlyContinue)
    if ($dockerOk) {
        Push-Location $root
        try {
            if ($RecreateDockerVolume) {
                Write-Host '[DB_FIX] WARNING: RecreateDockerVolume will DELETE docker postgres data.' -ForegroundColor Red
                docker compose down -v 2>$null
            }
            docker compose up -d postgres 2>&1 | Out-Host
            if ($LASTEXITCODE -eq 0) {
                $script:DockerMode = $true
                $cfg.Port = 5433
                Write-Host '[DB_FIX] Using Docker postgres on port 5433' -ForegroundColor Cyan
            }
        } finally {
            Pop-Location
        }
    }
}

if (-not $script:DockerMode) {
    Write-Host '[DB_FIX] Using host PostgreSQL (not Docker)' -ForegroundColor Cyan
    Write-Host "[DB_FIX] host=$($cfg.DbHost) port=$($cfg.Port) user=$($cfg.User)"
    # Try login with configured password first; if fails, prompt once
    $env:PGPASSWORD = $cfg.Password
    $test = & $psql -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d postgres -tAc 'SELECT 1' 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[DB_FIX] Current .env password did not work. Enter current postgres superuser password to run ALTER USER:' -ForegroundColor Yellow
        $sec = Read-Host 'Current postgres password' -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        $script:AdminPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        $env:PGPASSWORD = $script:AdminPassword
    }
}

Write-Host "[DB_FIX] Setting password for role $($cfg.User) ..."
Invoke-PsqlAdmin "ALTER USER $($cfg.User) WITH PASSWORD '$NewPassword';"

foreach ($dbName in @($cfg.WorkbenchDatabase, $cfg.CandidateDatabase)) {
    $exists = if ($script:DockerMode) {
        (docker compose -f $composeFile exec -T postgres psql -U postgres -d postgres -tAc `
            "SELECT 1 FROM pg_database WHERE datname='$dbName'" 2>$null).Trim()
    } else {
        (& $psql -h $cfg.DbHost -p $cfg.Port -U $cfg.User -d postgres -tAc `
            "SELECT 1 FROM pg_database WHERE datname='$dbName'" 2>$null).Trim()
    }
    if ($exists -ne '1') {
        Write-Host "[DB_FIX] Creating database $dbName ..."
        Invoke-PsqlAdmin "CREATE DATABASE $dbName;"
    } else {
        Write-Host "[DB_FIX] Database exists: $dbName"
    }
}

Write-Host ''
Write-Host 'Update backend/.env to match (example):' -ForegroundColor Green
Write-Host "  POSTGRES_PASSWORD=$NewPassword"
Write-Host "  DATABASE_URL=postgresql+psycopg_async://postgres:$NewPassword@$($cfg.DbHost):$($cfg.Port)/$($cfg.WorkbenchDatabase)"
Write-Host ''
Write-Host 'DBeaver connection:' -ForegroundColor Cyan
Write-Host "  Host=$($cfg.DbHost)  Port=$($cfg.Port)  Database=$($cfg.WorkbenchDatabase)  User=$($cfg.User)  Password=$NewPassword"
Write-Host '  (First-time test can use Database=postgres, then switch to workbench DB)'
