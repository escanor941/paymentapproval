; ============================================================
;  EMD Admin Panel — Inno Setup Installer Script
;  Build with: ISCC.exe setup_admin.iss
;  Requires Inno Setup 6: https://jrsoftware.org/isdl.php
; ============================================================

[Setup]
AppName=EMD Admin Panel
AppVersion=1.1
AppVerName=EMD Admin Panel v1.1
AppPublisher=EMD Group
AppPublisherURL=https://paymentapproval.onrender.com
AppSupportURL=https://paymentapproval.onrender.com
AppUpdatesURL=https://paymentapproval.onrender.com

; Installation directory
DefaultDirName={autopf}\EMD Group\Admin Panel
DefaultGroupName=EMD Group
DisableProgramGroupPage=no

; Output
OutputDir=installer
OutputBaseFilename=EMDAdminPanel_Setup_v1.1
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
UninstallDisplayName=EMD Admin Panel
UninstallDisplayIcon={app}\EMDAdminPanelLocal.exe
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
  Description: "Launch EMD Admin Panel at &Windows startup"; \
  GroupDescription: "Additional shortcuts:"; \
  Flags: unchecked

[Files]
; Main executable — built by PyInstaller (run build_admin_local_exe.bat first)
Source: "dist\EMDAdminPanelLocal.exe"; \
  DestDir: "{app}"; \
  DestName: "EMDAdminPanelLocal.exe"; \
  Flags: ignoreversion

[Icons]
; Start Menu
Name: "{group}\EMD Admin Panel";           Filename: "{app}\EMDAdminPanelLocal.exe"
Name: "{group}\Uninstall EMD Admin Panel"; Filename: "{uninstallexe}"

; Desktop
Name: "{commondesktop}\EMD Admin Panel"; \
  Filename: "{app}\EMDAdminPanelLocal.exe"; \
  Tasks: desktopicon

[Registry]
; Startup entry (optional task)
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "EMDAdminPanel"; \
  ValueData: """{app}\EMDAdminPanelLocal.exe"""; \
  Flags: uninsdeletevalue; \
  Tasks: startupicon

[Run]
; Offer to launch after install
Filename: "{app}\EMDAdminPanelLocal.exe"; \
  Description: "Launch EMD Admin Panel now"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Nothing extra needed — PyInstaller EXE is self-contained

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nEMD Group — Purchase Approval System%nCreated by Daniyal%n%nClick Next to continue.
