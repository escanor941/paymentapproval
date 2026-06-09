[Setup]
AppName=EMD Factory Panel
AppVersion=1.0.0
AppPublisher=EMD Group
AppPublisherURL=https://emdgroup.com
AppSupportURL=https://emdgroup.com/support
AppUpdatesURL=https://emdgroup.com/updates
DefaultDirName={pf}\EMD\FactoryPanel
DefaultGroupName=EMD Group
AllowNoIcons=yes
OutputDir=installers
OutputBaseFilename=EMDFactoryPanel_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\EMDFactoryPanel.exe
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
Source: "dist\EMDFactoryPanel.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "readme.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\EMD Factory Panel"; Filename: "{app}\EMDFactoryPanel.exe"
Name: "{group}\Uninstall EMD Factory Panel"; Filename: "{uninstallexe}"
Name: "{autodesktop}\EMD Factory Panel"; Filename: "{app}\EMDFactoryPanel.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\EMDFactoryPanel.exe"; Description: "Launch EMD Factory Panel"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCR; Subkey: ".emdfactory"; ValueType: string; ValueName: ""; ValueData: "EMDFactoryPanelFile"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "EMDFactoryPanelFile"; ValueType: string; ValueName: ""; ValueData: "EMD Factory Panel File"; Flags: uninsdeletekey
Root: HKCR; Subkey: "EMDFactoryPanelFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\EMDFactoryPanel.exe,0"
Root: HKCR; Subkey: "EMDFactoryPanelFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\EMDFactoryPanel.exe"" ""%1"""
