; ============================================================
;  EMD Group Combined Installer — Admin Panel & Factory Panel
;  Build with: ISCC.exe setup_combined.iss
;  Requires Inno Setup 6: https://jrsoftware.org/isdl.php
; ============================================================

[Setup]
AppName=EMD Group Panels
AppVersion=2.2
AppVerName=EMD Group Panels v2.2
AppPublisher=EMD Group
AppPublisherURL=https://factory-purchase-approval-production.up.railway.app
AppSupportURL=https://factory-purchase-approval-production.up.railway.app
AppUpdatesURL=https://factory-purchase-approval-production.up.railway.app

; Installation directory
DefaultDirName={autopf}\EMD Group
DefaultGroupName=EMD Group
DisableProgramGroupPage=no

; Output
OutputDir=installer
OutputBaseFilename=EMDGroup_Panels_Setup_v2.2
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
UninstallDisplayName=EMD Group Panels
UninstallDisplayIcon={app}\EMDAdminPanel.exe
CreateUninstallRegKey=yes

; Misc
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "full"; Description: "Full Installation"
Name: "admin"; Description: "Admin Panel Only"
Name: "factory"; Description: "Factory Panel Only"
Name: "custom"; Description: "Custom Installation"; Flags: iscustom

[Components]
Name: "admin"; Description: "Admin Panel (Purchase Approval Management)"; Types: full admin custom; Flags: fixed
Name: "factory"; Description: "Factory Panel (Purchase Request Submission)"; Types: full factory custom; Flags: fixed

[Tasks]
Name: "desktopicon_admin"; \
  Description: "Create a &Desktop shortcut for Admin Panel"; \
  GroupDescription: "Additional shortcuts:"; \
  Components: admin
Name: "desktopicon_factory"; \
  Description: "Create a &Desktop shortcut for Factory Panel"; \
  GroupDescription: "Additional shortcuts:"; \
  Components: factory
Name: "startupicon_admin"; \
  Description: "Launch Admin Panel at &Windows startup"; \
  GroupDescription: "Additional shortcuts:"; \
  Components: admin; Flags: unchecked
Name: "startupicon_factory"; \
  Description: "Launch Factory Panel at &Windows startup"; \
  GroupDescription: "Additional shortcuts:"; \
  Components: factory; Flags: unchecked

[Files]
; Admin Panel — built by PyInstaller (onedir)
Source: "dist\EMDAdminPanel\*"; \
  DestDir: "{app}\Admin Panel"; \
  Flags: ignoreversion recursesubdirs createallsubdirs; \
  Components: admin

; Factory Panel — built by PyInstaller (single exe)
Source: "dist\EMDFactoryPanel.exe"; \
  DestDir: "{app}\Factory Panel"; \
  DestName: "EMDFactoryPanel.exe"; \
  Flags: ignoreversion; \
  Components: factory

; Prerequisite runtime for Qt/PySide6 binaries (only needed for Admin Panel)
Source: "prerequisites\vc_redist.x64.exe"; \
  DestDir: "{tmp}"; \
  Flags: deleteafterinstall ignoreversion; \
  Components: admin

[Icons]
; Start Menu - Admin Panel
Name: "{group}\Admin Panel"; \
  Filename: "{app}\Admin Panel\EMDAdminPanel.exe"; \
  Components: admin
Name: "{group}\Factory Panel"; \
  Filename: "{app}\Factory Panel\EMDFactoryPanel.exe"; \
  Components: factory
Name: "{group}\Uninstall EMD Group Panels"; \
  Filename: "{uninstallexe}"

; Desktop - Admin Panel
Name: "{commondesktop}\Admin Panel"; \
  Filename: "{app}\Admin Panel\EMDAdminPanel.exe"; \
  Tasks: desktopicon_admin

; Desktop - Factory Panel
Name: "{commondesktop}\Factory Panel"; \
  Filename: "{app}\Factory Panel\EMDFactoryPanel.exe"; \
  Tasks: desktopicon_factory

[Registry]
; Startup entry - Admin Panel (optional task)
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "EMDAdminPanel"; \
  ValueData: """{app}\Admin Panel\EMDAdminPanel.exe"""; \
  Flags: uninsdeletevalue; \
  Tasks: startupicon_admin

; Startup entry - Factory Panel (optional task)
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "EMDFactoryPanel"; \
  ValueData: """{app}\Factory Panel\EMDFactoryPanel.exe"""; \
  Flags: uninsdeletevalue; \
  Tasks: startupicon_factory

[Run]
; Install Microsoft VC++ runtime required by Qt/PySide6 (Admin Panel only)
Filename: "{tmp}\vc_redist.x64.exe"; \
  Parameters: "/install /quiet /norestart"; \
  StatusMsg: "Installing Microsoft Visual C++ Runtime..."; \
  Flags: waituntilterminated; \
  Components: admin

; Offer to launch Admin Panel after install
Filename: "{app}\Admin Panel\EMDAdminPanel.exe"; \
  Description: "Launch Admin Panel now"; \
  Flags: nowait postinstall skipifsilent; \
  Components: admin

; Offer to launch Factory Panel after install
Filename: "{app}\Factory Panel\EMDFactoryPanel.exe"; \
  Description: "Launch Factory Panel now"; \
  Flags: nowait postinstall skipifsilent; \
  Components: factory

[UninstallRun]
; Nothing extra needed — PyInstaller EXE is self-contained

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nEMD Group — Purchase Approval & Request Management System%n%nSelect which panels you want to install:%n• Admin Panel: For purchase approval management%n• Factory Panel: For purchase request submission%n%nCreated by Daniyal%n%nClick Next to continue.
