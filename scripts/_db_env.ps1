# Shared: load PostgreSQL connection parameters from backend/.env (no secrets in repo).
# Usage: . "$PSScriptRoot\_db_env.ps1"

function Get-DbEnvPath {
    $root = Split-Path -Parent $PSScriptRoot
    Join-Path $root 'backend\.env'
}

function Read-DbEnvFile {
    param([string]$Path = (Get-DbEnvPath))
    $vars = @{}
    if (-not (Test-Path $Path)) {
        return $vars
    }
    foreach ($line in Get-Content $Path -Encoding UTF8) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        if ($t -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $vars[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
    return $vars
}

function Parse-DatabaseUrl {
    param([string]$Url)
    if (-not $Url) { return $null }
    $u = $Url -replace '^postgresql\+[^:/]+', 'postgresql'
    if ($u -notmatch '^postgresql://([^@]+)@([^:/]+)(?::(\d+))?/([^?]+)') {
        return $null
    }
    $userPart = $Matches[1]
    $dbHost = $Matches[2]
    $port = if ($Matches[3]) { [int]$Matches[3] } else { 5432 }
    $db = $Matches[4]
    $user = $userPart
    $pass = ''
    if ($userPart -match '^([^:]+):(.+)$') {
        $user = $Matches[1]
        $pass = [uri]::UnescapeDataString($Matches[2])
    }
    return [pscustomobject]@{
        User     = $user
        Password = $pass
        DbHost   = $dbHost
        Port     = $port
        Database = $db
    }
}

function Get-ProjectDbConfig {
  <#
    Resolves connection params: POSTGRES_* in .env > DATABASE_URL > defaults.
    Does not print passwords.
  #>
    $envFile = Read-DbEnvFile
    $dbHost = if ($envFile['POSTGRES_HOST']) { $envFile['POSTGRES_HOST'] } else { '127.0.0.1' }
    $port = if ($envFile['POSTGRES_PORT']) { [int]$envFile['POSTGRES_PORT'] } else { 5432 }
    $user = if ($envFile['POSTGRES_USER']) { $envFile['POSTGRES_USER'] } else { 'postgres' }
    $pass = if ($null -ne $envFile['POSTGRES_PASSWORD']) { $envFile['POSTGRES_PASSWORD'] } else { '' }
    $wbDb = if ($envFile['POSTGRES_DB']) { $envFile['POSTGRES_DB'] } else { 'neurographiq_kg_v3_wb' }
    $candDb = if ($envFile['POSTGRES_DB_CANDIDATE']) { $envFile['POSTGRES_DB_CANDIDATE'] } else { 'neurographiq_kg_v3_candidate' }

    if ($envFile['DATABASE_URL']) {
        $parsed = Parse-DatabaseUrl $envFile['DATABASE_URL']
        if ($parsed) {
            if (-not $envFile['POSTGRES_HOST']) { $dbHost = $parsed.DbHost }
            if (-not $envFile['POSTGRES_PORT']) { $port = $parsed.Port }
            if (-not $envFile['POSTGRES_USER']) { $user = $parsed.User }
            if (-not $envFile['POSTGRES_PASSWORD'] -and $parsed.Password) { $pass = $parsed.Password }
            if (-not $envFile['POSTGRES_DB']) { $wbDb = $parsed.Database }
        }
    }

    if (-not $pass -and $env:PGPASSWORD) { $pass = $env:PGPASSWORD }

    return [pscustomobject]@{
        DbHost             = $dbHost
        Port               = $port
        User               = $user
        Password           = $pass
        WorkbenchDatabase  = $wbDb
        CandidateDatabase  = $candDb
        EnvFile            = (Get-DbEnvPath)
        EnvFileExists      = (Test-Path (Get-DbEnvPath))
    }
}

function Get-PsqlExecutable {
    $psqlExe = $env:PSQL_EXE
    if ($psqlExe -and (Test-Path $psqlExe)) { return $psqlExe }
    $candidate = 'D:\Tool\Coding\Database\PostgreSQL\bin\psql.exe'
    if (Test-Path $candidate) { return $candidate }
    return 'psql.exe'
}
