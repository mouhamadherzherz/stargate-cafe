iss_path = r'C:\STARGATE_CAFE\StarGate_Cafe_Setup.iss'
with open(iss_path, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('#define MyAppVersion   "5.3.0"', '#define MyAppVersion   "5.3.1"')
with open(iss_path, 'w', encoding='utf-8') as f:
    f.write(c)
print('Updated ISS version to 5.3.1')
