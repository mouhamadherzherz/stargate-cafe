@echo off
chcp 65001 >nul
title STARGATE CAFE v5.0 PRO - Master Server
cd /d "%~dp0"

:: تنظيف أي عمليات سابقة عالقة على المنفذ 5000
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr :5000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo ========================================================
echo   ☕ ستارجيت كافيه - STARGATE CAFE v5.0 PRO
echo   الرابط المحلي (لجهازك):     http://127.0.0.1:5000
echo   رابط الموظف (على الشبكة):  http://192.168.10.27:5000
echo ========================================================
echo السيرفر يعمل الآن... لا تغلق هذه النافذة.

start http://127.0.0.1:5000
python app.py
pause
