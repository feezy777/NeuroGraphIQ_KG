Option Explicit

Dim shell, fso, scriptDir, batPath
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = Chr(34) & fso.BuildPath(scriptDir, "start_workbench.bat") & Chr(34)

shell.CurrentDirectory = scriptDir
' Hidden launch. start_workbench.bat now handles "already running" detection.
shell.Run batPath, 0, False
