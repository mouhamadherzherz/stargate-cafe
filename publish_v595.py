# -*- coding: utf-8 -*-
import os
import sys
import json
import zipfile
import shutil
import subprocess
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding='utf-8')

TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "mouhamadherzherz/stargate-cafe"
VERSION = "5.9.5"
TAG = f"v{VERSION}"
RELEASE_NAME = f"Stargate Cafe & Gaming System {TAG} PRO"

SOURCE_DIR = r"d:\STARGATE\stargate_cafe_source"
ORGANIZED_DIR = r"d:\STARGATE\organized_programs\cafe"
OUTPUT_ZIP = os.path.join(SOURCE_DIR, "Stargate_Cafe_Update.zip")

print("=== 0. Syncing modified files from organized_programs to source ===")
for root_file in ["accounting.py", "app.py", "database.py", "cafe_version.json", "desktop_app.py", "logger.py"]:
    src_f = os.path.join(ORGANIZED_DIR, root_file)
    dst_f = os.path.join(SOURCE_DIR, root_file)
    if os.path.exists(src_f):
        shutil.copy2(src_f, dst_f)

for sub in ['templates', 'static']:
    s_src = os.path.join(ORGANIZED_DIR, sub)
    s_dst = os.path.join(SOURCE_DIR, sub)
    if os.path.exists(s_src):
        for root, dirs, files in os.walk(s_src):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'logs')]
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), s_src)
                target = os.path.join(s_dst, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(os.path.join(root, f), target)

print("=== 1. Building Stargate_Cafe_Update.zip ===")
if os.path.exists(OUTPUT_ZIP):
    try:
        os.remove(OUTPUT_ZIP)
    except Exception:
        pass

with zipfile.ZipFile(OUTPUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for root_file in os.listdir(ORGANIZED_DIR):
        abs_f = os.path.join(ORGANIZED_DIR, root_file)
        if os.path.isfile(abs_f):
            ext = os.path.splitext(root_file)[1].lower()
            if ext in ('.py', '.bat', '.json', '.txt', '.ico', '.png', '.jpg') and not root_file.endswith('.pyc'):
                if root_file not in ('cafe_accounting.db', 'lockfile', 'Stargate_Cafe_Update.zip', 'publish_release.py', 'publish_v570.py', 'publish_v595.py'):
                    zipf.write(abs_f, root_file)
    for sub in ['templates', 'static']:
        s_dir = os.path.join(ORGANIZED_DIR, sub)
        if os.path.exists(s_dir):
            for root, dirs, files in os.walk(s_dir):
                dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'logs')]
                for file in files:
                    if not file.endswith('.pyc') and not file.endswith('.tmp'):
                        abs_f = os.path.join(root, file)
                        rel_f = os.path.relpath(abs_f, ORGANIZED_DIR)
                        zipf.write(abs_f, rel_f)

zip_size_mb = os.path.getsize(OUTPUT_ZIP) / (1024 * 1024)
print(f"[OK] Stargate_Cafe_Update.zip built: {zip_size_mb:.2f} MB")

# Distribute zip locally
destinations = [
    r"d:\STARGATE\organized_programs\cafe\Stargate_Cafe_Update.zip",
    r"C:\STARGATE_CAFE\Stargate_Cafe_Update.zip",
    os.path.expanduser(r"~\Desktop\Stargate_Cafe_Update.zip")
]
for dst in destinations:
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(OUTPUT_ZIP, dst)
        print(f"[OK] Copied to: {dst}")
    except Exception as e:
        print(f"[!] Warning copying to {dst}: {e}")

