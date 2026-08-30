; Inno Setup 6 script — per-user Windows installer for AssetManager.
;
; Why per-user (PrivilegesRequired=lowest): the app writes its RuntimeData
; directory NEXT TO the executable (see AssetsManager/core/path_resolver.py),
; so installing into %LOCALAPPDATA%\Programs keeps every write inside the
; user profile — no UAC prompt, no Program Files ACL wall.
;
; Version discipline: constants.py (AssetsManager/core/constants.py) is the
; single source of truth. scripts/build_installer.py reads APP_VERSION from
; there and stamps installer/_version.iss, which is #included below. Do NOT
; hardcode a version in this file.
;
; Package contents: the full PyInstaller onedir output (dist/AssetManager),
; built beforehand via `pyinstaller AssetManager.spec`.

#define MyAppName "AssetManager"
#define MyAppExeName "AssetManager.exe"
#define MyAppPublisher "AssetManager"
#include "_version.iss"

[Setup]
; Fixed GUID: changing it makes Windows treat an update as a different app.
; The doubled {{ is the documented escape for a literal leading brace.
AppId={{55D9C16C-7359-425E-ACAB-2445E0B08BAC}
AppName={#MyAppName}
AppVersion={#APP_VERSION}
AppVerName={#MyAppName} {#APP_VERSION}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
; Per-user install: no admin rights, no HKLM writes, no Program Files ACLs.
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
; Installer/shortcut icon (tracked canonical source, same as the exe icon).
SetupIconFile=..\Assets\icons\icon.ico
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist\installer
OutputBaseFilename=AssetManager-{#APP_VERSION}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; ChineseSimplified.isl ships with the unofficial-translations pack only, not
; the stock Inno Setup 6 install (nor the choco innosetup package). Stamped
; in only when the file exists next to the compiler; otherwise English-only.
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif

[Tasks]
; Desktop shortcut is opt-in (task unchecked); the Start Menu shortcut is
; always created via [Icons] below.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Full onedir bundle — everything PyInstaller collected, preserving the
; _internal layout of PyInstaller 6.
Source: "..\dist\AssetManager\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Nothing — no services/tasks to stop.

; NOTE: no [UninstallDelete] on purpose. RuntimeData lives in {app} next to
; the exe; the uninstaller must not wipe user data, so leftover runtime
; files stay until the user removes the folder themselves.
