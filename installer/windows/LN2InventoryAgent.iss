; Inno Setup script for LN2 Inventory Agent.
; Build prerequisite: pyinstaller ln2_inventory.spec

#define MyAppName "LN2 Inventory Agent"
#define MyAppPublisher "EamonFox"
#define MyAppExeName "LN2InventoryAgent.exe"

#define MyAppVersion GetEnv("LN2_AGENT_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "0.1.0"
#endif

#define SourceDir "..\\..\\dist\\LN2InventoryAgent"

#if !DirExists(SourceDir)
  #error "Missing dist/LN2InventoryAgent. Build it first with: pyinstaller ln2_inventory.spec"
#endif

#if !FileExists(SourceDir + "\\" + MyAppExeName)
  #error "Missing LN2InventoryAgent.exe under dist/LN2InventoryAgent."
#endif

[Setup]
AppId={{7C2D9B8B-A08F-4C69-A8E7-2A04A3010049}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=LN2InventoryAgent-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
