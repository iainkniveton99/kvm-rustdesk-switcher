Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' If running from Startup folder, use the install directory instead
If InStr(LCase(scriptDir), "startup") > 0 Then
    ' Try common install locations - edit this path to match your setup
    If fso.FileExists("C:\kvm-switcher\kvm_listener.py") Then
        scriptDir = "C:\kvm-switcher"
    End If
End If

WshShell.Run "pythonw """ & scriptDir & "\kvm_listener.py""", 0, False
