$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$targetVbs = Join-Path $projectRoot "start_desktop_silent.vbs"
$wscript = Join-Path $env:SystemRoot "System32\wscript.exe"

if (-not (Test-Path $targetVbs)) {
    throw "start_desktop_silent.vbs not found at $targetVbs"
}

if (-not (Test-Path $wscript)) {
    throw "wscript.exe not found at $wscript"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "NeuroKG Desktop V3.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = "`"$targetVbs`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Start NeuroKG Desktop V3 (silent)"
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
$shortcut.Save()

Write-Host "Shortcut created:" $shortcutPath
