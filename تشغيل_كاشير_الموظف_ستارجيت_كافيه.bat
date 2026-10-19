@echo off
title Stargate Cafe POS
color 0b

echo ========================================================
echo        STARGATE CAFE POS - Employee Login
echo ========================================================
echo.

set "LOCAL_URL=http://127.0.0.1:5000"
set "SERVER_URL=http://192.168.10.27:5000"

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/api/check_update' -TimeoutSec 1 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 (
    set "TARGET_URL=%LOCAL_URL%"
) else (
    powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://192.168.10.27:5000/api/check_update' -TimeoutSec 1 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
    if %errorlevel% equ 0 (
        set "TARGET_URL=%SERVER_URL%"
    ) else (
        echo [INFO] Starting Stargate Cafe server...
        if exist "C:\STARGATE_CAFE" (
            cd /d "C:\STARGATE_CAFE"
        ) else if exist "d:\STARGATE\organized_programs\cafe" (
            cd /d "d:\STARGATE\organized_programs\cafe"
        )
        start "" pythonw.exe app.py
        timeout /t 2 /nobreak >nul
        set "TARGET_URL=%LOCAL_URL%"
    )
)

echo [OK] Connecting to: %TARGET_URL%

set "EDGE_EXE="

set "PROFILE_DIR=%LOCALAPPDATA%\StargateCafeBrowserProfile"
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%" >nul 2>&1
if exist "%PROFILE_DIR%\lockfile" del /F /Q "%PROFILE_DIR%\lockfile" >nul 2>&1

if defined EDGE_EXE (
    start "" "%EDGE_EXE%" --user-data-dir="%PROFILE_DIR%" --app="%TARGET_URL%/employee/login" --window-size=1360,880 --no-first-run
) else (
    start "" "%TARGET_URL%/employee/login"
)

echo [OK] Launched successfully!
ping 127.0.0.1 -n 2 >nul
exit
