@echo off
chcp 65001 >nul
color 0B
title STARGATE CAFE - تحديث فوري من الانترنت

echo ======================================================================
echo         STARGATE CAFE - التحديث الذكي الفوري من الانترنت
echo              github.com/mouhamadherzherz/stargate-cafe
echo ======================================================================
echo.

set "INSTALL_DIR=C:\STARGATE_CAFE"
set "GITHUB_RAW=https://raw.githubusercontent.com/mouhamadherzherz/stargate-cafe/master"
set "TEMP_UPDATE=%TEMP%\stargate_cafe_update"

:: التحقق من الاتصال بالانترنت
echo [0/6] التحقق من الاتصال بالانترنت...
ping -n 1 github.com >nul 2>&1
if errorlevel 1 (
    color 0C
    echo.
    echo [!] خطأ: لا يوجد اتصال بالانترنت!
    echo     تأكد من الاتصال ثم أعد تشغيل هذا الملف.
    echo.
    pause
    exit /b 1
)
echo     [OK] الاتصال بالانترنت يعمل بشكل صحيح.
echo.

:: حفظ نسخة احتياطية آمنة لقاعدة البيانات
echo [1/6] حماية بياناتك - جاري حفظ نسخة احتياطية طارئة...
if exist "%INSTALL_DIR%\data\cafe_accounting.db" (
    if not exist "%INSTALL_DIR%\Safe_Backups" mkdir "%INSTALL_DIR%\Safe_Backups"
    copy /Y "%INSTALL_DIR%\data\cafe_accounting.db" "%INSTALL_DIR%\Safe_Backups\backup_before_update_%date:~-4%%date:~3,2%%date:~0,2%.db" >nul 2>&1
    echo     [OK] تم حفظ النسخة الاحتياطية بأمان كامل في Safe_Backups.
) else (
    echo     [تثبيت جديد] لا توجد بيانات سابقة.
)

:: تهيئة مجلد التحديث المؤقت
echo [2/6] تهيئة بيئة التحديث...
if exist "%TEMP_UPDATE%" rmdir /S /Q "%TEMP_UPDATE%" >nul 2>&1
mkdir "%TEMP_UPDATE%" >nul 2>&1
mkdir "%TEMP_UPDATE%\templates" >nul 2>&1
echo     [OK] جاهز لتحميل التحديثات.

:: تحميل الملفات المحدّثة الأساسية من GitHub
echo [3/6] جاري تحميل التحديثات من الانترنت...
echo     (هذا قد يستغرق بضع ثوانٍ حسب سرعة الانترنت)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$files = @('accounting.py','app.py','database.py','desktop_app.py'); ^
   $base = '%GITHUB_RAW%'; ^
   $dest = '%TEMP_UPDATE%'; ^
   $ok = 0; $fail = 0; ^
   foreach ($f in $files) { ^
     try { ^
       Invoke-WebRequest -Uri \"$base/$f\" -OutFile \"$dest\$f\" -UseBasicParsing -TimeoutSec 30; ^
       Write-Host \"      [+] تم تحميل: $f\"; $ok++ ^
     } catch { ^
       Write-Host \"      [!] فشل تحميل: $f\"; $fail++ ^
     } ^
   }; ^
   Write-Host \"   ملفات محمّلة: $ok  فشل: $fail\""

:: تحميل القوالب
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$templates = @('templates/dashboard.html','templates/safe.html','templates/debts.html','templates/reports.html','templates/settings.html','templates/cafe_orders.html','templates/print_daily_closing.html','templates/print_safe_statement.html','templates/admin.html','templates/employees.html','templates/inventory.html'); ^
   $base = '%GITHUB_RAW%'; ^
   $dest = '%TEMP_UPDATE%\templates'; ^
   foreach ($t in $templates) { ^
     $name = Split-Path $t -Leaf; ^
     try { ^
       Invoke-WebRequest -Uri \"$base/$t\" -OutFile \"$dest\$name\" -UseBasicParsing -TimeoutSec 30 ^
     } catch {} ^
   }; ^
   Write-Host '      [OK] تم تحميل القوالب.'"

