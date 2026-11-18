#ifndef MyAppVersion
  #define MyAppVersion "1.0.1"
#endif
#define MyAppName "Blockys"
#define MyAppPublisher "Blockys"
#define MyAppExeName "Blockys.exe"
#define MyAppId "{{F935545A-3ECD-4141-9A45-12DEF218A593}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Blockys
DefaultGroupName=Blockys
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x86compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Blockys-Setup-{#MyAppVersion}
SetupIconFile=..\bloque\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes
MinVersion=10.0
VersionInfoVersion=1.0.1.0
VersionInfoProductVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Instalador de Blockys

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "..\dist\Blockys\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: IsWin64
Source: "..\dist\Blockys32\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: not IsWin64
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Blockys"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\Blockys"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Blockys"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    MsgBox('Tus cuentas, instancias y mundos se conservaron en:' + #13#10 +
           ExpandConstant('{userappdata}\BloqueLauncher'), mbInformation, MB_OK);
end;
