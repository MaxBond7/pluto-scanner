Option Explicit
Dim fso, shell, baseDir, pythonw, script, extraArgs, i, q
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
q = Chr(34)

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = baseDir & "\.venv\Scripts\pythonw.exe"
script = baseDir & "\launch_pluto_scanner.py"

If Not fso.FileExists(pythonw) Then
    MsgBox "Python not found: " & pythonw, vbCritical, "Pluto Scanner"
    WScript.Quit 1
End If
If Not fso.FileExists(script) Then
    MsgBox "Launcher not found: " & script, vbCritical, "Pluto Scanner"
    WScript.Quit 1
End If

extraArgs = ""
For i = 0 To WScript.Arguments.Count - 1
    extraArgs = extraArgs & " " & q & Replace(WScript.Arguments(i), q, q & q) & q
Next

shell.CurrentDirectory = baseDir
shell.Run q & pythonw & q & " " & q & script & q & extraArgs, 0, False