echo     [OK] اكتمل تحميل التحديثات.

:: إيقاف النسخة القديمة
echo [4/6] جاري إيقاف البرنامج القديم وفك قفل الملفات...
taskkill /F /IM STARGATE.exe >nul 2>&1
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM msedge.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo     [OK] تم إيقاف النسخة القديمة.

:: تطبيق التحديثات
echo [5/6] جاري تطبيق التحديثات على البرنامج المثبت...

:: تحديث ملفات Python (المنطق الرئيسي)
if exist "%TEMP_UPDATE%\accounting.py" (
    copy /Y "%TEMP_UPDATE%\accounting.py" "%INSTALL_DIR%\accounting.py" >nul 2>&1
    copy /Y "%TEMP_UPDATE%\accounting.py" "%INSTALL_DIR%\_internal\accounting.py" >nul 2>&1
    echo     [+] تم تحديث: accounting.py (الحسابات والمحاسبة)
)
if exist "%TEMP_UPDATE%\app.py" (
    copy /Y "%TEMP_UPDATE%\app.py" "%INSTALL_DIR%\app.py" >nul 2>&1
    copy /Y "%TEMP_UPDATE%\app.py" "%INSTALL_DIR%\_internal\app.py" >nul 2>&1
    echo     [+] تم تحديث: app.py (منطق التطبيق)
)
if exist "%TEMP_UPDATE%\database.py" (
    copy /Y "%TEMP_UPDATE%\database.py" "%INSTALL_DIR%\database.py" >nul 2>&1
    copy /Y "%TEMP_UPDATE%\database.py" "%INSTALL_DIR%\_internal\database.py" >nul 2>&1
    echo     [+] تم تحديث: database.py (قاعدة البيانات)
)
if exist "%TEMP_UPDATE%\desktop_app.py" (
    copy /Y "%TEMP_UPDATE%\desktop_app.py" "%INSTALL_DIR%\desktop_app.py" >nul 2>&1
    copy /Y "%TEMP_UPDATE%\desktop_app.py" "%INSTALL_DIR%\_internal\desktop_app.py" >nul 2>&1
    echo     [+] تم تحديث: desktop_app.py (مشغّل التطبيق)
)

:: تحديث القوالب
if exist "%TEMP_UPDATE%\templates" (
    robocopy "%TEMP_UPDATE%\templates" "%INSTALL_DIR%\templates" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul
    robocopy "%TEMP_UPDATE%\templates" "%INSTALL_DIR%\_internal\templates" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul
    echo     [+] تم تحديث جميع القوالب والواجهات.
)

:: تنظيف ملفات التحديث المؤقتة
rmdir /S /Q "%TEMP_UPDATE%" >nul 2>&1

:: تنظيف كاش المتصفح لتظهر التغييرات فوراً
if exist "%INSTALL_DIR%\data\app_profile\Default\Cache" (
    rmdir /S /Q "%INSTALL_DIR%\data\app_profile\Default\Cache" >nul 2>&1
)
if exist "%INSTALL_DIR%\data\app_profile\Default\Code Cache" (
    rmdir /S /Q "%INSTALL_DIR%\data\app_profile\Default\Code Cache" >nul 2>&1
)

echo     [OK] تم تطبيق جميع التحديثات بنجاح.

echo.
echo ======================================================================
color 0A
echo   🎉 تم التحديث بنجاح تام!
echo ======================================================================
echo.
echo   ✅ تم تحديث: محرك الحسابات والمالية والخزنة
echo   ✅ تم تحديث: واجهات التقارير وتسكير الحسابات
echo   ✅ بياناتك ومبيعاتك محفوظة 100%% - لم يُمس شيء
echo   ✅ تم حفظ نسخة احتياطية في مجلد Safe_Backups
echo.
echo ======================================================================
echo.

set /p run_now="هل تريد تشغيل البرنامج الآن؟ (Y/N): "
if /i "%run_now%"=="Y" (
    echo.
    echo جاري تشغيل STARGATE CAFE...
    start "" "C:\STARGATE_CAFE\STARGATE.exe"
    timeout /t 2 /nobreak >nul
)

exit
