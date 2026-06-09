[Setup]
AppName=EMD Admin Panel
AppVersion=1.0.0
AppPublisher=EMD Group
AppPublisherURL=https://emdgroup.com
AppSupportURL=https://emdgroup.com/support
AppUpdatesURL=https://emdgroup.com/updates
DefaultDirName={pf}\EMD\AdminPanel
DefaultGroupName=EMD Group
AllowNoIcons=yes
OutputDir=installers
OutputBaseFilename=EMDAdminPanel_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\EMDAdminPanel.exe
ChangesAssociations=yes
CreateAppDir=yes
DisableDirPage=no
DisableProgramGroupPage=no
LicenseFile=license.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "dist\EMDAdminPanel.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "readme.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\EMD Admin Panel"; Filename: "{app}\EMDAdminPanel.exe"
Name: "{group}\Uninstall EMD Admin Panel"; Filename: "{uninstallexe}"
Name: "{autodesktop}\EMD Admin Panel"; Filename: "{app}\EMDAdminPanel.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\EMDAdminPanel.exe"; Description: "Launch EMD Admin Panel"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCR; Subkey: ".emdadmin"; ValueType: string; ValueName: ""; ValueData: "EMDAdminPanelFile"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "EMDAdminPanelFile"; ValueType: string; ValueName: ""; ValueData: "EMD Admin Panel File"; Flags: uninsdeletekey
Root: HKCR; Subkey: "EMDAdminPanelFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\EMDAdminPanel.exe,0"
Root: HKCR; Subkey: "EMDAdminPanelFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\EMDAdminPanel.exe"" ""%1"""
