' MathViz launcher - starts the GUI without any console window.
' Double-click this file (keep it ASCII-only: wscript reads .vbs as ANSI).
Option Explicit

Dim fso, sh, here, pyw, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
pyw  = here & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pyw) Then
    MsgBox "pythonw.exe not found:" & vbCrLf & pyw & vbCrLf & vbCrLf & _
           "Create the venv first:" & vbCrLf & _
           "    uv venv --python 3.12 .venv" & vbCrLf & _
           "    uv pip install --python .venv\Scripts\python.exe -r requirements.txt", _
           16, "MathViz"
    WScript.Quit 1
End If

' pythonw.exe attaches no console, so nothing pops up.
' Style 1 (normal) instead of 0 (hidden): some shells pass the hidden state on
' to the child, and then even the GUI window stays invisible.
cmd = """" & pyw & """ -m app.main"
sh.CurrentDirectory = here
sh.Run cmd, 1, False