print("\n=== 2. Committing and Pushing to GitHub (master) ===")
try:
    subprocess.run(["git", "-C", SOURCE_DIR, "add", "-A"], check=True)
    subprocess.run(["git", "-C", SOURCE_DIR, "commit", "-m", f"Release {TAG}: 100% strict inventory locks and permanent offline AI"], check=False)
    push_res = subprocess.run(["git", "-C", SOURCE_DIR, "push", f"https://{TOKEN}@github.com/{REPO}.git", "master"], capture_output=True, text=True)
    print("Push stdout:", push_res.stdout)
    print("Push stderr:", push_res.stderr)
    print("Push code:", push_res.returncode)
except Exception as e:
    print(f"Git push error: {e}")

print(f"\n=== 3. Creating / Updating GitHub Release {TAG} ===")
headers = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Stargate-Release-Bot"
}

with open(os.path.join(ORGANIZED_DIR, "cafe_version.json"), "r", encoding="utf-8") as vf:
    v_data = json.load(vf)

changelog_text = v_data.get("changelog", f"Release {TAG}")

rel_api_url = f"https://api.github.com/repos/{REPO}/releases"
release_id = None
upload_url = None

try:
    check_req = urllib.request.Request(f"{rel_api_url}/tags/{TAG}", headers=headers)
    with urllib.request.urlopen(check_req) as resp:
        existing = json.loads(resp.read().decode('utf-8'))
        release_id = existing['id']
        upload_url = existing['upload_url'].split('{')[0]
        print(f"[!] Release {TAG} already exists (ID: {release_id}). Removing existing assets...")
        for asset in existing.get('assets', []):
            if asset['name'] == 'Stargate_Cafe_Update.zip':
                del_req = urllib.request.Request(asset['url'], headers=headers, method='DELETE')
                urllib.request.urlopen(del_req)
                print("[OK] Deleted old asset.")
except urllib.error.HTTPError as e:
    if e.code == 404:
        print(f"[+] Release {TAG} does not exist yet. Creating new release...")
    else:
        print(f"[-] HTTP error checking release: {e}")

if not upload_url:
    payload = {
        "tag_name": TAG,
        "target_commitish": "master",
        "name": RELEASE_NAME,
        "body": changelog_text,
        "draft": False,
        "prerelease": False
    }
    req = urllib.request.Request(rel_api_url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    with urllib.request.urlopen(req) as resp:
        rel_info = json.loads(resp.read().decode('utf-8'))
        upload_url = rel_info['upload_url'].split('{')[0]
        print(f"[OK] Created GitHub release ID: {rel_info['id']}")

print(f"\n=== 4. Uploading Asset Stargate_Cafe_Update.zip ({zip_size_mb:.2f} MB) ===")
asset_upload_url = f"{upload_url}?name=Stargate_Cafe_Update.zip"
with open(OUTPUT_ZIP, 'rb') as f:
    zip_bytes = f.read()

up_headers = dict(headers)
up_headers['Content-Type'] = 'application/zip'
up_headers['Content-Length'] = str(len(zip_bytes))

up_req = urllib.request.Request(asset_upload_url, data=zip_bytes, headers=up_headers, method='POST')
with urllib.request.urlopen(up_req) as resp:
    asset_data = json.loads(resp.read().decode('utf-8'))
    download_url = asset_data.get('browser_download_url')
    print(f"[OK] Asset uploaded successfully! Direct URL: {download_url}")

print("\n=== 5. Updating Firebase Realtime Database ===")
v_data["download_url"] = download_url or f"https://github.com/{REPO}/releases/download/{TAG}/Stargate_Cafe_Update.zip"

fb_url = "https://stargate-experts-default-rtdb.firebaseio.com/cafe_updates/latest.json"
fb_req = urllib.request.Request(
    fb_url,
    data=json.dumps(v_data, ensure_ascii=False).encode('utf-8'),
    headers={'Content-Type': 'application/json'},
    method='PUT'
)
with urllib.request.urlopen(fb_req, timeout=10) as fb_resp:
    print(f"[OK] Firebase cafe_updates updated successfully! Status: {fb_resp.status}")

print("\n=== ALL PUBLISHING STEPS COMPLETED 100% ===")
