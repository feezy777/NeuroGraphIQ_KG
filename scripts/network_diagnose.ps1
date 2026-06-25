# Network diagnostics — read-only, safe for campus/dev environments.
# Usage: .\scripts\network_diagnose.ps1

$ErrorActionPreference = 'Continue'

Write-Host "========== NeuroGraphIQ Network Diagnose ==========" -ForegroundColor Cyan

Write-Host "`n[1] System proxy env vars"
Get-ChildItem Env: | Where-Object { $_.Name -match 'PROXY|proxy' } | Format-Table Name, Value -AutoSize
if (-not (Get-ChildItem Env: | Where-Object { $_.Name -match 'PROXY' })) {
    Write-Host "  (none set)"
}

Write-Host "`n[2] Windows proxy (WinHTTP + user)"
try { netsh winhttp show proxy } catch { Write-Host "  winhttp: unavailable" }
$ie = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
if ($ie) {
    Write-Host "  ProxyEnable=$($ie.ProxyEnable) ProxyServer=$($ie.ProxyServer) AutoConfigURL=$($ie.AutoConfigURL)"
}

Write-Host "`n[3] Clash/VPN local port 7897"
$clash = Test-NetConnection 127.0.0.1 -Port 7897 -WarningAction SilentlyContinue
Write-Host "  127.0.0.1:7897 open=$($clash.TcpTestSucceeded)"

Write-Host "`n[4] Package manager proxy/registry"
Write-Host "  npm registry=$(npm config get registry 2>$null)"
Write-Host "  npm proxy=$(npm config get proxy 2>$null)"
Write-Host "  git http.proxy=$(git config --global --get http.proxy 2>$null)"
Write-Host "  git https.proxy=$(git config --global --get https.proxy 2>$null)"

Write-Host "`n[5] DNS resolve timing (ms)"
$hosts = @('registry.npmjs.org', 'pypi.org', 'github.com', 'api.deepseek.com')
foreach ($h in $hosts) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Resolve-DnsName $h -ErrorAction Stop | Select-Object -First 1
        $sw.Stop()
        Write-Host ("  {0,4} ms  {1} -> {2}" -f $sw.ElapsedMilliseconds, $h, ($r.IPAddress -join ','))
    } catch {
        $sw.Stop()
        Write-Host ("  {0,4} ms  {1} FAIL" -f $sw.ElapsedMilliseconds, $h)
    }
}

Write-Host "`n[6] HTTP latency"
foreach ($url in @(
        'https://registry.npmjs.org/',
        'https://pypi.org/simple/',
        'http://127.0.0.1:8002/api/health'
    )) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10 -Method Head
        $sw.Stop()
        Write-Host ("  {0,4} ms  {1} status={2}" -f $sw.ElapsedMilliseconds, $url, $r.StatusCode)
    } catch {
        $sw.Stop()
        Write-Host ("  {0,4} ms  {1} err={2}" -f $sw.ElapsedMilliseconds, $url, $_.Exception.Message)
    }
}

Write-Host "`n[7] Backend ports 8000/8001/8002"
foreach ($p in 8000, 8001, 8002) {
    $ok = (Test-NetConnection 127.0.0.1 -Port $p -WarningAction SilentlyContinue).TcpTestSucceeded
    Write-Host "  port $p open=$ok"
}

Write-Host "`n[8] Project DB check (optional)"
if (Test-Path "$PSScriptRoot\db_check_connection.ps1") {
    & "$PSScriptRoot\db_check_connection.ps1" 2>$null
}

Write-Host "`nDone. See docs/network_troubleshooting.md for fixes." -ForegroundColor Green
