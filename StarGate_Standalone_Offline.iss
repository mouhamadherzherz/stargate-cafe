; =====================================================================
; مثبت برنامج ستارجيت كافيه المستقل والشامل - STARGATE STANDALONE OFFLINE POS
; Inno Setup 7 Script - 100% Offline Standalone - Zero Dependencies
; =====================================================================

#define MyAppName        "STARGATE Cafe POS"
#define MyAppArabicName   "برنامج ستارجيت كافيه - النسخة المستقلة"
#define MyAppVersion     "5.7.0"
#define MyAppPublisher   "STARGATE EXPERTS"
#define MyAppExeName     "STARGATE_POS.exe"
#define MyDistDir        "d:\STARGATE\organized_programs\cafe\dist\STARGATE_POS"
#define MyCafeDir        "d:\STARGATE\organized_programs\cafe"

[Setup]
AppId={{C4FE-OFFLINE-STANDALONE-STARGATE-2026}}
AppName={#MyAppArabicName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppArabicName} v{#MyAppVersion} (أوفلاين بالكامل)
AppPublisher={#MyAppPublisher}
DefaultDirName=C:\STARGATE_CAFE
DefaultGroupName={#MyAppArabicName}
AllowNoIcons=yes
OutputDir=C:\Users\mouha\Desktop
OutputBaseFilename=تثبيت_ستارجيت_كافيه_المستقل_اوفلاين
SetupIconFile={#MyCafeDir}\app_icon.ico
Compression=lzma2/ultra64
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
; 1. Embedded Python Engine & Binaries (Full Standalone Offline)
Source: "{#MyDistDir}\STARGATE_POS.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyDistDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; 2. Application Core Python Modules & Resources
Source: "{#MyCafeDir}\app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\accounting.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\database.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\desktop_app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\logger.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\cafe_version.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyCafeDir}\app_icon.ico"; DestName: "stargate_logo.ico"; DestDir: "{app}"; Flags: ignoreversion

; 3. Templates & Static Web UI
Source: "{#MyCafeDir}\templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MyCafeDir}\static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs createallsubdirs

; 4. Pure Clean Zero Database (Never overwritten if existing on update)
Source: "{#MyCafeDir}\data\cafe_accounting.db"; DestDir: "{app}\data"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{userdesktop}\{#MyAppArabicName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\app_icon.ico"
Name: "{group}\{#MyAppArabicName}";       Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\إلغاء تثبيت {#MyAppArabicName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "تشغيل برنامج ستارجيت كافيه الآن"; Flags: nowait postinstall skipifsilent
