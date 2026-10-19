@echo off
chcp 65001 >nul
color 0B
title STARGATE CAFE - تحديث جهاز الموظف الفوري v6.1.0 PRO
echo ======================================================================
echo         STARGATE CAFE - تحديث نظام الكافيه للموظف (v6.1.0 PRO)
echo         سيرفر التحديث المباشر: http://192.168.10.27:5000
echo ======================================================================
echo.

set "CAFE_DIR=C:\STARGATE_CAFE"
if not exist "%CAFE_DIR%" (
    echo [!] مجلد البرنامج %CAFE_DIR% غير موجود على هذا الجهاز.
    echo يرجى التأكد من مسار تثبيت STARGATE_CAFE.
    pause
    exit /b 1
)

echo [1/4] إيقاف البرنامج وفك قفل الملفات بأمان...
taskkill /F /IM STARGATE.exe >nul 2>&1
taskkill /F /IM STARGATE_CLIENT.exe >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*STARGATE_CAFE*' -or $_.CommandLine -like '*app.py*' -or $_.CommandLine -like '*desktop_app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
timeout /t 2 /nobreak >nul

echo [2/4] جاري تنزيل التحديث من السيرفر المحلي (فوري وبأقصى سرعة)...
set "TEMP_ZIP=%CAFE_DIR%\local_update_v610.zip"
set "TEMP_DIR=%CAFE_DIR%\local_update_extracted"

if exist "%TEMP_DIR%" rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
mkdir "%TEMP_DIR%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { ^
     [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; ^
     $wc = New-Object System.Net.WebClient; ^
     $wc.DownloadFile('http://192.168.10.27:5000/download/update.zip', '%TEMP_ZIP%'); ^
   } catch { ^
     Write-Host 'Local server unreachable, downloading from cloud repository...'; ^
     $wc = New-Object System.Net.WebClient; ^
     $wc.DownloadFile('https://raw.githubusercontent.com/mouhamadherzherz/stargate-cafe/master/Stargate_Cafe_Update.zip', '%TEMP_ZIP%'); ^
   }; ^
   Expand-Archive -Path '%TEMP_ZIP%' -DestinationPath '%TEMP_DIR%' -Force"

if not exist "%TEMP_DIR%\app.py" (
    echo.
    echo [!] فشل التنزيل من السيرفر المحلي والإنترنت.
    echo تأكد من اتصال الشبكة أو الاتصال بالسيرفر الرئيسي.
    pause
    exit /b 1
)

echo [3/4] تثبيت التحديث مع الحفاظ التام على المبيعات وقاعدة البيانات...
robocopy "%TEMP_DIR%" "%CAFE_DIR%" /E /IS /IT /XF "*.db" "*.sqlite" "cafe_accounting.db" /XD "data" "Safe_Backups" >nul
if exist "%CAFE_DIR%\_internal" (
    robocopy "%TEMP_DIR%\templates" "%CAFE_DIR%\_internal\templates" /E /IS >nul 2>&1
    robocopy "%TEMP_DIR%\static"    "%CAFE_DIR%\_internal\static"    /E /IS >nul 2>&1
    copy /Y "%TEMP_DIR%\*.py" "%CAFE_DIR%\_internal\" >nul 2>&1
    copy /Y "%TEMP_DIR%\cafe_version.json" "%CAFE_DIR%\_internal\" >nul 2>&1
)

:: تنظيف الملفات المؤقتة
del /F /Q "%TEMP_ZIP%" >nul 2>&1
rmdir /S /Q "%TEMP_DIR%" >nul 2>&1

:: تنظيف كاش المتصفح لظهور الميزات فوراً
if exist "%CAFE_DIR%\data\app_profile\Default\Cache" (
    rmdir /S /Q "%CAFE_DIR%\data\app_profile\Default\Cache" >nul 2>&1
)
if exist "%CAFE_DIR%\data\app_profile\Default\Code Cache" (
    rmdir /S /Q "%CAFE_DIR%\data\app_profile\Default\Code Cache" >nul 2>&1
)

echo [4/4] جاري إعادة تشغيل البرنامج بالإصدار الجديد v6.1.0...
echo ======================================================================
color 0A
echo   🎉 تم تحديث برنامج الموظف بنجاح تام إلى v6.1.0 PRO!
echo ======================================================================
cd /d "%CAFE_DIR%"
if exist "STARGATE.exe" (
    start "" "STARGATE.exe"
) else (
    start "" pythonw.exe desktop_app.py
)
timeout /t 3 /nobreak >nul
exit
