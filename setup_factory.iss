; ============================================================
;  EMD Factory Panel — Inno Setup Installer Script
;  Build with: ISCC.exe setup_factory.iss
;  Requires Inno Setup 6: https://jrsoftware.org/isdl.php
; ============================================================

[Setup]
AppName=EMD Factory Panel
AppVersion=1.1
AppVerName=EMD Factory Panel v1.1
AppPublisher=EMD Group
AppPublisherURL=https://paymentapproval.onrender.com
AppSupportURL=https://paymentapproval.onrender.com
AppUpdatesURL=https://paymentapproval.onrender.com

; Installation directory
DefaultDirName={autopf}\EMD Group\Factory Panel
DefaultGroupName=EMD Group
DisableProgramGroupPage=no

; Output
OutputDir=installer
OutputBaseFilename=EMDFactoryPanel_Setup_v1.1
SetupIconFile=

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
InternalCompressLevel=ultra64

; UI
WizardStyle=modern
DisableWelcomePage=no

; Privileges — install for all users in Program Files
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; Uninstaller
UninstallDisplayName=EMD Factory Panel
UninstallDisplayIcon={app}\EMDFactoryPanel.exe
CreateUninstallRegKey=yes

; Misc
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; \
  Description: "Create a &Desktop shortcut"; \
  GroupDescription: "Additional shortcuts:"
Name: "startupicon"; \
  Description: "Launch EMD Factory Panel at &Windows startup"; \
  GroupDescription: "Additional shortcuts:"; \
  Flags: unchecked

[Files]
; Main executable — built by PyInstaller
Source: "dist\EMDFactoryPanel.exe"; \
  DestDir: "{app}"; \
  DestName: "EMDFactoryPanel.exe"; \
  Flags: ignoreversion

[Icons]
; Start Menu
Name: "{group}\EMD Factory Panel";             Filename: "{app}\EMDFactoryPanel.exe"
Name: "{group}\Uninstall EMD Factory Panel";   Filename: "{uninstallexe}"

; Desktop
Name: "{commondesktop}\EMD Factory Panel"; \
  Filename: "{app}\EMDFactoryPanel.exe"; \
  Tasks: desktopicon

[Registry]
; Startup entry (optional task)
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "EMDFactoryPanel"; \
  ValueData: """{app}\EMDFactoryPanel.exe"""; \
  Flags: uninsdeletevalue; \
  Tasks: startupicon

[Run]
; Offer to launch after install
Filename: "{app}\EMDFactoryPanel.exe"; \
  Description: "Launch EMD Factory Panel now"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Nothing extra needed — PyInstaller EXE is self-contained

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nEMD Group — Factory Purchase Request System%nCreated by Daniyal%n%nClick Next to continue.