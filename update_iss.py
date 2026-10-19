import re
import os

iss_path = r'C:\STARGATE_CAFE\StarGate_Cafe_Setup.iss'
with open(iss_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

content = re.sub(r'#define MyAppVersion\s+"[^"]+"', '#define MyAppVersion   "5.3.0"', content)
content = re.sub(r'#define MyAppArabicName\s+"[^"]+"', '#define MyAppArabicName "STARGATE CAFE"', content)

init_setup = """function InitializeSetup(): Boolean;
begin
  Result := True;
end;"""
content = re.sub(r'function InitializeSetup\(\): Boolean;[\s\S]*?end;', init_setup, content)

content = content.replace("OutputDir=C:\\STARGATE_CAFE\\installer_output", "OutputDir=C:\\Users\\mouha\\Desktop")

with open(iss_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Updated ISS file successfully.')
