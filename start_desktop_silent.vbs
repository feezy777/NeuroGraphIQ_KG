Option Explicit

Dim shell, fso, scriptDir, batPath
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = Chr(34) & fso.BuildPath(scriptDir, "start_desktop.bat") & Chr(34)

shell.CurrentDirectory = scriptDir
shell.Run batPath, 0, False
