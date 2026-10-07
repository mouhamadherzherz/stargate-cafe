@echo off
chcp 65001 >nul
color 0B
title STARGATE CAFE - تثبيت التحديث المباشر v5.7.0 PRO
echo ======================================================================
echo         STARGATE CAFE - تثبيت التحديث الفوري (v5.7.0 PRO)
echo ======================================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "CAFE_DIR=C:\STARGATE_CAFE"
set "ZIP_FILE="

:: البحث عن ملف الزيب
if exist "%SCRIPT_DIR%Stargate_Cafe_Update.zip" (
    set "ZIP_FILE=%SCRIPT_DIR%Stargate_Cafe_Update.zip"
) else if exist "%USERPROFILE%\Desktop\Stargate_Cafe_Update.zip" (
    set "ZIP_FILE=%USERPROFILE%\Desktop\Stargate_Cafe_Update.zip"
) else if exist "%CAFE_DIR%\Stargate_Cafe_Update.zip" (
    set "ZIP_FILE=%CAFE_DIR%\Stargate_Cafe_Update.zip"
)

if "%ZIP_FILE%"=="" (
    color 0C
    echo [!] لم يتم العثور على ملف Stargate_Cafe_Update.zip
    echo يرجى وضع هذا الملف بجانب ملف Stargate_Cafe_Update.zip ثم إعادة المحاولة.
    echo.
    pause
    exit /b 1
)

if not exist "%CAFE_DIR%" (
    color 0C
    echo [!] مجلد البرنامج %CAFE_DIR% غير موجود على هذا الجهاز.
    pause
    exit /b 1
)

echo [1/4] إيقاف البرنامج القديم وفك قفل الملفات...
taskkill /F /IM STARGATE.exe >nul 2>&1
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1
taskkill /F /IM msedge.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo [2/4] جاري استخراج ملفات التحديث الجديد...
set "TEMP_DIR=%CAFE_DIR%\temp_update_extract"
if exist "%TEMP_DIR%" rmdir /S /Q "%TEMP_DIR%" >nul 2>&1
mkdir "%TEMP_DIR%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%TEMP_DIR%' -Force"

if not exist "%TEMP_DIR%\app.py" (
    color 0C
    echo [!] فشل فك ضغط التحديث أو الملف تالف.
    pause
    exit /b 1
)

echo [3/4] تثبيت التحديث وحماية قواعد البيانات والمبيعات...
robocopy "%TEMP_DIR%" "%CAFE_DIR%" /E /IS /IT /XF "*.db" "*.sqlite" "cafe_accounting.db" /XD "data" "Safe_Backups" >nul
if exist "%CAFE_DIR%\_internal" (
    robocopy "%TEMP_DIR%\templates" "%CAFE_DIR%\_internal\templates" /E /IS >nul 2>&1
    robocopy "%TEMP_DIR%\static"    "%CAFE_DIR%\_internal\static"    /E /IS >nul 2>&1
    copy /Y "%TEMP_DIR%\*.py" "%CAFE_DIR%\_internal\" >nul 2>&1
    copy /Y "%TEMP_DIR%\cafe_version.json" "%CAFE_DIR%\_internal\" >nul 2>&1
)

:: تنظيف المجلد المؤقت
rmdir /S /Q "%TEMP_DIR%" >nul 2>&1

:: مسح كاش المتصفح لظهور الميزات فوراً
if exist "%CAFE_DIR%\data\app_profile\Default\Cache" (
    rmdir /S /Q "%CAFE_DIR%\data\app_profile\Default\Cache" >nul 2>&1
)
if exist "%CAFE_DIR%\data\app_profile\Default\Code Cache" (
    rmdir /S /Q "%CAFE_DIR%\data\app_profile\Default\Code Cache" >nul 2>&1
)

echo [4/4] تشغيل البرنامج...
echo ======================================================================
color 0A
echo   🎉 تم تثبيت التحديث v5.3.1 بنجاح تام!
echo ======================================================================
cd /d "%CAFE_DIR%"
if exist "STARGATE.exe" (
    start "" "STARGATE.exe"
) else (
    start "" pythonw.exe desktop_app.py
)
timeout /t 3 /nobreak >nul
exit
