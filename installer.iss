; Inno Setup script for Claude Usage Widget
; Compile with Inno Setup Compiler (https://jrsoftware.org/isinfo.php)

[Setup]
AppName=Claude Usage Widget
AppVersion=1.0
AppPublisher=HamzaAmjad-RG
AppPublisherURL=https://github.com/HamzaAmjad-RG/claude-usage-widget-windows
DefaultDirName={autopf}\ClaudeUsageWidget
DefaultGroupName=Claude Usage Widget
OutputBaseFilename=ClaudeUsageWidgetSetup
SetupIconFile=new_icon.ico
UninstallDisplayIcon={app}\ClaudeUsageWidget.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern

[Files]
Source: "dist\ClaudeUsageWidget.exe"; DestDir: "{app}"; Flags: ignoreversion
; The app will create an empty curl.txt on first run if missing.
; Do NOT bundle the project's curl.txt — it may contain user credentials.

[Icons]
Name: "{group}\Claude Usage Widget"; Filename: "{app}\ClaudeUsageWidget.exe"
Name: "{group}\Uninstall Claude Usage Widget"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Claude Usage Widget"; Filename: "{app}\ClaudeUsageWidget.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "autostart"; Description: "Start automatically when Windows starts"; GroupDescription: "Startup:"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ClaudeUsageWidget"; ValueData: """{app}\ClaudeUsageWidget.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[InstallDelete]
; Remove leftover curl.txt from previous installs (may contain credentials)
Type: files; Name: "{app}\curl.txt"

[Run]
Filename: "{app}\ClaudeUsageWidget.exe"; Description: "Launch Claude Usage Widget"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up runtime files not installed by the installer
Type: files; Name: "{app}\curl.txt"
Type: files; Name: "{app}\notification_state.json"
Type: files; Name: "{app}\widget_state.json"

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // Kill running instance before installing/upgrading
  Exec('taskkill', '/F /IM ClaudeUsageWidget.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  // Kill running instance before uninstalling
  Exec('taskkill', '/F /IM ClaudeUsageWidget.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;
