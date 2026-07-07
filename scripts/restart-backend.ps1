# NeuroGraphIQ KG V3 — restart FastAPI backend (port 8002)
# Invoked from dashboard or manually. Waits briefly so the API response can return first.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
Set-Location $BackendDir

Start-Sleep -Seconds 2

$port = 8002
$projectBackend = [regex]::Escape($BackendDir).Replace('\\', '[\\/]')
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $cmd = $_.CommandLine
        $cmd -and (
            $cmd -match "$projectBackend.*run_server\.py" -or
            $cmd -match "$projectBackend.*uvicorn"
        )
    } |
    ForEach-Object {
        Write-Host "Stopping backend PID $($_.ProcessId)..." -ForegroundColor Yellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
foreach ($cleanupPort in @($port, 8001)) {
    $pids = netstat -ano | Select-String ":$cleanupPort\s" | ForEach-Object {
        ($_.Line -split '\s+')[-1]
    } | Sort-Object -Unique
    foreach ($procId in $pids) {
        if ($procId -match '^\d+$' -and (Get-Process -Id $procId -ErrorAction SilentlyContinue)) {
            Write-Host "Stopping PID $procId on port $cleanupPort..." -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}
Start-Sleep -Seconds 2

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "Missing backend venv. Run scripts/start-backend.ps1 first."
}

Write-Host "Starting API: http://127.0.0.1:8002" -ForegroundColor Green
Start-Process `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "run_server.py" `
    -WorkingDirectory $BackendDir `
    -WindowStyle Hidden
