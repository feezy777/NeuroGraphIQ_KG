# Quick PC network / proxy status check (read-only)
$ErrorActionPreference = 'SilentlyContinue'

Write-Host "=== Active WiFi ===" -ForegroundColor Cyan
Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias WLAN |
  Select-Object IPAddress, PrefixLength | Format-Table -AutoSize

Write-Host "=== System Proxy ===" -ForegroundColor Cyan
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
  Select-Object ProxyEnable, ProxyServer, ProxyOverride | Format-List

Write-Host "=== Clash Processes ===" -ForegroundColor Cyan
Get-Process verge-mihomo, clash-win64, clash-verge -ErrorAction SilentlyContinue |
  Select-Object ProcessName, Id | Format-Table -AutoSize

Write-Host "=== Proxy Ports ===" -ForegroundColor Cyan
7890, 7897 | ForEach-Object {
  $ok = (Test-NetConnection 127.0.0.1 -Port $_ -WarningAction SilentlyContinue).TcpTestSucceeded
  Write-Host "127.0.0.1:$_ -> $ok"
}

Write-Host "=== Gateway Ping (5) ===" -ForegroundColor Cyan
$gw = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Where-Object RouteMetric -gt 0 | Sort-Object RouteMetric | Select-Object -First 1).NextHop
if ($gw) { ping -n 5 $gw } else { Write-Host 'No default gateway' }

Write-Host "=== 802.1x events (last 5 min) ===" -ForegroundColor Cyan
$since = (Get-Date).AddMinutes(-5)
Get-WinEvent -FilterHashtable @{
  LogName = 'Microsoft-Windows-WLAN-AutoConfig/Operational'
  StartTime = $since
} -MaxEvents 50 |
  Where-Object { $_.Id -in 11004, 11005, 11010 } |
  Select-Object -First 10 TimeCreated, Id |
  Format-Table -AutoSize
