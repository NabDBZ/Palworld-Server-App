; Inno Setup script — builds a friendly setup.exe for Palworld Server Manager
; 1) install Inno Setup (https://jrsoftware.org/isinfo.php)
; 2) open this file, adjust #define RELEASEDIR if needed, press "Compile"
; The setup installs the MANAGER only — the Palworld server itself is
; installed separately (two SteamCMD commands, see docs/SETUP.md).

#define RELEASEDIR "."
#define APPVER "1.1"

[Setup]
AppName=Palworld Server Manager
AppVersion={#APPVER}
AppPublisher=Palworld Server Manager contributors
DefaultDirName={sd}\PalworldServer
DefaultGroupName=Palworld Server Manager
OutputBaseFilename=PalworldServerManager-{#APPVER}-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
SetupIconFile=app.ico
UninstallDisplayIcon={app}\PalworldControl.exe

[Files]
Source: "{#RELEASEDIR}\PalworldControl.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RELEASEDIR}\app\tools\*"; DestDir: "{app}\app\tools"; Flags: ignoreversion recursesubdirs
Source: "{#RELEASEDIR}\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs
Source: "{#RELEASEDIR}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RELEASEDIR}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Palworld Server Manager"; Filename: "{app}\PalworldControl.exe"
Name: "{autodesktop}\Palworld Server Manager"; Filename: "{app}\PalworldControl.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\PalworldControl.exe"; Description: "Launch Palworld Server Manager"; Flags: nowait postinstall skipifsilent
