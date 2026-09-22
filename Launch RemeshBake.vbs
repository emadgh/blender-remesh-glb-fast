Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptPath = fso.GetParentFolderName(WScript.ScriptFullName) & "\RemeshBake.ps1"
shell.Run "powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptPath & """", 0, False
