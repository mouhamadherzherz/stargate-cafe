import os
import sys
import time
import socket
import threading
import subprocess
import traceback
import shutil
import logger

# Determine base dir
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(BASE_DIR, "STARGATE_STARTUP.log")

def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
            f.flush()
    except Exception:
        pass

log("=== STARGATE STARTING ===")
log(f"sys.executable: {sys.executable}")
log(f"BASE_DIR: {BASE_DIR}")
log(f"frozen: {getattr(sys, 'frozen', False)}")

if getattr(sys, 'frozen', False):
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

try:
    import database
    import accounting
    from app import app, init_db
    log("Imported database, accounting, app successfully")
except BaseException as e:
    log(f"CRITICAL IMPORT ERROR:\n{traceback.format_exc()}")
    sys.exit(1)

def find_free_port(start_port=5000):
    for port in [5000] + list(range(9292, 9492)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return port
        except OSError:
            continue
    return start_port

APP_PORT = find_free_port(5000)
log(f"Selected APP_PORT: {APP_PORT}")

def run_flask(port):
    try:
        log("Calling init_db()...")
        init_db()
        log("init_db() done. Starting app.run()...")
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
    except BaseException as e:
        log(f"Flask crash error:\n{traceback.format_exc()}")

def wait_for_server(port, timeout=5.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.05)
                if s.connect_ex(('127.0.0.1', port)) == 0:
                    return True
        except Exception:
            pass
        time.sleep(0.05)
    return False

def launch_desktop_gui(url):
    app_profile_dir = os.path.join(database.DB_DIR, 'app_profile')
    os.makedirs(app_profile_dir, exist_ok=True)
    # Clear Edge HTTP Cache so updates are always seen immediately
    for cache_sub in [r"Default\Cache", r"Default\Code Cache", r"Default\Service Worker", r"Default\GPUCache"]:
        cache_path = os.path.join(app_profile_dir, cache_sub)
        if os.path.exists(cache_path):
            try:
                shutil.rmtree(cache_path, ignore_errors=True)
            except Exception as e:
                log(f"Failed to clean cache path {cache_path}: {e}")


    edge_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]

    browser_exe = None
    for p in edge_paths:
        if os.path.exists(p):
            browser_exe = p
            break

    if browser_exe:
        cmd = [
            browser_exe,
            f"--user-data-dir={app_profile_dir}",
            f"--app={url}",
            "--window-size=1360,880",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-cache",
            "--disk-cache-size=1"
        ]
        try:
            log(f"Launching browser app mode: {browser_exe}")
            subprocess.Popen(cmd)
            return
        except BaseException as e:
            log(f"Browser launch failed: {e}")

    try:
        import webbrowser
        log(f"Fallback to webbrowser: {url}")
        webbrowser.open(url)
    except BaseException as e:
        log(f"webbrowser fallback failed: {e}")

if __name__ == '__main__':
    try:
        log("Starting server_thread...")
        server_thread = threading.Thread(target=run_flask, args=(APP_PORT,), daemon=True)
        server_thread.start()

        ready = wait_for_server(APP_PORT, timeout=5.0)
        log(f"Server ready: {ready}")

        launch_desktop_gui(f"http://127.0.0.1:{APP_PORT}/employee/login")
        log("GUI launch requested. Entering permanent keep-alive loop.")

        while True:
            time.sleep(5)
    except BaseException as e:
        log(f"FATAL MAIN CRASH:\n{traceback.format_exc()}")
