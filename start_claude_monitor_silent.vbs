' Claude Usage Monitor - Silent Startup Script
' This VBScript runs the Python app without showing a console window

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "python claude_usage_menubar.py", 0, False
Set WshShell = Nothing
