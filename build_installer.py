import os
import re
import subprocess
import shutil

iss_path = r"C:\STARGATE_CAFE\StarGate_Cafe_Setup.iss"

print("Reading ISS:", iss_path)
with open(iss_path, "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

# Replace version with 5.3.2
content = re.sub(r'#define MyAppVersion\s+"[^"]+"', '#define MyAppVersion   "5.3.2"', content)

# Ensure output directory is Desktop
content = content.replace("OutputDir=C:\\STARGATE_CAFE\\installer_output", "OutputDir=C:\\Users\\mouha\\Desktop")

with open(iss_path, "w", encoding="utf-8") as f:
    f.write(content)

print("[OK] ISS updated to version 5.3.2")

# Run Inno Setup Compiler
iscc_path = r"C:\Program Files\Inno Setup 7\ISCC.exe"
if not os.path.exists(iscc_path):
    print("[!] ISCC not found at:", iscc_path)
else:
    print("[*] Compiling installer with Inno Setup 7...")
    res = subprocess.run([iscc_path, iss_path], capture_output=True, text=True)
    if res.returncode == 0:
        print("[OK] Compilation SUCCEEDED!")
        target_exe = r"C:\Users\mouha\Desktop\StargateCafe_Setup_v5.3.2.exe"
        if os.path.exists(target_exe):
            size_mb = os.path.getsize(target_exe) / (1024 * 1024)
            print(f"[OK] Created: {target_exe} ({size_mb:.2f} MB)")
        else:
            print("[?] Compiled, but check output filename on Desktop.")
    else:
        print("[!] ISCC compilation failed:")
        print(res.stderr or res.stdout)
