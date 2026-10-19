# -*- coding: utf-8 -*-
"""
نظام النسخ الاحتياطي التلقائي - STARGATE Cafe v6.0
=======================================================
- نسخة احتياطية يومية تلقائية بدون إيقاف السيرفر (SQLite Online Backup API)
- ضغط النسخ بـ ZIP للتوفير في المساحة
- الاحتفاظ بـ 14 نسخة فقط (أسبوعان) مع حذف القديم تلقائياً
- فحص سلامة قاعدة البيانات أسبوعياً (PRAGMA integrity_check)
"""

import os
import sys
import sqlite3
import zipfile
import logging
from datetime import datetime
from pathlib import Path

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False

logger = logging.getLogger('stargate.backup')


def _get_base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_backup_dir() -> str:
    backup_dir = os.path.join(_get_base_dir(), 'data', 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def perform_backup(db_path: str, max_keep: int = 14):
    """نسخة احتياطية بالـ SQLite Online Backup API - لا يوقف السيرفر."""
    try:
        if not os.path.exists(db_path):
            logger.warning("Backup skipped: DB not found at %s", db_path)
            return None

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = get_backup_dir()
        tmp_db_path = os.path.join(backup_dir, f'cafe_backup_{timestamp}.db')
        zip_path = os.path.join(backup_dir, f'cafe_backup_{timestamp}.zip')

        src_conn = sqlite3.connect(db_path, timeout=30.0)
        dst_conn = sqlite3.connect(tmp_db_path)
        with dst_conn:
            src_conn.backup(dst_conn, pages=100)
        dst_conn.close()
        src_conn.close()

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.write(tmp_db_path, f'cafe_backup_{timestamp}.db')

        os.remove(tmp_db_path)
        file_size_kb = os.path.getsize(zip_path) // 1024
        logger.info("Backup created: %s (%d KB)", zip_path, file_size_kb)

        # تنظيف النسخ القديمة
        backups = sorted(Path(backup_dir).glob('cafe_backup_*.zip'),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[max_keep:]:
            old.unlink()
            logger.info("Removed old backup: %s", old.name)

        return zip_path
    except Exception as e:
        logger.exception("Backup FAILED: %s", e)
        return None


def perform_integrity_check(db_path: str) -> bool:
    """فحص سلامة قاعدة البيانات أسبوعياً."""
    try:
        conn = sqlite3.connect(db_path, timeout=15.0)
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.close()
        if result == 'ok' and not fk_issues:
            logger.info("DB integrity check PASSED")
            return True
        logger.error("DB integrity FAILED: %s, FK violations: %d", result, len(fk_issues))
        return False
    except Exception as e:
        logger.exception("Integrity check error: %s", e)
        return False


def _fallback_backup_loop(db_path: str):
    """حلقة احتياطية تعمل بخيط منفصل في حال عدم توفر مكتبة APScheduler."""
    import time
    last_backup_date = None
    logger.info("Starting lightweight native thread backup monitor...")
    while True:
        try:
            now = datetime.now()
            # Perform daily backup if around 03:00 AM or if today's backup not taken
            if now.hour == 3 and last_backup_date != now.date():
                logger.info("Executing automated daily backup via native thread loop...")
                perform_backup(db_path)
                last_backup_date = now.date()
                if now.weekday() == 6:  # Sunday
                    perform_integrity_check(db_path)
        except Exception as err:
            logger.error("Error in fallback backup thread: %s", err)
        time.sleep(300)  # Check every 5 minutes


def start_backup_scheduler(db_path: str):
    """جدولة نسخ احتياطي يومي الساعة 3 صباحاً + فحص أسبوعي."""
    if not HAS_APSCHEDULER:
        logger.info("APScheduler not installed, using resilient daemon thread scheduler instead.")
        import threading
        t = threading.Thread(target=_fallback_backup_loop, args=(db_path,), daemon=True)
        t.start()
        return t

    scheduler = BackgroundScheduler(timezone='Asia/Beirut', daemon=True)

    scheduler.add_job(
        func=lambda: perform_backup(db_path),
        trigger=CronTrigger(hour=3, minute=0),
        id='daily_backup',
        name='STARGATE Daily DB Backup',
        replace_existing=True,
        misfire_grace_time=3600
    )

    scheduler.add_job(
        func=lambda: perform_integrity_check(db_path),
        trigger=CronTrigger(day_of_week='sun', hour=4, minute=0),
        id='weekly_integrity',
        name='STARGATE Weekly DB Integrity Check',
        replace_existing=True,
        misfire_grace_time=3600
    )

    scheduler.start()
    logger.info("Backup scheduler started: daily@03:00, integrity check every Sunday@04:00")
    return scheduler


def get_backup_status(backup_dir=None) -> dict:
    """معلومات آخر نسخة احتياطية."""
    if backup_dir is None:
        backup_dir = get_backup_dir()
    try:
        backups = sorted(Path(backup_dir).glob('cafe_backup_*.zip'),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        if not backups:
            return {'last_backup': None, 'count': 0, 'total_size_kb': 0}
        latest = backups[0]
        total_size = sum(p.stat().st_size for p in backups) // 1024
        last_time = datetime.fromtimestamp(latest.stat().st_mtime)
        return {
            'last_backup': last_time.strftime('%Y-%m-%d %H:%M'),
            'last_backup_file': latest.name,
            'count': len(backups),
            'total_size_kb': total_size
        }
    except Exception as e:
        logger.error("Error reading backup status: %s", e)
        return {'last_backup': None, 'count': 0, 'total_size_kb': 0}
