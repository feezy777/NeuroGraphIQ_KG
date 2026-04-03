$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$targetVbs = Join-Path $projectRoot "start_workbench_silent.vbs"
$wscript = Join-Path $env:SystemRoot "System32\wscript.exe"

if (-not (Test-Path $targetVbs)) {
    throw "start_workbench_silent.vbs not found at $targetVbs"
}

if (-not (Test-Path $wscript)) {
    throw "wscript.exe not found at $wscript"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "NeuroKG Workbench.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = "`"$targetVbs`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Start or open NeuroKG Workbench (silent)"
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
$shortcut.Save()

Write-Host "Shortcut created:" $shortcutPath
