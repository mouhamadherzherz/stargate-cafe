@echo off
chcp 65001 >nul
title STARGATE CAFE - كاشير الموظف
echo ======================================================
echo    جاري فتح كاشير ونظام ستارجيت كافيه للموظف...
echo ======================================================

set "TARGET_URL=http://192.168.10.27:5000"

set "EDGE_EXE="

if defined EDGE_EXE (
    start "" "%EDGE_EXE%" --app="%TARGET_URL%" --window-size=1360,880
) else (
    start "" "%TARGET_URL%"
)
exit
