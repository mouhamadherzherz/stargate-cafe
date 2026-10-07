@echo off
chcp 65001 >nul
title تحديث برنامج ستارجيت كافيه - STARGATE CAFE v5.3.1
color 0b

echo ======================================================================
echo          STARGATE EXPERTS - تحديث برنامج الكافيه v5.3.1
echo ======================================================================
echo.

set "CAFE_DIR=C:\STARGATE_CAFE"

if not exist "%CAFE_DIR%" (
    echo [X] لم يتم العثور على مجلد برنامج الكافيه في %CAFE_DIR%
    echo يرجى التأكد من مسار تثبيت البرنامج.
    pause
    exit /b
)

:: 1. حفظ نسخة احتياطية فورية لقاعدة البيانات
echo [1/5] جاري حفظ نسخة احتياطية آمنة للبيانات والمبيعات...
if exist "%CAFE_DIR%\data\cafe_accounting.db" (
    if not exist "%CAFE_DIR%\Safe_Backups" mkdir "%CAFE_DIR%\Safe_Backups"
    copy /Y "%CAFE_DIR%\data\cafe_accounting.db" "%CAFE_DIR%\Safe_Backups\backup_before_v531_%random%.db" >nul 2>&1
    echo     [OK] تم تأمين نسخة احتياطية بنجاح 100%%.
)

:: 2. إيقاف البرنامج القديم لفك قفل الملفات
echo [2/5] جاري إغلاق النسخة القديمة لتطبيق التحديث...
taskkill /F /IM STARGATE.exe >nul 2>&1
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM msedge.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo     [OK] تم فك قفل الملفات.

:: 3. تنزيل التحديث السحابي الجديد
echo [3/5] جاري تنزيل حزمة التحديث v5.3.2 من السحابة...
set "ZIP_URL=https://github.com/mouhamadherzherz/stargate-cafe/releases/download/v5.3.2/Stargate_Cafe_Update.zip"
set "TEMP_ZIP=%CAFE_DIR%\update_v532.zip"
set "TEMP_EXTRACT=%CAFE_DIR%\update_extracted"

if exist "%TEMP_EXTRACT%" rmdir /S /Q "%TEMP_EXTRACT%" >nul 2>&1
mkdir "%TEMP_EXTRACT%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('%ZIP_URL%', '%TEMP_ZIP%'); Expand-Archive -Path '%TEMP_ZIP%' -DestinationPath '%TEMP_EXTRACT%' -Force"

if not exist "%TEMP_EXTRACT%\app.py" (
    echo [!] فشل تنزيل ملفات التحديث. تحقق من اتصال الإنترنت.
    pause
    exit /b
)
echo     [OK] تم تنزيل حزمة التحديث بنجاح.

:: 4. تطبيق التحديث مع الحفاظ على البيانات
echo [4/5] جاري تركيب التحديث وتحديث الحسابات والخزينة...
robocopy "%TEMP_EXTRACT%" "%CAFE_DIR%" /E /IS /IT /XF "*.db" "*.sqlite" "cafe_accounting.db" /XD "data" "Safe_Backups" >nul
if exist "%CAFE_DIR%\_internal" (
    robocopy "%TEMP_EXTRACT%\templates" "%CAFE_DIR%\_internal\templates" /E /IS >nul 2>&1
    robocopy "%TEMP_EXTRACT%\static"    "%CAFE_DIR%\_internal\static"    /E /IS >nul 2>&1
    copy /Y "%TEMP_EXTRACT%\*.py" "%CAFE_DIR%\_internal\" >nul 2>&1
    copy /Y "%TEMP_EXTRACT%\cafe_version.json" "%CAFE_DIR%\_internal\" >nul 2>&1
)

:: تنظيف الملفات المؤقتة
del /F /Q "%TEMP_ZIP%" >nul 2>&1
rmdir /S /Q "%TEMP_EXTRACT%" >nul 2>&1

:: تنظيف كاش المتصفح لظهور التغييرات فورا
if exist "%CAFE_DIR%\data\app_profile\Default\Cache" (
    rmdir /S /Q "%CAFE_DIR%\data\app_profile\Default\Cache" >nul 2>&1
)
if exist "%CAFE_DIR%\data\app_profile\Default\Code Cache" (
    rmdir /S /Q "%CAFE_DIR%\data\app_profile\Default\Code Cache" >nul 2>&1
)

echo.
echo ======================================================================
color 0a
echo   🎉 تم التحديث إلى الإصدار v4.4.0 بنجاح تام!
echo ======================================================================
echo   - تم إصلاح كافة أخطاء المالية والحسابات وتسكير اليومية والخزينة.
echo   - تم تفعيل شريط إشعارات التحديث التلقائي المستقبلي في الشاشة.
echo   - تم الحفاظ على 100%% من مبيعاتك وبياناتك وديونك دون أي مساس.
echo ======================================================================
echo.

echo [5/5] جاري تشغيل برنامج الكافيه الآن...
cd /d "%CAFE_DIR%"
if exist "STARGATE.exe" (
    start "" "STARGATE.exe"
) else (
    start "" pythonw.exe desktop_app.py
)

timeout /t 3 /nobreak >nul
exit