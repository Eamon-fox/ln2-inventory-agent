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
SetupIconFile=..\..\installer\windows\icon.ico
LicenseFile=..\..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.LanguageLabel=Language:
english.ThemeLabel=Theme:
english.English=English
english.Chinese=中文 (简体)
english.Light=浅色
english.Dark=深色

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\installer\windows\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Code]
var
  LanguagePage: TWizardPage;
  LanguageCombo: TComboBox;
  LanguageLabel: TLabel;
  ThemePage: TWizardPage;
  ThemeCombo: TComboBox;
  ThemeLabel: TLabel;

procedure InitializeWizard;
var
  ConfigDir: string;
begin
  ConfigDir := ExpandConstant('{userappdata}\ln2agent');

  LanguagePage := CreateCustomPage(wpSelectDir, 'Language', 'Select your preferred language');
  
  LanguageLabel := TLabel.Create(LanguagePage);
  LanguageLabel.Parent := LanguagePage.Surface;
  LanguageLabel.Caption := 'Language:';
  LanguageLabel.Left := 0;
  LanguageLabel.Top := 10;

  LanguageCombo := TComboBox.Create(LanguagePage);
  LanguageCombo.Parent := LanguagePage.Surface;
  LanguageCombo.Left := 0;
  LanguageCombo.Top := 35;
  LanguageCombo.Width := 200;
  LanguageCombo.Items.Add('English');
  LanguageCombo.Items.Add('中文 (简体)');
  LanguageCombo.ItemIndex := 1;

  ThemePage := CreateCustomPage(LanguagePage.ID, 'Theme', 'Select your preferred theme');
  
  ThemeLabel := TLabel.Create(ThemePage);
  ThemeLabel.Parent := ThemePage.Surface;
  ThemeLabel.Caption := 'Theme:';
  ThemeLabel.Left := 0;
  ThemeLabel.Top := 10;

  ThemeCombo := TComboBox.Create(ThemePage);
  ThemeCombo.Parent := ThemePage.Surface;
  ThemeCombo.Left := 0;
  ThemeCombo.Top := 35;
  ThemeCombo.Width := 200;
  ThemeCombo.Items.Add('浅色 (Light)');
  ThemeCombo.Items.Add('深色 (Dark)');
  ThemeCombo.ItemIndex := 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigFile: string;
  ConfigDir: string;
  LangCode: string;
  ThemeCode: string;
  StringList: TStringList;
begin
  if CurStep = ssPostInstall then
  begin
    ConfigDir := ExpandConstant('{userappdata}\ln2agent');
    ForceDirectories(ConfigDir);
    ConfigFile := ConfigDir + '\config.yaml';

    if LanguageCombo.ItemIndex = 0 then
      LangCode := 'en'
    else
      LangCode := 'zh-CN';

    if ThemeCombo.ItemIndex = 0 then
      ThemeCode := 'light'
    else
      ThemeCode := 'dark';

    StringList := TStringList.Create;
    try
      StringList.Add('yaml_path:');
      StringList.Add('api_keys: {}');
      StringList.Add('language: "' + LangCode + '"');
      StringList.Add('theme: "' + ThemeCode + '"');
      StringList.Add('last_notified_release: "0.0.0"');
      StringList.Add('release_notes_preview: ""');
      StringList.Add('import_prompt_seen: false');
      StringList.Add('ai:');
      StringList.Add('  provider: deepseek');
      StringList.Add('  model: null');
      StringList.Add('  max_steps: 12');
      StringList.Add('  thinking_enabled: true');
      StringList.Add('  custom_prompt: ""');
      StringList.SaveToFile(ConfigFile);
    finally
      StringList.Free;
    end;
  end;
end;

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
