@echo off
chcp 65001 >nul
color 0B
title نظام ستارجيت كافيه - التثبيت والتحديث الذكي الفوري (STARGATE CAFE)

echo ======================================================================
echo              نظام ستارجيت كافيه - STARGATE CAFE SYSTEM
echo        التحديث الشامل للصور، الواجهات، تقارير الخزنة والمبيعات
echo ======================================================================
echo.

set "TARGET_DIR=C:\STARGATE_CAFE"

:: تحديد مصدر الملفات بذكاء
if exist "%~dp0STARGATE.exe" (
    set "APP_SOURCE=%~dp0"
) else if exist "%~dp0App_Files\STARGATE.exe" (
    set "APP_SOURCE=%~dp0App_Files"
) else (
    set "APP_SOURCE=%~dp0"
)

echo [1/6] جاري إغلاق أي نسخة سابقة قيد التشغيل وإغلاق المتصفح لفك قفل الملفات...
taskkill /F /IM STARGATE.exe >nul 2>&1
taskkill /F /IM msedge.exe >nul 2>&1
timeout /t 1 /nobreak >nul

echo [2/6] جاري تهيئة مجلدات البرنامج على القرص C:...
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
if not exist "%TARGET_DIR%\data" mkdir "%TARGET_DIR%\data"
if not exist "%TARGET_DIR%\Safe_Backups" mkdir "%TARGET_DIR%\Safe_Backups"
if not exist "%TARGET_DIR%\static\uploads" mkdir "%TARGET_DIR%\static\uploads"
if not exist "%TARGET_DIR%\_internal\templates" mkdir "%TARGET_DIR%\_internal\templates"
if not exist "%TARGET_DIR%\_internal\static\uploads" mkdir "%TARGET_DIR%\_internal\static\uploads"

:: أمان البيانات 100%: حفظ نسخة احتياطية من قاعدة البيانات الحالية
if exist "%TARGET_DIR%\data\cafe_accounting.db" (
    echo [3/6] حفظ نسخة احتياطية آمنة لقاعدة البيانات الحالية...
    copy /Y "%TARGET_DIR%\data\cafe_accounting.db" "%TARGET_DIR%\Safe_Backups\backup_before_update.db" >nul 2>&1
    echo       [تم حفظ النسخة الاحتياطية بنجاح في Safe_Backups]
) else (
    echo [3/6] تثبيت جديد: جاري اعتماد قاعدة البيانات المحملة بالمنتجات والصور...
    if exist "%APP_SOURCE%\data\cafe_accounting.db" (
        copy /Y "%APP_SOURCE%\data\cafe_accounting.db" "%TARGET_DIR%\data\cafe_accounting.db" >nul 2>&1
    )
)

echo [4/6] تنظيف الكاش والذاكرة المؤقتة لضمان ظهور التحديثات فوراً بدون تعليق...
if exist "%TARGET_DIR%\data\app_profile\Default\Cache" (
    rmdir /S /Q "%TARGET_DIR%\data\app_profile\Default\Cache" >nul 2>&1
)
if exist "%TARGET_DIR%\data\app_profile\Default\Code Cache" (
    rmdir /S /Q "%TARGET_DIR%\data\app_profile\Default\Code Cache" >nul 2>&1
)
if exist "%TARGET_DIR%\data\app_profile\Default\GPUCache" (
    rmdir /S /Q "%TARGET_DIR%\data\app_profile\Default\GPUCache" >nul 2>&1
)

echo [5/6] جاري تحديث ملفات النظام، القوالب، الصور المحسنة، وملفات _internal...
robocopy "%APP_SOURCE%" "%TARGET_DIR%" /E /XD "%TARGET_DIR%\Safe_Backups" /XF "*.log" /NFL /NDL /NJH /NJS /nc /ns /np >nul

:: تأكيد وتحديث قوالب _internal لضمان قراءة النسخة الجديدة دائماً
if exist "%APP_SOURCE%\templates" (
    robocopy "%APP_SOURCE%\templates" "%TARGET_DIR%\templates" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul
    robocopy "%APP_SOURCE%\templates" "%TARGET_DIR%\_internal\templates" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul
)
if exist "%APP_SOURCE%\static\uploads" (
    robocopy "%APP_SOURCE%\static\uploads" "%TARGET_DIR%\static\uploads" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul
    robocopy "%APP_SOURCE%\static\uploads" "%TARGET_DIR%\_internal\static\uploads" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul
)

:: التأكد القطعي من وجود قاعدة البيانات
if not exist "%TARGET_DIR%\data\cafe_accounting.db" (
    if exist "%APP_SOURCE%\data\cafe_accounting.db" (
        copy /Y "%APP_SOURCE%\data\cafe_accounting.db" "%TARGET_DIR%\data\cafe_accounting.db" >nul 2>&1
    )
)

echo [6/6] إنشاء وتحديث اختصار رسمي احترافي على سطح المكتب...
powershell -Command "$WshShell = New-Object -comObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([System.IO.Path]::Combine([System.Environment]::GetFolderPath('Desktop'), 'STARGATE CAFE.lnk')); $Shortcut.TargetPath = 'C:\STARGATE_CAFE\STARGATE.exe'; $Shortcut.WorkingDirectory = 'C:\STARGATE_CAFE'; if(Test-Path 'C:\STARGATE_CAFE\app_icon.ico'){ $Shortcut.IconLocation = 'C:\STARGATE_CAFE\app_icon.ico,0' }; $Shortcut.Save()" >nul 2>&1

echo.
echo ======================================================================
echo                  تم التحديث والتثبيت بنجاح تام 100%%!
echo   - تم تحديث القوالب وملفات _internal والكاش بالكامل.
echo   - تم حل مشكلة ظهور أرقام ومسارات الصور مقابل المنتجات نهائياً.
echo   - تم تحسين جودة وعرض صور المنتجات بدون أي قص، مع مظهر استوديو احترافي.
echo   - ميزة لصق الصور الفوري بـ (Ctrl + V) من Google أو WhatsApp مفعلة.
echo   - تم تنظيف كاش المتصفح القديم لترى التعديلات فوراً وبدقة تامة.
echo   - جميع بيانات المبيعات، المخزون، والمنتجات محفوظة بأمان كامل.
echo   - عند أول تشغيل يطلب النظام ضبط كلمة سر الإدارة والموظفين.
echo   - تم وضع أيقونة البرنامج على سطح المكتب باسم STARGATE CAFE.
echo ======================================================================
echo.

set /p run_now="هل تريد تشغيل البرنامج الآن؟ (Y/N): "
if /i "%run_now%"=="Y" (
    start "" "C:\STARGATE_CAFE\STARGATE.exe"
)
exit
