@echo off
chcp 65001 >nul
title STARGATE CAFE - Open in VS Code

set "VSCODE_PATH=%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"
set "PROJECT_PATH=d:\STARGATE\organized_programs\cafe"

if exist "%VSCODE_PATH%" (
    start "" "%VSCODE_PATH%" "%PROJECT_PATH%" "%PROJECT_PATH%\app.py"
) else (
    code "%PROJECT_PATH%" "%PROJECT_PATH%\app.py"
)
exit
