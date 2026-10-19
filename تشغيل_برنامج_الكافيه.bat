@echo off
title Stargate Cafe Server
color 0b

echo ========================================================
echo        STARGATE CAFE - Server and POS Launcher
echo ========================================================
echo.

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/api/check_update' -TimeoutSec 1 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Server is already running!
) else (
    echo [INFO] Starting Stargate Cafe server...
    if exist "C:\STARGATE_CAFE" (
        cd /d "C:\STARGATE_CAFE"
    ) else if exist "d:\STARGATE\organized_programs\cafe" (
        cd /d "d:\STARGATE\organized_programs\cafe"
    )
    start "" pythonw.exe app.py
    timeout /t 2 /nobreak >nul
)

set "EDGE_EXE="

set "PROFILE_DIR=%LOCALAPPDATA%\StargateCafeBrowserProfile"
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%" >nul 2>&1
if exist "%PROFILE_DIR%\lockfile" del /F /Q "%PROFILE_DIR%\lockfile" >nul 2>&1
if exist "%PROFILE_DIR%\Default\Cache" rd /s /q "%PROFILE_DIR%\Default\Cache" >nul 2>&1
if exist "%PROFILE_DIR%\Default\Code Cache" rd /s /q "%PROFILE_DIR%\Default\Code Cache" >nul 2>&1

if defined EDGE_EXE (
    start "" "%EDGE_EXE%" --user-data-dir="%PROFILE_DIR%" --app="http://127.0.0.1:5000/employee/login" --window-size=1360,880 --no-first-run
) else (
    start "" "http://127.0.0.1:5000/employee/login"
)

echo [OK] Opening POS in browser...
ping 127.0.0.1 -n 2 >nul
exit
