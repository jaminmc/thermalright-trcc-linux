; TRCC Windows Installer — Inno Setup Script
; Built by GitHub Actions, not manually.
;
; Receives APP_VERSION via /D flag from CI:
;   iscc /DAPP_VERSION=8.3.10 trcc.iss

#ifndef APP_VERSION
  #define APP_VERSION "0.0.0"
#endif

[Setup]
AppId={{F7A3C2E1-8B4D-4F9A-B6E2-1D3C5A7F8E90}
AppName=TRCC
AppVersion={#APP_VERSION}
AppVerName=TRCC {#APP_VERSION}
AppPublisher=TRCC Linux Contributors
AppPublisherURL=https://github.com/Lexonight1/thermalright-trcc-linux
AppSupportURL=https://github.com/Lexonight1/thermalright-trcc-linux/issues
DefaultDirName={autopf}\TRCC
DefaultGroupName=TRCC
OutputDir=Output
OutputBaseFilename=trcc-{#APP_VERSION}-setup
SetupIconFile=..\src\trcc\assets\icons\app.ico
UninstallDisplayIcon={app}\trcc-gui.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=admin
LicenseFile=..\LICENSE
; Upgrade: detect running TRCC and offer to close it
CloseApplications=yes
CloseApplicationsFilter=trcc*.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Clean stale PyInstaller files from previous version before installing new ones
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\trcc.exe"
Type: files; Name: "{app}\trcc-gui.exe"

[Files]
; PyInstaller output directory (all DLLs, Python runtime, Qt, app code)
Source: "..\dist\trcc\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; WinUSB driver .inf kept for reference — not auto-installed (requires signed cert)
; Users needing WinUSB (bulk/HID devices) are guided to Zadig via `trcc doctor`
Source: "trcc-usb.inf"; DestDir: "{app}\driver"; Flags: ignoreversion

[Icons]
Name: "{group}\TRCC"; Filename: "{app}\trcc-gui.exe"; Comment: "Thermalright LCD Control Center"
Name: "{group}\TRCC (CLI)"; Filename: "{app}\trcc.exe"; Comment: "TRCC Command Line"
Name: "{group}\{cm:UninstallProgram,TRCC}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\TRCC"; Filename: "{app}\trcc-gui.exe"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\TRCC"; Filename: "{app}\trcc-gui.exe"; Tasks: quicklaunchicon

[Run]
; WinUSB driver not auto-installed (requires signed certificate).
; Users with bulk/HID devices are guided to Zadig via `trcc doctor`.
Filename: "{app}\trcc-gui.exe"; Description: "{cm:LaunchProgram,TRCC}"; Flags: nowait postinstall skipifsilent

[Registry]
; Add trcc CLI to PATH
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Check: NeedsAddPath('{app}')

[UninstallDelete]
; Clean up autostart entry and app directory
Type: files; Name: "{userappdata}\Microsoft\Windows\Start Menu\Programs\Startup\trcc-linux.desktop"
Type: files; Name: "{userstartup}\trcc-linux.desktop"
Type: filesandordirs; Name: "{app}"

[UninstallRun]
; Kill TRCC processes before uninstall
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM trcc-gui.exe"; Flags: runhidden; RunOnceId: "KillGUI"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM trcc.exe"; Flags: runhidden; RunOnceId: "KillCLI"

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + UpperCase(Param) + ';', ';' + UpperCase(OrigPath) + ';') = 0;
end;
