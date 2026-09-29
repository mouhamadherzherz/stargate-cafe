@echo off
chcp 65001 >nul
title تشغيل ستارجيت كافيه - STARGATE CAFE
cd /d "%~dp0"
if exist "%~dp0STARGATE.exe" (
    start "" "%~dp0STARGATE.exe"
) else (
    start "" python desktop_app.py
)
exit
