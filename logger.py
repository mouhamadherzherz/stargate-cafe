# -*- coding: utf-8 -*-
"""
نظام Logging موحد لبرنامج STARGATE Cafe
Centralized logging system with rotation
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

def _get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _get_base_dir()
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

# ──────────────────────────────────────────────
# Formatters
# ──────────────────────────────────────────────
FORMATTER = logging.Formatter(
    '[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def _make_handler(filename, level=logging.DEBUG):
    handler = RotatingFileHandler(
        os.path.join(LOGS_DIR, filename),
        maxBytes=5_000_000,  # 5 MB
        backupCount=5,
        encoding='utf-8'
    )
    handler.setLevel(level)
    handler.setFormatter(FORMATTER)
    return handler

# ──────────────────────────────────────────────
# Console handler (only in dev / non-frozen)
# ──────────────────────────────────────────────
def _make_console_handler():
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(logging.WARNING)
    h.setFormatter(FORMATTER)
    return h

# ──────────────────────────────────────────────
# Root app logger
# ──────────────────────────────────────────────
def get_app_logger() -> logging.Logger:
    """General application logger → logs/app.log"""
    logger = logging.getLogger('stargate.app')
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        logger.addHandler(_make_handler('app.log', logging.INFO))
        logger.addHandler(_make_handler('errors.log', logging.ERROR))
        if not getattr(sys, 'frozen', False):
            logger.addHandler(_make_console_handler())
        logger.propagate = False
    return logger

# ──────────────────────────────────────────────
# Audit logger (financial operations)
# ──────────────────────────────────────────────
_AUDIT_FORMATTER = logging.Formatter(
    '[%(asctime)s] AUDIT | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def get_audit_logger() -> logging.Logger:
    """Audit logger → logs/audit.log  (immutable records)"""
    logger = logging.getLogger('stargate.audit')
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        h = RotatingFileHandler(
            os.path.join(LOGS_DIR, 'audit.log'),
            maxBytes=10_000_000,
            backupCount=10,
            encoding='utf-8'
        )
        h.setLevel(logging.INFO)
        h.setFormatter(_AUDIT_FORMATTER)
        logger.addHandler(h)
        logger.propagate = False
    return logger

# ──────────────────────────────────────────────
# Convenience singleton accessors
# ──────────────────────────────────────────────
app_logger  = get_app_logger()
audit_logger = get_audit_logger()

def log_audit(actor: str, action: str, record_id=None,
              old_value=None, new_value=None, reason: str = '', extra: str = ''):
    """
    Write a structured audit entry.
    Example:
        log_audit('Ahmad', 'DELETE_EXPENSE', record_id=128,
                  old_value='50 USD', reason='Duplicate')
    """
    parts = [
        f"actor={actor!r}",
        f"action={action}",
    ]
    if record_id is not None:
        parts.append(f"id={record_id}")
    if old_value is not None:
        parts.append(f"old={old_value!r}")
    if new_value is not None:
        parts.append(f"new={new_value!r}")
    if reason:
        parts.append(f"reason={reason!r}")
    if extra:
        parts.append(extra)
    audit_logger.info(' | '.join(parts))
