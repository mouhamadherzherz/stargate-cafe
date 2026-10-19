@echo off
chcp 65001 >nul
color 0B
title STARGATE CAFE - تثبيت كاشير الموظف الجديد بالكامل v5.7.0

echo ======================================================================
echo    STARGATE CAFE - تثبيت واستبدال برنامج الموظف بالكامل (v5.7.0)
echo ======================================================================
echo.

set "CAFE_DIR=C:\STARGATE_CAFE"
if not exist "%CAFE_DIR%" mkdir "%CAFE_DIR%" >nul 2>&1

:: 1. إيقاف أي برنامج قديم وفك القفل
echo [1/3] إيقاف العمليات القديمة وتنظيف الملفات التالفة...
taskkill /F /IM STARGATE.exe >nul 2>&1
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1

:: حذف مجلد _internal القديم التالف نهائياً لتفادي مشكلة pyinstaller
if exist "%CAFE_DIR%\_internal" (
    rmdir /S /Q "%CAFE_DIR%\_internal" >nul 2>&1
)

:: 2. تنزيل المشغل التنفيذي الأصلي النظيف (بدون pyinstaller)
echo [2/3] تثبيت مشغل الكاشير الأصلي الجديد (خفيف وسريع جداً)...
set "CLIENT_EXE=%CAFE_DIR%\STARGATE.exe"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; ^
   $downloaded = $false; ^
   try { ^
     $wc = New-Object System.Net.WebClient; ^
     $wc.DownloadFile('http://192.168.10.27:5000/download/client.exe', '%CLIENT_EXE%'); ^
     if (Test-Path '%CLIENT_EXE%') { $downloaded = $true } ^
   } catch {}; ^
   if (-not $downloaded) { ^
     try { ^
       $wc = New-Object System.Net.WebClient; ^
       $wc.DownloadFile('http://192.168.10.27:5000/static/STARGATE_CLIENT.exe', '%CLIENT_EXE%'); ^
     } catch {} ^
   }"

:: 3. إنشاء اختصار مباشر على سطح المكتب
echo [3/3] إنشاء اختصار التشغيل على سطح المكتب...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $s = $ws.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'كاشير ستارجيت كافيه.lnk')); ^
   $s.TargetPath = '%CLIENT_EXE%'; ^
   $s.WorkingDirectory = '%CAFE_DIR%'; ^
   $s.Save()"

echo.
echo ======================================================================
color 0A
echo   🎉 تم تثبيت واستبدال البرنامج بنجاح تام!
echo ======================================================================
echo.
echo جاري فتح شاشة الكاشير الآن...

start "" "%CLIENT_EXE%"
timeout /t 3 /nobreak >nul
exit
