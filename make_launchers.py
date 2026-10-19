# -*- coding: utf-8 -*-
import os
import shutil

src_bat = r'd:\STARGATE\organized_programs\cafe\تثبيت_وتحديث_برنامج_الموظف_فوراً.bat'
dst_bat = os.path.expanduser(r'~\Desktop\تثبيت_وتحديث_برنامج_الموظف_فوراً.bat')

launcher_content = '''@echo off
chcp 65001 >nul
title STARGATE CAFE - كاشير الموظف
echo ======================================================
echo    جاري فتح كاشير ونظام ستارجيت كافيه للموظف...
echo ======================================================

set "TARGET_URL=http://192.168.10.27:5000"

set "EDGE_EXE="
if exist "%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe" set "EDGE_EXE=%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe"
if exist "%ProgramFiles%\\Microsoft\\Edge\\Application\\msedge.exe" set "EDGE_EXE=%ProgramFiles%\\Microsoft\\Edge\\Application\\msedge.exe"
if exist "%LocalAppData%\\Microsoft\\Edge\\Application\\msedge.exe" set "EDGE_EXE=%LocalAppData%\\Microsoft\\Edge\\Application\\msedge.exe"

if defined EDGE_EXE (
    start "" "%EDGE_EXE%" --app="%TARGET_URL%" --window-size=1360,880
) else (
    start "" "%TARGET_URL%"
)
exit
'''

desktop_launcher = os.path.expanduser(r'~\Desktop\تشغيل_كاشير_الموظف_فوراً.bat')
with open(desktop_launcher, 'w', encoding='utf-8') as f:
    f.write(launcher_content)

cafe_launcher = r'd:\STARGATE\organized_programs\cafe\تشغيل_كاشير_الموظف_فوراً.bat'
with open(cafe_launcher, 'w', encoding='utf-8') as f:
    f.write(launcher_content)

shutil.copy2(src_bat, dst_bat)
print("SUCCESS: Updated launchers created on Desktop and cafe directory!")
