; =====================================================================
; مثبت برنامج ستارجيت كافيه الكامل - STARGATE CAFE FULL SETUP v5.7.0
; Inno Setup 7 Script - Full Complete System Package
; =====================================================================

#define MyAppName      "Stargate Cafe POS"
#define MyAppArabicName "برنامج ستارجيت كافيه والمحاسبة"
#define MyAppVersion   "5.7.0"
#define MyAppPublisher "STARGATE EXPERTS"
#define MyAppExeName   "STARGATE.exe"
#define MyCafeDir      "d:\STARGATE\organized_programs\cafe"

[Setup]
AppId={{C4FE-FULL-STARGATE-POS-2026}}
AppName={#MyAppArabicName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppArabicName} v{#MyAppVersion} PRO
AppPublisher={#MyAppPublisher}
DefaultDirName=C:\STARGATE_CAFE
DefaultGroupName={#MyAppArabicName}
AllowNoIcons=yes
OutputDir=C:\Users\mouha\Desktop
OutputBaseFilename=تثبيت_برنامج_ستارجيت_كافيه_الكامل_Setup
SetupIconFile={#MyCafeDir}\app_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableDirPage=no
PrivilegesRequired=lowest
CloseApplications=yes
UninstallDisplayIcon={app}\app_icon.ico
UninstallDisplayName={#MyAppArabicName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "إنشاء اختصار على سطح المكتب (Desktop Shortcut)"; GroupDescription: "الأيقونات:"

[Files]
; Complete Core Source Code & Resources
Source: "{#MyCafeDir}\app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\accounting.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\database.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\desktop_app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\logger.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\cafe_version.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\app_icon.ico"; DestName: "stargate_logo.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\تشغيل_برنامج_الكافيه.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\STARGATE_CLIENT.exe"; DestName: "STARGATE.exe"; DestDir: "{app}"; Flags: ignoreversion

; Full Web Templates and Static Assets
Source: "{#MyCafeDir}\templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MyCafeDir}\static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs createallsubdirs

; Database Directory & Clean Default DB (Zero data loss: never overwrite if client already has data)
Source: "{#MyCafeDir}\data\cafe_accounting.db"; DestDir: "{app}\data"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{userdesktop}\{#MyAppArabicName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\app_icon.ico"
Name: "{userdesktop}\تشغيل سيرفر الكافيه"; Filename: "{app}\تشغيل_برنامج_الكافيه.bat"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\app_icon.ico"
Name: "{group}\{#MyAppArabicName}";       Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\إلغاء تثبيت {#MyAppArabicName}"; Filename: "{uninstallexe}"

[InstallDelete]
; Clean up old broken files
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\*.pyc"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "تشغيل برنامج ستارجيت كافيه الآن"; Flags: nowait postinstall skipifsilent
