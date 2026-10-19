; =====================================================================
; مثبت برنامج كاشير الموظف ستارجيت كافيه - STARGATE CAFE CLIENT
; Inno Setup Script - Clean Native Release (No PyInstaller)
; =====================================================================

#define MyAppName      "Stargate Cafe Cashier"
#define MyAppArabicName "كاشير ستارجيت كافيه"
#define MyAppVersion   "5.7.0"
#define MyAppPublisher "STARGATE EXPERTS"
#define MyAppExeName   "STARGATE.exe"
#define MySourceDir    "d:\STARGATE\organized_programs\cafe"

[Setup]
AppId={{C4FE-CLIENT-STARGATE-POS-2026}}
AppName={#MyAppArabicName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppArabicName} v{#MyAppVersion} PRO
AppPublisher={#MyAppPublisher}
DefaultDirName=C:\STARGATE_CAFE
DefaultGroupName={#MyAppArabicName}
AllowNoIcons=yes
OutputDir=C:\Users\mouha\Desktop
OutputBaseFilename=تثبيت_كاشير_الموظف_بالكامل
SetupIconFile={#MySourceDir}\app_icon.ico
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
DisableDirPage=no
PrivilegesRequired=lowest
CloseApplications=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppArabicName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "إنشاء اختصار على سطح المكتب (Desktop Shortcut)"; GroupDescription: "الأيقونات:"

[Files]
; Clean Native Client Executable & Icons
Source: "{#MySourceDir}\STARGATE_CLIENT.exe"; DestName: "STARGATE.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MySourceDir}\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MySourceDir}\app_icon.ico"; DestName: "stargate_logo.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\{#MyAppArabicName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\app_icon.ico"
Name: "{group}\{#MyAppArabicName}";       Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\إلغاء تثبيت {#MyAppArabicName}"; Filename: "{uninstallexe}"

[InstallDelete]
; Clean up any old broken PyInstaller files
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\*.pyc"
Type: files; Name: "{app}\*.log"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "تشغيل برنامج كاشير الموظف فوراً"; Flags: nowait postinstall skipifsilent
