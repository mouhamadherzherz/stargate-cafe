# -*- coding: utf-8 -*-
import os
import re
import subprocess
import shutil

iss_path = r"C:\STARGATE_CAFE\StarGate_Cafe_Setup.iss"
desktop_dir = os.path.expanduser(r"~\Desktop")

import json

ver_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cafe_version.json')
current_ver = '6.1.0'
if os.path.exists(ver_file):
    try:
        with open(ver_file, 'r', encoding='utf-8') as vf:
            current_ver = json.load(vf).get('version', '6.1.0')
    except Exception:
        pass

print("Reading ISS:", iss_path)
with open(iss_path, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.strip().startswith('#define MyAppVersion'):
        new_lines.append(f'#define MyAppVersion   "{current_ver}"\n')
    elif line.strip().startswith('OutputDir='):
        new_lines.append(f'OutputDir={desktop_dir}\n')
    else:
        new_lines.append(line)

with open(iss_path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print(f"[OK] ISS updated to version {current_ver}")

# Run Inno Setup Compiler
iscc_path = r"C:\Program Files\Inno Setup 7\ISCC.exe"
if not os.path.exists(iscc_path):
    print("[!] ISCC not found at:", iscc_path)
else:
    print("[*] Compiling installer with Inno Setup 7...")
    res = subprocess.run([iscc_path, iss_path], capture_output=True, text=True)
    if res.returncode == 0:
        print("[OK] Compilation SUCCEEDED!")
        target_exe = os.path.join(desktop_dir, f"StargateCafe_Setup_v{current_ver}.exe")
        if os.path.exists(target_exe):
            size_mb = os.path.getsize(target_exe) / (1024 * 1024)
            print(f"[OK] Created: {target_exe} ({size_mb:.2f} MB)")
            for copy_dest in [
                os.path.join(desktop_dir, "تثبيت_برنامج_ستارجيت_كافيه_Setup.exe"),
                r"C:\STARGATE_CAFE\StargateCafe_Setup.exe",
                r"d:\STARGATE\organized_programs\cafe\StargateCafe_Setup.exe"
            ]:
                try:
                    shutil.copy2(target_exe, copy_dest)
                    print(f"[OK] Copied to: {copy_dest}")
                except Exception as e:
                    print(f"[!] Warning copying to {copy_dest}: {e}")
        else:
            print("[?] Output file check:", os.listdir(desktop_dir))
    else:
        print("[!] ISCC compilation failed:")
        print(res.stderr or res.stdout)
