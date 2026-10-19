
class ProductSalesResult(list):
    """Hybrid list & dict object for complete backwards and forwards compatibility."""
    def __init__(self, rows, **kwargs):
        super().__init__(rows)
        self.products_list = rows
        self.data_dict = {'products_list': rows, **kwargs}
        for k, v in kwargs.items():
            setattr(self, k, v)
    def __getitem__(self, key):
        if isinstance(key, str):
            return self.data_dict.get(key, None)
        return super().__getitem__(key)
    def get(self, key, default=None):
        return self.data_dict.get(key, default)
    def keys(self):
        return self.data_dict.keys()
    def items(self):
        return self.data_dict.items()
    def values(self):
        return self.data_dict.values()


# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import random
import time
import threading
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
import database
from database import get_db, init_db, hash_password, verify_password, _needs_hash_upgrade, write_audit_log
from logger import app_logger as logger

# 🔒 Thread lock to prevent race conditions during concurrent financial ledger entries
_ledger_lock = threading.Lock()


def round_money(amount, currency='USD') -> float:
    """
    Unified central currency rounding:
    - USD: 2 decimal places (0.01)
    - LBP: integer (1)
    """
    if amount is None:
        amount = 0
    try:
        d = Decimal(str(amount))
    except Exception:
        d = Decimal('0')
    if str(currency).upper() in ('USD', '$'):
        return float(d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    return float(d.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def calculate_order_totals(items_list, exchange_rate=89500.0) -> dict:
    """
    Single source of truth for calculating order totals.
    Uses Decimal arithmetic for precision and prevents float drift.
    """
    try:
        rate = Decimal(str(exchange_rate if exchange_rate and float(exchange_rate) > 0 else 89500.0))
    except Exception:
        rate = Decimal('89500')

    total_lbp_dec = Decimal('0')
    processed_items = []

    for it in (items_list or []):
        try:
            raw_q = float(it.get('quantity') or 1.0)
            qty = round(raw_q, 2)
            if qty <= 0:
                qty = 1.0
        except (ValueError, TypeError):
            qty = 1.0

        try:
            price_lbp = Decimal(str(it.get('price_lbp') or 0))
            if price_lbp < Decimal('0'):
                price_lbp = Decimal('0')
        except Exception:
            price_lbp = Decimal('0')

        subtotal_lbp = price_lbp * Decimal(str(qty))
        subtotal_usd = (subtotal_lbp / rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        unit_usd = (price_lbp / rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        total_lbp_dec += subtotal_lbp

        item_copy = dict(it)
        item_copy['quantity'] = qty
        item_copy['price_lbp'] = float(price_lbp)
        item_copy['price_usd'] = float(unit_usd)
        item_copy['subtotal_lbp'] = float(subtotal_lbp)
        item_copy['subtotal_usd'] = float(subtotal_usd)
        processed_items.append(item_copy)

    total_usd_dec = (total_lbp_dec / rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {
        'total_lbp': float(total_lbp_dec),
        'total_usd': float(total_usd_dec),
        'items': processed_items
    }


def get_local_now():
    from datetime import datetime
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def get_business_date(dt=None):
    from datetime import datetime, timedelta
    if dt is None:
        dt = datetime.now()
    if dt.hour < 5:
        dt = dt - timedelta(days=1)
    return dt.strftime('%Y-%m-%d')

_order_seq = 0
_order_seq_lock = threading.Lock()

def generate_order_number(cursor=None):
    """
    توليد رقم فاتورة غير قابل للتكرار إطلاقاً:
    CAF-YYYYMMDD-HHMMSS-SEQ-RAND
    يجمع بين التاريخ والوقت والعداد التسلسلي والتحقق من قاعدة البيانات لمنع أي تضارب (Collision-Proof).
    """
    global _order_seq
    with _order_seq_lock:
        _order_seq += 1
        seq = _order_seq

    now = datetime.now()
    date_str = now.strftime('%Y%m%d')
    time_str = now.strftime('%H%M%S')
    rand_num = random.randint(100, 999)
    order_num = f"CAF-{date_str}-{time_str}-{seq:04d}-{rand_num}"
    if cursor:
        try:
            cursor.execute("SELECT 1 FROM cafe_orders WHERE order_number = ?", (order_num,))
            while cursor.fetchone():
                with _order_seq_lock:
                    _order_seq += 1
                    seq = _order_seq
                order_num = f"CAF-{date_str}-{datetime.now().strftime('%H%M%S')}-{seq:04d}-{random.randint(100, 999)}"
                cursor.execute("SELECT 1 FROM cafe_orders WHERE order_number = ?", (order_num,))
        except Exception as e:
            logger.warning(f"Order number collision check warning: {e}")
    return order_num

# ----------------- SETTINGS -----------------

def get_settings():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM settings WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {
        'company_name': 'STARGATE',
        'currency': 'ل.ل',
        'secondary_currency': '$',
        'exchange_rate': 89500.0,
        'pc_price_per_click_lbp': 100000.0,
        'admin_password': ''
    }

# -------------------------------------------------------------
# 📊 CENTRAL FINANCIAL LEDGER ENGINE (سجل الحركة المالية المركزي)
# -------------------------------------------------------------

def record_financial_ledger_entry(
    entry_type: str,
    source: str,
    destination: str,
    amount_lbp: float = 0.0,
    amount_usd: float = 0.0,
    reference_table: str = None,
    reference_id: int = None,
    user_id: int = None,
    user_name: str = 'النظام',
    notes: str = '',
    exchange_rate: float = None,
    business_date: str = None,
    db_conn = None
) -> int:
    """
    سجل الحركة المالية المركزي المزدوج (Immutable Financial Ledger).
    يسجل حركة الكاش بدقة ويوثق الرصيد اللحظي قبل وبعد كل حركة في الدرج والخزنة.
    محمي بقفل تسلسلي Threading Lock و BEGIN IMMEDIATE لمنع أي تضارب أو Race Condition.
    """
    with _ledger_lock:
        is_external_conn = (db_conn is not None)
        conn = None
        try:
            settings = get_settings()
            rate = exchange_rate or float(settings.get('exchange_rate') or 89500.0)
            bdate = business_date or get_business_date()
            a_lbp = float(amount_lbp or 0.0)
            a_usd = float(amount_usd or 0.0)
            if a_usd <= 0 and a_lbp > 0 and rate > 0:
                a_usd = round(a_lbp / rate, 2)
            elif a_lbp <= 0 and a_usd > 0 and rate > 0:
                a_lbp = round(a_usd * rate, 0)

            if is_external_conn:
                conn = db_conn
            else:
                conn = get_db()
                # Exclusive immediate lock on SQLite database to guarantee atomic sequential balance calculations
                conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()

            # حساب الأرصدة الحالية قبل الحركة
            cursor.execute("""
                SELECT COALESCE(SUM(CASE 
                    WHEN destination = 'drawer' AND status = 'active' THEN amount_lbp 
                    WHEN source = 'drawer' AND status = 'active' THEN -amount_lbp 
                    ELSE 0 END), 0)
                FROM financial_ledger
            """)
            ledger_drawer_row = cursor.fetchone()
            drawer_before = float(ledger_drawer_row[0] or 0.0) if ledger_drawer_row else 0.0

            cursor.execute("""
                SELECT 
                    COALESCE(SUM(CASE 
                        WHEN destination = 'safe' AND status = 'active' THEN amount_lbp 
                        WHEN source = 'safe' AND status = 'active' THEN -amount_lbp 
                        ELSE 0 END), 0) as safe_lbp,
                    COALESCE(SUM(CASE 
                        WHEN destination = 'safe' AND status = 'active' THEN amount_usd 
                        WHEN source = 'safe' AND status = 'active' THEN -amount_usd 
                        ELSE 0 END), 0) as safe_usd
                FROM financial_ledger
            """)
            ledger_safe_row = cursor.fetchone()
            safe_lbp_before = float(ledger_safe_row[0] or 0.0) if ledger_safe_row else 0.0
            safe_usd_before = float(ledger_safe_row[1] or 0.0) if ledger_safe_row else 0.0

            # احتساب الأرصدة بعد العملية
            drawer_after = drawer_before
            if destination == 'drawer':
                drawer_after += a_lbp
            if source == 'drawer':
                drawer_after -= a_lbp

            safe_lbp_after = safe_lbp_before
            safe_usd_after = safe_usd_before
            if destination == 'safe':
                safe_lbp_after += a_lbp
                safe_usd_after += a_usd
            if source == 'safe':
                safe_lbp_after -= a_lbp
                safe_usd_after -= a_usd

            now_str = get_local_now()
            cursor.execute("""
                INSERT INTO financial_ledger (
                    entry_type, source, destination, reference_table, reference_id,
                    amount_lbp, amount_usd, exchange_rate,
                    drawer_balance_before, drawer_balance_after,
                    safe_balance_lbp_before, safe_balance_lbp_after,
                    safe_balance_usd_before, safe_balance_usd_after,
                    user_id, user_name, status, notes, business_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """, (
                entry_type, source, destination, reference_table, reference_id,
                a_lbp, a_usd, rate,
                drawer_before, drawer_after,
                safe_lbp_before, safe_lbp_after,
                safe_usd_before, safe_usd_after,
                user_id, user_name, (notes or '').strip(), bdate, now_str
            ))
            ledger_id = cursor.lastrowid
            if not is_external_conn:
                conn.commit()
                conn.close()
            return ledger_id
        except Exception as e:
            logger.error(f"Error in record_financial_ledger_entry: {e}", exc_info=True)
            if not is_external_conn and conn:
                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass
            if is_external_conn:
                raise
            return 0


def get_financial_ledger_entries(start_date=None, end_date=None, entry_type=None, limit=300):
    """جلب سجل الحركات المالية المركزي مع الفلاتر ودعم التاريخ والنوع."""
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM financial_ledger WHERE 1=1"
    params = []

    if start_date:
        query += " AND DATE(business_date) >= DATE(?)"
        params.append(start_date)
    if end_date:
        query += " AND DATE(business_date) <= DATE(?)"
        params.append(end_date)
    if entry_type and entry_type != 'all':
        query += " AND entry_type = ?"
        params.append(entry_type)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def cancel_financial_ledger_entry(ledger_id: int, cancelled_by: str = 'المدير', reason: str = ''):
    """إلغاء قيد مالي مع تسجيل بيانات الإلغاء وتعديل الأرصدة."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM financial_ledger WHERE id = ?", (ledger_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "القيد المالي غير موجود"
    if row['status'] == 'cancelled':
        conn.close()
        return False, "القيد المالي ملغى مسبقاً"

    now_str = get_local_now()
    cursor.execute("""
        UPDATE financial_ledger
        SET status = 'cancelled', cancelled_by = ?, cancelled_at = ?, cancel_reason = ?
        WHERE id = ?
    """, (cancelled_by, now_str, (reason or 'إلغاء قيد').strip(), ledger_id))
    conn.commit()
    conn.close()

    database.write_audit_log(
        actor=cancelled_by,
        action='CANCEL_LEDGER_ENTRY',
        table_name='financial_ledger',
        record_id=ledger_id,
        reason=reason
    )
    return True, "تم إلغاء القيد المالي بنجاح"


def record_shift_closing(
    business_date: str,
    employee_id: int,
    employee_name: str,
    opening_float_lbp: float = 0.0,
    opening_float_usd: float = 0.0,
    cash_sales_lbp: float = 0.0,
    cash_sales_usd: float = 0.0,
    debt_sales_lbp: float = 0.0,
    debt_collected_lbp: float = 0.0,
    expenses_lbp: float = 0.0,
    safe_transfers_lbp: float = 0.0,
    expected_cash_lbp: float = 0.0,
    actual_cash_lbp: float = 0.0,
    difference_lbp: float = 0.0,
    difference_note: str = '',
    orders_count: int = 0,
    handover_to_employee_name: str = None
):
    """
    تسجيل إغلاق ومطابقة الوردية في سجل shift_closings المحاسبي.
    """
    conn = get_db()
    cursor = conn.cursor()
    now_str = get_local_now()
    cursor.execute("""
        INSERT INTO shift_closings (
            business_date, employee_id, employee_name, closed_at,
            opening_float_lbp, opening_float_usd,
            cash_sales_lbp, cash_sales_usd,
            debt_sales_lbp, debt_collected_lbp,
            expenses_lbp, safe_transfers_lbp,
            expected_cash_lbp, actual_cash_lbp,
            difference_lbp, difference_note, orders_count,
            status, handover_to_employee_name,
            approved_by, approved_at, approval_status,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'closed', ?, ?, ?, 'approved', ?)
    """, (
        business_date, employee_id, employee_name, now_str,
        opening_float_lbp, opening_float_usd,
        cash_sales_lbp, cash_sales_usd,
        debt_sales_lbp, debt_collected_lbp,
        expenses_lbp, safe_transfers_lbp,
        expected_cash_lbp, actual_cash_lbp,
        difference_lbp, difference_note, orders_count,
        handover_to_employee_name,
        employee_name or 'الكاشير', now_str,
        now_str
    ))
    closing_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # إذا وُجد فرق (عجز أو زيادة في النقدية) ننشئ قيد تسوية مزدوج آلي لضبط الصندوق
    if abs(float(difference_lbp or 0.0)) > 0:
        try:
            settings = get_settings()
            rate = float(settings.get('exchange_rate') or 89500.0)
            diff_val = float(difference_lbp)
            diff_u = round(abs(diff_val) / rate, 2) if rate > 0 else 0.0
            if diff_val > 0:
                # زيادة نقدية (Cash Overage - Revenue 4040)
                # مدين: صندوق الكاشير (1010) / دائن: زيادة وفائض الصندوق (4040)
                record_double_entry_journal(
                    description=f"تسوية زيادة نقدية إغلاق وردية ({employee_name}): +{diff_val:,.0f} ل.ل",
                    lines=[
                        {'account_code': '1010', 'debit_lbp': diff_val, 'credit_lbp': 0.0, 'debit_usd': diff_u, 'credit_usd': 0.0, 'memo': 'إثبات الزيادة بصندوق الكاشير'},
                        {'account_code': '4040', 'debit_lbp': 0.0, 'credit_lbp': diff_val, 'debit_usd': 0.0, 'credit_usd': diff_u, 'memo': 'إيراد فائض وزيادة الصندوق'}
                    ],
                    reference_type='shift_closings',
                    reference_id=closing_id,
                    user_name=employee_name
                )
            else:
                # عجز نقدي (Cash Shortage - Expense 5050)
                # مدين: عجز الصندوق وفوارق الجرد (5050) / دائن: صندوق الكاشير (1010)
                abs_diff = abs(diff_val)
                record_double_entry_journal(
                    description=f"تسوية عجز نقدي إغلاق وردية ({employee_name}): -{abs_diff:,.0f} ل.ل",
                    lines=[
                        {'account_code': '5050', 'debit_lbp': abs_diff, 'credit_lbp': 0.0, 'debit_usd': diff_u, 'credit_usd': 0.0, 'memo': 'مصروف عجز وفوارق الصندوق'},
                        {'account_code': '1010', 'debit_lbp': 0.0, 'credit_lbp': abs_diff, 'debit_usd': 0.0, 'credit_usd': diff_u, 'memo': 'تخفيض الصندوق لمطابقة العد الفعلي'}
                    ],
                    reference_type='shift_closings',
                    reference_id=closing_id,
                    user_name=employee_name
                )
        except Exception as eje:
            logger.warning(f"Error creating journal for shift diff: {eje}")

    try:
        log_shift_close(
            employee_id=employee_id,
            employee_name=employee_name,
            total_sales_lbp=cash_sales_lbp + debt_sales_lbp,
            cash_sales_lbp=cash_sales_lbp,
            production_note=f"إغلاق وردية - متوقع: {expected_cash_lbp:,.0f} | فعلي: {actual_cash_lbp:,.0f} | الفرق: {difference_lbp:,.0f} ({difference_note})",
            date=business_date
        )
    except Exception as e:
        logger.warning(f"Error logging shift close legacy: {e}")

    return closing_id


def approve_shift_closing(shift_closing_id: int, approved_by: str = 'المالك', notes: str = ''):
    """
    اعتماد رسمي لإغلاق الوردية ومطابقة الصندوق من قبل المدير أو المالك (Approval Flow).
    """
    conn = get_db()
    cursor = conn.cursor()
    now_str = get_local_now()
    cursor.execute("""
        UPDATE shift_closings
        SET approved_by = ?,
            approved_at = ?,
            approval_status = 'approved',
            approval_notes = ?
        WHERE id = ?
    """, (approved_by, now_str, notes.strip(), shift_closing_id))
    conn.commit()
    conn.close()

    try:
        database.write_audit_log(
            actor=approved_by,
            action='APPROVE_SHIFT_CLOSING',
            table_name='shift_closings',
            record_id=shift_closing_id,
            reason=f"اعتماد تسليم ومطابقة الصندوق للوردية #{shift_closing_id} ({notes})"
        )
    except Exception as e:
        logger.warning(f"Error logging audit for approve shift closing: {e}")

    return True


def get_shift_closings(business_date=None, limit=50):
    """جلب سجلات إغلاق ومطابقة الورديات."""
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM shift_closings WHERE 1=1"
    params = []
    if business_date:
        query += " AND business_date = ?"
        params.append(business_date)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_admin_password_hash():
    """Retrieve hashed admin password from DB."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT admin_password FROM settings WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        if row and row['admin_password']:
            return str(row['admin_password']).strip()
    except Exception:
        pass
    return ''

# Keep backward-compat alias
def get_admin_password():
    return get_admin_password_hash()

def verify_admin_password(entered_pin):
    """Verify entered password against hashed admin password."""
    if not entered_pin:
        return False
    stored = get_admin_password_hash()
    if not stored:
        return False
    return verify_password(entered_pin, stored)

def verify_manager_or_admin_pin(entered_pin):
    """Verify PIN/Password against system admin password OR any active manager/admin employee."""
    if not entered_pin:
        return False
    # Check system admin password
    if verify_admin_password(entered_pin):
        return True
    # Check employees with role 'admin' or 'manager'
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT pin, password FROM employees WHERE role IN ('admin', 'manager') AND is_active = 1")
        rows = cursor.fetchall()
        conn.close()
        for r in rows:
            p = str(r['pin'] or '').strip()
            pw = str(r['password'] or '').strip()
            if p and (p == str(entered_pin).strip() or verify_password(entered_pin, p)):
                return True
            if pw and verify_password(entered_pin, pw):
                return True
    except Exception as e:
        logger.error(f"Error checking manager PIN: {e}")
    return False

def update_admin_password(new_pin):
    """Update admin password (hashed)."""
    new_pin = (new_pin or '').strip()
    if not new_pin or len(new_pin) < 4:
        return False, "يرجى إدخال كلمة سر صحيحة لا تقل عن 4 حروف"
    try:
        hashed = hash_password(new_pin)
        conn = get_db()
        conn.execute(
            "UPDATE settings SET admin_password=?, updated_at=CURRENT_TIMESTAMP WHERE id=1",
            (hashed,)
        )
        conn.commit()
        conn.close()
        return True, "تم تغيير كلمة سر الإدارة بنجاح!"
    except Exception as e:
        return False, f"فشل أثناء تغيير كلمة السر: {e}"

def update_settings(data):
    conn = get_db()
    cursor = conn.cursor()
    company_name = data.get('company_name', 'STARGATE').strip() or 'STARGATE'
    phone = data.get('phone', '').strip()
    rate = float(data.get('exchange_rate') or 89500.0)
    pc_price = float(data.get('pc_price_per_click_lbp') or data.get('pc_session_price_lbp') or 100000.0)

    telegram_enabled = 1 if data.get('telegram_enabled') in (1, '1', True, 'on') else 0
    telegram_bot_token = data.get('telegram_bot_token', '').strip() if 'telegram_bot_token' in data else None
    telegram_chat_id = data.get('telegram_chat_id', '').strip() if 'telegram_chat_id' in data else None

    if telegram_bot_token is not None and telegram_chat_id is not None:
        cursor.execute("""
        UPDATE settings SET
            company_name = ?,
            phone = ?,
            exchange_rate = ?,
            pc_price_per_click_lbp = ?,
            telegram_enabled = ?,
            telegram_bot_token = ?,
            telegram_chat_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """, (company_name, phone, rate, pc_price, telegram_enabled, telegram_bot_token, telegram_chat_id))
    else:
        cursor.execute("""
        UPDATE settings SET
            company_name = ?,
            phone = ?,
            exchange_rate = ?,
            pc_price_per_click_lbp = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """, (company_name, phone, rate, pc_price))
    conn.commit()

    # Also update GAMING item in menu if exists
    cursor.execute("""
    UPDATE cafe_items SET price_lbp = ?, price_usd = ?
    WHERE item_type = 'gaming' OR name LIKE '%GAMING%'
    """, (pc_price, round(pc_price / rate, 2) if rate > 0 else 1.10))
    conn.commit()

    conn.close()
    return True

# ----------------- MENU & CATEGORIES -----------------

def get_categories():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT c.*, COUNT(i.id) as items_count
    FROM cafe_categories c
    LEFT JOIN cafe_items i ON c.id = i.category_id AND i.is_active = 1
    GROUP BY c.id
    ORDER BY c.sort_order ASC, c.id ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def add_category(name, icon='☕', sort_order=0):
    name = (name or '').strip()
    if not name:
        return False, "اسم القسم مطلوب"
    icon = (icon or '☕').strip() or '☕'
    try:
        sort_order = int(sort_order or 0)
    except Exception:
        sort_order = 0
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES (?, ?, ?)", (name, icon, sort_order))
        conn.commit()
        cid = cursor.lastrowid
        conn.close()
        return True, cid
    except Exception as e:
        conn.close()
        return False, f"خطأ أثناء إضافة القسم: {str(e)}"

def update_category(cat_id, name, icon='☕', sort_order=0):
    name = (name or '').strip()
    if not name:
        return False, "اسم القسم مطلوب"
    icon = (icon or '☕').strip() or '☕'
    try:
        sort_order = int(sort_order or 0)
    except Exception:
        sort_order = 0
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE cafe_categories SET name = ?, icon = ?, sort_order = ? WHERE id = ?", (name, icon, sort_order, cat_id))
        conn.commit()
        conn.close()
        return True, "تم تعديل القسم بنجاح"
    except Exception as e:
        conn.close()
        return False, f"خطأ أثناء تعديل القسم: {str(e)}"

def delete_category(cat_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM cafe_categories WHERE id = ?", (cat_id,))
        conn.commit()
        conn.close()
        return True, "تم حذف القسم بنجاح"
    except Exception as e:
        conn.close()
        return False, f"خطأ أثناء حذف القسم: {str(e)}"

def reorder_category(cat_id, direction):
    """تحريك القسم لأعلى أو لأسفل لتغيير ترتيب أزرار الكاشير."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, sort_order FROM cafe_categories ORDER BY sort_order ASC, id ASC")
        cats = [dict(r) for r in cursor.fetchall()]
        
        target_idx = None
        for idx, c in enumerate(cats):
            if c['id'] == cat_id:
                target_idx = idx
                break
                
        if target_idx is None:
            conn.close()
            return False, "القسم غير موجود"
            
        if direction == 'up' and target_idx > 0:
            cats[target_idx], cats[target_idx - 1] = cats[target_idx - 1], cats[target_idx]
        elif direction == 'down' and target_idx < len(cats) - 1:
            cats[target_idx], cats[target_idx + 1] = cats[target_idx + 1], cats[target_idx]
        else:
            conn.close()
            return True, "لم يتغير الترتيب"
            
        for idx, c in enumerate(cats):
            cursor.execute("UPDATE cafe_categories SET sort_order = ? WHERE id = ?", ((idx + 1) * 10, c['id']))
            
        conn.commit()
        conn.close()
        return True, "تم تغيير ترتيب القسم بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)

def save_categories_order(ordered_ids):
    """حفظ ترتيب جميع الأقسام دفعة واحدة."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        for idx, cid in enumerate(ordered_ids):
            try:
                cid = int(cid)
                cursor.execute("UPDATE cafe_categories SET sort_order = ? WHERE id = ?", ((idx + 1) * 10, cid))
            except Exception:
                pass
        conn.commit()
        conn.close()
        return True, "تم حفظ ترتيب الأقسام بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)

def move_item_to_category(item_id, new_category_id):
    """نقل صنف من قسم إلى قسم آخر."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM cafe_categories WHERE id = ?", (new_category_id,))
        if not cursor.fetchone():
            conn.close()
            return False, "القسم المستهدف غير موجود"
        cursor.execute("UPDATE cafe_items SET category_id = ? WHERE id = ?", (new_category_id, item_id))
        conn.commit()
        conn.close()
        return True, "تم نقل الصنف إلى القسم الجديد بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)

def reorder_item(item_id, direction, category_id=None):
    """
    تحريك الصنف للأمام أو للخلف في شاشة الكاشير.
    يعمل بشكل عام وشامل عبر جميع المنتجات المعروضة على شاشة الكاشير،
    بحيث يتمكن الموظف من تقريب أكثر الأصناف مبيعاً وترتيب الشاشة بالشكل المريح له.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, category_id, sort_order FROM cafe_items WHERE id = ?", (item_id,))
        current_item = cursor.fetchone()
        if not current_item:
            conn.close()
            return False, "الصنف غير موجود"

        if category_id:
            cursor.execute("""
                SELECT id FROM cafe_items 
                WHERE category_id = ? AND is_active = 1 AND (item_type IS NULL OR item_type NOT IN ('gaming', 'computer'))
                ORDER BY sort_order ASC, id ASC
            """, (category_id,))
        else:
            cursor.execute("""
                SELECT id FROM cafe_items 
                WHERE is_active = 1 AND (item_type IS NULL OR item_type NOT IN ('gaming', 'computer'))
                ORDER BY sort_order ASC, id ASC
            """)
        items = cursor.fetchall()
        item_ids = [r['id'] for r in items]
        if item_id not in item_ids:
            conn.close()
            return False, "الصنف غير موجود في القائمة النشطة"

        idx = item_ids.index(item_id)
        if direction in ('up', 'left', 'prev', 'forward') and idx > 0:
            item_ids[idx], item_ids[idx - 1] = item_ids[idx - 1], item_ids[idx]
        elif direction in ('down', 'right', 'next', 'backward') and idx < len(item_ids) - 1:
            item_ids[idx], item_ids[idx + 1] = item_ids[idx + 1], item_ids[idx]
        else:
            conn.close()
            return True, "الصنف في أقصى موضع بالفعل"

        for new_idx, i_id in enumerate(item_ids):
            cursor.execute("UPDATE cafe_items SET sort_order = ? WHERE id = ?", ((new_idx + 1) * 10, i_id))

        conn.commit()
        conn.close()
        return True, "تم تحديث ترتيب الصنف بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)

def set_item_sort_order(item_id, sort_order):
    """تحديد رقم ترتيب الصنف مباشرة."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE cafe_items SET sort_order = ? WHERE id = ?", (int(sort_order), item_id))
        conn.commit()
        conn.close()
        return True, "تم حفظ ترتيب الصنف"
    except Exception as e:
        conn.close()
        return False, str(e)

def pin_item_to_top(item_id):
    """تثبيت الصنف في أول شاشة الكاشير في الموضع رقم 1 (المفضلة والأكثر مبيعاً)."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id FROM cafe_items 
            WHERE is_active = 1 AND (item_type IS NULL OR item_type NOT IN ('gaming', 'computer'))
            ORDER BY sort_order ASC, id ASC
        """)
        item_ids = [r['id'] for r in cursor.fetchall() if r['id'] != item_id]
        new_ordered = [item_id] + item_ids
        for new_idx, i_id in enumerate(new_ordered):
            cursor.execute("UPDATE cafe_items SET sort_order = ? WHERE id = ?", ((new_idx + 1) * 10, i_id))
        conn.commit()
        conn.close()
        return True, "تم تثبيت الصنف في مقدمة شاشة الكاشير كأول صنف بنجاح ⭐"
    except Exception as e:
        conn.close()
        return False, str(e)

def auto_sort_items_by_sales():
    """ترتيب أصناف الكاشير تلقائياً حسب الأكثر طلباً ومبيعاً لوضعها في متناول يد الموظف مباشرة."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT i.id, COALESCE(SUM(coi.quantity), 0) as total_sold
            FROM cafe_items i
            LEFT JOIN cafe_order_items coi ON coi.item_id = i.id
            WHERE i.is_active = 1 AND (i.item_type IS NULL OR i.item_type NOT IN ('gaming', 'computer'))
            GROUP BY i.id
            ORDER BY total_sold DESC, i.id ASC
        """)
        rows = cursor.fetchall()
        for new_idx, r in enumerate(rows):
            cursor.execute("UPDATE cafe_items SET sort_order = ? WHERE id = ?", ((new_idx + 1) * 10, r['id']))
        conn.commit()
        conn.close()
        return True, "تم ترتيب الأصناف تلقائياً حسب الأكثر طلباً ومبيعاً ⭐"
    except Exception as e:
        conn.close()
        return False, str(e)

def set_item_exact_position(item_id, target_position):
    """نقل الصنف لموضع محدد بدقة (مثلاً الموضع 1 أو 2 أو 5)."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        target_pos = max(1, int(target_position)) - 1
        cursor.execute("""
            SELECT id FROM cafe_items 
            WHERE is_active = 1 AND (item_type IS NULL OR item_type NOT IN ('gaming', 'computer'))
            ORDER BY sort_order ASC, id ASC
        """)
        item_ids = [r['id'] for r in cursor.fetchall() if r['id'] != item_id]
        if target_pos >= len(item_ids):
            item_ids.append(item_id)
        else:
            item_ids.insert(target_pos, item_id)
        for idx, i_id in enumerate(item_ids):
            cursor.execute("UPDATE cafe_items SET sort_order = ? WHERE id = ?", ((idx + 1) * 10, i_id))
        conn.commit()
        conn.close()
        return True, f"تم نقل الصنف إلى الموضع {target_pos + 1} بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)


def get_top_selling_items(limit=12):
    """جلب أكثر الأصناف طلباً ومبيعاً تلقائياً لوضعها في متناول يد الكاشير."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.*, c.name as category_name, c.icon as category_icon, 
               COALESCE(SUM(coi.quantity), 0) as total_sold
        FROM cafe_items i
        JOIN cafe_categories c ON i.category_id = c.id
        LEFT JOIN cafe_order_items coi ON coi.item_id = i.id
        WHERE i.is_active = 1 AND i.item_type != 'gaming' AND i.item_type != 'computer'
        GROUP BY i.id
        ORDER BY total_sold DESC, i.sort_order ASC, i.name ASC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def toggle_coffee_bean_link(item_id):
    """تبديل حالة ربط الصنف بكيلو البن (يخصم / لا يخصم من كيس البن)."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name, is_coffee_bean_linked FROM cafe_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "الصنف غير موجود"
        current = int(row['is_coffee_bean_linked'] or 0)
        new_val = 0 if current == 1 else 1
        if new_val == 1:
            cursor.execute("UPDATE cafe_items SET is_coffee_bean_linked = 1, track_stock = 0, stock_qty = 0 WHERE id = ?", (item_id,))
        else:
            cursor.execute("UPDATE cafe_items SET is_coffee_bean_linked = 0 WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()
        return True, new_val
    except Exception as e:
        conn.close()
        return False, str(e)

def get_categories_with_items():
    """جلب جميع الأقسام مع الأصناف التابعة لها لإدارة التصنيفات."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cafe_categories ORDER BY sort_order ASC, id ASC")
    categories = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("""
        SELECT i.*, c.name as category_name
        FROM cafe_items i
        LEFT JOIN cafe_categories c ON i.category_id = c.id
        ORDER BY i.sort_order ASC, i.name ASC
    """)
    all_items = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    items_by_cat = {}
    for item in all_items:
        cid = item.get('category_id')
        if cid not in items_by_cat:
            items_by_cat[cid] = []
        items_by_cat[cid].append(item)
        
    for cat in categories:
        prods = items_by_cat.get(cat['id'], [])
        cat['products'] = prods
        cat['items'] = prods
        cat['items_count'] = len(prods)
        
    return categories

def get_item(item_id):
    """Fetch a single item by its ID with category metadata."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT i.*, c.name as category_name, c.icon as category_icon
    FROM cafe_items i
    LEFT JOIN cafe_categories c ON i.category_id = c.id
    WHERE i.id = ?
    """, (item_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_items(category_id=None, active_only=True):
    conn = get_db()
    cursor = conn.cursor()
    query = """
    SELECT i.*, c.name as category_name, c.icon as category_icon
    FROM cafe_items i
    JOIN cafe_categories c ON i.category_id = c.id
    WHERE 1=1
    """
    params = []
    if active_only:
        query += " AND i.is_active = 1"
    if category_id:
        query += " AND i.category_id = ?"
        params.append(category_id)
    query += " ORDER BY (CASE WHEN i.item_type = 'gaming' THEN 0 ELSE 1 END), i.sort_order ASC, c.sort_order ASC, i.name ASC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

COFFEE_KEYWORDS = (
    'قهوة', 'قهوه', 'قهوة تركي', 'قهوه تركي', 'بن تركي', 'قهوة دوبل', 'قهوة سادة', 'قهوة وسط', 'قهوة حلوة'
)

def normalize_arabic_coffee_text(text: str) -> str:
    if not text:
        return ''
    t = str(text).lower()
    t = t.replace('إ', 'ا').replace('أ', 'ا').replace('آ', 'ا')
    t = t.replace('ة', 'ه').replace('ى', 'ي')
    return t

def is_coffee_item(item_name: str, category_name: str = '', item_id: int = None) -> bool:
    """
    Check if an item deducts from the coffee beans (kilo bag).
    Source of truth is ALWAYS `cafe_items.is_coffee_bean_linked` set explicitly by the owner.
    If the item exists in cafe_items with is_coffee_bean_linked specified, that setting is absolute.
    Strictly coffee only — cappuccino, espresso, latte and other drinks are never deducted from coffee bag.
    """
    if item_id:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT is_coffee_bean_linked FROM cafe_items WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            conn.close()
            if row and row['is_coffee_bean_linked'] is not None:
                return bool(row['is_coffee_bean_linked'] == 1)
        except Exception as e:
            logger.warning(f"Error checking is_coffee_bean_linked for item_id {item_id}: {e}")

    if not item_name:
        return False

    clean_name = item_name.strip()

    # Check database by name if item exists
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT is_coffee_bean_linked FROM cafe_items WHERE LOWER(TRIM(name)) = LOWER(TRIM(?)) LIMIT 1", (clean_name,))
        row = cursor.fetchone()
        conn.close()
        if row and row['is_coffee_bean_linked'] is not None:
            return bool(row['is_coffee_bean_linked'] == 1)
    except Exception as e:
        logger.warning(f"Error checking is_coffee_bean_linked by name {clean_name}: {e}")

    # Fallback ONLY for legacy or unlinked ad-hoc items not yet in cafe_items table:
    name_norm = normalize_arabic_coffee_text(clean_name)
    # Strictly exclude Cappuccino, Espresso, Latte, Nescafe, sachets, tea, cold drinks, sweets, cakes
    if any(ex in name_norm for ex in ('3 in 1', '3in1', '3  1', 'ظرف', 'ساشيه', 'علبه', 'كابتشينو', 'كبتشينو', 'اسبريسو', 'إسبريسو', 'نسكافيه', 'لاتيه', 'موكا', 'شاي', 'عصير', 'بيبسي', 'سفن', 'مياه', 'كيك', 'حلو', 'بسكوت', 'شوكولا')):
        return False

    norm_keywords = [normalize_arabic_coffee_text(kw) for kw in COFFEE_KEYWORDS]
    return any(kw in name_norm for kw in norm_keywords)

def add_item(data):
    name = data.get('name', '').strip()
    category_id = data.get('category_id')
    price_lbp = float(data.get('price_lbp') or 0)
    price_usd = float(data.get('price_usd') or 0)
    icon = data.get('icon', '☕').strip() or '☕'
    item_type = data.get('item_type', 'cafe').strip() or 'cafe'
    sort_order = int(data.get('sort_order') or 0)
    stock_qty = float(data.get('stock_qty') or 0.0) if data.get('stock_qty') not in (None, '') else 0.0
    # Automatic inventory tracking: ALWAYS 1 unless explicitly set to 0 or item_type is 'gaming'
    track_stock = 0 if item_type == 'gaming' else 1
    if 'track_stock' in data and data.get('track_stock') in (0, '0', False):
        track_stock = 0
    low_stock_limit = float(data.get('low_stock_limit') or 5.0)
    is_coffee_bean_linked = 1 if data.get('is_coffee_bean_linked') in (1, '1', True, 'on') else 0

    # If linked to coffee beans kilo bag, it is tracked via coffee beans batch, not cups
    if is_coffee_bean_linked == 1:
        stock_qty = 0.0
        track_stock = 0

    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    if price_lbp == 0 and price_usd > 0 and rate > 0:
        price_lbp = round(price_usd * rate, 0)
    elif price_usd == 0 and price_lbp > 0 and rate > 0:
        price_usd = round(price_lbp / rate, 2)

    wholesale_price_lbp = float(data.get('wholesale_price_lbp') or 0.0)
    wholesale_price_usd = float(data.get('wholesale_price_usd') or 0.0)
    if wholesale_price_lbp > 0 and wholesale_price_usd == 0 and rate > 0:
        wholesale_price_usd = round(wholesale_price_lbp / rate, 2)
    elif wholesale_price_usd > 0 and wholesale_price_lbp == 0 and rate > 0:
        wholesale_price_lbp = round(wholesale_price_usd * rate, 0)

    cost_price_lbp = float(data.get('cost_price_lbp') or 0.0)
    cost_price_usd = float(data.get('cost_price_usd') or 0.0)
    if cost_price_lbp > 0 and cost_price_usd == 0 and rate > 0:
        cost_price_usd = round(cost_price_lbp / rate, 2)
    elif cost_price_usd > 0 and cost_price_lbp == 0 and rate > 0:
        cost_price_lbp = round(cost_price_usd * rate, 0)

    if not name or not category_id:
        return False, "اسم الصنف والتصنيف مطلوبان"

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, icon, item_type, sort_order, is_active, stock_qty, track_stock, low_stock_limit, wholesale_price_lbp, wholesale_price_usd, cost_price_lbp, cost_price_usd, is_coffee_bean_linked)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (category_id, name, price_lbp, price_usd, icon, item_type, sort_order, stock_qty, track_stock, low_stock_limit, wholesale_price_lbp, wholesale_price_usd, cost_price_lbp, cost_price_usd, is_coffee_bean_linked))
        conn.commit()
        iid = cursor.lastrowid
        conn.close()
        return True, iid
    except Exception as e:
        conn.close()
        return False, str(e)

def update_item(item_id, data):
    existing = get_item(item_id)
    name = data.get('name', '').strip()
    if not name and existing:
        name = existing.get('name', '')
    category_id = data.get('category_id') or (existing.get('category_id') if existing else None)
    price_lbp = float(data.get('price_lbp') or 0)
    price_usd = float(data.get('price_usd') or 0)
    icon = data.get('icon', '').strip()
    if not icon:
        icon = existing.get('icon') if existing and existing.get('icon') else '☕'
    item_type = data.get('item_type', '').strip() or (existing.get('item_type') if existing else 'cafe') or 'cafe'
    sort_order = int(data.get('sort_order') if 'sort_order' in data else (existing.get('sort_order', 0) if existing else 0))
    # CRITICAL FIX: Preserve is_active if omitted in edit forms so product never disappears
    if 'is_active' in data:
        is_active = 1 if data.get('is_active') in (1, '1', True, 'on') else 0
    else:
        is_active = existing.get('is_active', 1) if existing else 1
    stock_qty = float(data.get('stock_qty') or 0.0) if 'stock_qty' in data and data.get('stock_qty') not in (None, '') else None
    # Auto track stock if not gaming
    if item_type == 'gaming':
        track_stock = 0
    elif 'track_stock' in data:
        track_stock = 0 if data.get('track_stock') in (0, '0', False) else 1
    else:
        track_stock = existing.get('track_stock', 1) if existing else 1
    low_stock_limit = float(data.get('low_stock_limit') or 5.0) if 'low_stock_limit' in data else (existing.get('low_stock_limit', 5.0) if existing else 5.0)
    is_coffee_bean_linked = (1 if data.get('is_coffee_bean_linked') in (1, '1', True, 'on') else 0) if 'is_coffee_bean_linked' in data else (existing.get('is_coffee_bean_linked', 0) if existing else 0)

    # Coffee bean linked items protection
    if is_coffee_bean_linked == 1:
        if stock_qty is not None:
            stock_qty = 0.0
        track_stock = 0

    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    if price_lbp == 0 and price_usd > 0 and rate > 0:
        price_lbp = round(price_usd * rate, 0)
    elif price_usd == 0 and price_lbp > 0 and rate > 0:
        price_usd = round(price_lbp / rate, 2)

    wholesale_price_lbp = float(data.get('wholesale_price_lbp') or 0.0)
    wholesale_price_usd = float(data.get('wholesale_price_usd') or 0.0)
    if wholesale_price_lbp > 0 and wholesale_price_usd == 0 and rate > 0:
        wholesale_price_usd = round(wholesale_price_lbp / rate, 2)
    elif wholesale_price_usd > 0 and wholesale_price_lbp == 0 and rate > 0:
        wholesale_price_lbp = round(wholesale_price_usd * rate, 0)

    cost_price_lbp = float(data.get('cost_price_lbp') or 0.0)
    cost_price_usd = float(data.get('cost_price_usd') or 0.0)
    if cost_price_lbp > 0 and cost_price_usd == 0 and rate > 0:
        cost_price_usd = round(cost_price_lbp / rate, 2)
    elif cost_price_usd > 0 and cost_price_lbp == 0 and rate > 0:
        cost_price_lbp = round(cost_price_usd * rate, 0)

    conn = get_db()
    cursor = conn.cursor()
    try:
        if stock_qty is not None and track_stock is not None:
            cursor.execute("""
            UPDATE cafe_items SET
                category_id = ?,
                name = ?,
                price_lbp = ?,
                price_usd = ?,
                icon = ?,
                item_type = ?,
                sort_order = ?,
                is_active = ?,
                stock_qty = ?,
                track_stock = ?,
                low_stock_limit = ?,
                wholesale_price_lbp = ?,
                wholesale_price_usd = ?,
                cost_price_lbp = ?,
                cost_price_usd = ?,
                is_coffee_bean_linked = COALESCE(?, is_coffee_bean_linked)
            WHERE id = ?
            """, (category_id, name, price_lbp, price_usd, icon, item_type, sort_order, is_active, stock_qty, track_stock, low_stock_limit, wholesale_price_lbp, wholesale_price_usd, cost_price_lbp, cost_price_usd, is_coffee_bean_linked, item_id))
        else:
            cursor.execute("""
            UPDATE cafe_items SET
                category_id = ?,
                name = ?,
                price_lbp = ?,
                price_usd = ?,
                icon = ?,
                item_type = ?,
                sort_order = ?,
                is_active = ?,
                wholesale_price_lbp = ?,
                wholesale_price_usd = ?,
                cost_price_lbp = ?,
                cost_price_usd = ?,
                is_coffee_bean_linked = COALESCE(?, is_coffee_bean_linked)
            WHERE id = ?
            """, (category_id, name, price_lbp, price_usd, icon, item_type, sort_order, is_active, wholesale_price_lbp, wholesale_price_usd, cost_price_lbp, cost_price_usd, is_coffee_bean_linked, item_id))
        conn.commit()
        conn.close()
        return True, "تم التعديل بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)

def delete_item(item_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cafe_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return True

# ----------------- CAFÉ POS ORDERS & OPEN CUSTOMER TABS (الزبائن الجالسون) -----------------

def create_order(order_data, items_list, tab_id=None):
    """Create a paid or debt order or checkout & pay an existing open customer tab."""
    if not items_list:
        return False, "الفاتورة فارغة"

    # Whitelist payment methods (رفض أي طريقة دفع غير معروفة)
    payment_method = str(order_data.get('payment_method') or 'cash').strip().lower()
    allowed_payment_methods = {'cash', 'debt', 'card', 'split'}
    if payment_method not in allowed_payment_methods:
        return False, f"طريقة دفع غير صالحة ({payment_method}). الطرق المعتمدة: نقداً (cash)، آجل/دين (debt)، بطاقة مصرفية (card)."

    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    conn = get_db()
    cursor = conn.cursor()

    try:
        # 0. Server-side Idempotency Verification (منع تكرار الفواتير والطلبات عند النقر المكرر أو انقطاع الشبكة)
        idempotency_key = (order_data.get('idempotency_key') or '').strip()
        if idempotency_key:
            cursor.execute("""
                SELECT id, order_number, subtotal_lbp, discount_lbp, discount_percent, discount_reason,
                       total_lbp, total_usd, payment_method, status
                FROM cafe_orders WHERE idempotency_key = ?
            """, (idempotency_key,))
            existing = cursor.fetchone()
            if existing:
                conn.close()
                return True, {
                    'order_id': existing['id'],
                    'order_number': existing['order_number'],
                    'subtotal_lbp': existing['subtotal_lbp'],
                    'discount_lbp': existing['discount_lbp'],
                    'discount_percent': existing['discount_percent'],
                    'discount_reason': existing['discount_reason'],
                    'total_lbp': existing['total_lbp'],
                    'total_usd': existing['total_usd'],
                    'payment_method': existing['payment_method'],
                    'is_duplicate': True
                }

        # 1. Server-side authoritative item verification (منع التلاعب بالأسعار من المتصفح)
        is_wholesale = 1 if order_data.get('is_wholesale') in (1, '1', True, 'true') else 0
        validated_items = []
        for it in items_list:
            item_id = it.get('item_id')
            try:
                raw_q = float(it.get('quantity') or 1.0)
                q = round(raw_q, 2)
                if q <= 0:
                    q = 1.0
            except (ValueError, TypeError):
                q = 1.0
            it_is_ws = 1 if (it.get('is_wholesale') or is_wholesale) else 0

            if item_id:
                cursor.execute("""
                    SELECT id, name, price_lbp, cost_price_lbp, cost_price_usd,
                           wholesale_price_lbp, track_stock, stock_qty, is_active
                    FROM cafe_items WHERE id = ?
                """, (item_id,))
                db_item = cursor.fetchone()
                if not db_item:
                    conn.close()
                    return False, f"الصنف المحدد غير موجود في قاعدة البيانات (معرّف: {item_id})"
                if db_item['is_active'] != 1:
                    conn.close()
                    return False, f"الصنف ({db_item['name']}) غير متاح أو متوقف عن البيع حالياً"

                # استخدام السعر الرسمي المعتمد من الخادم فقط
                if it_is_ws and db_item['wholesale_price_lbp'] and float(db_item['wholesale_price_lbp']) > 0:
                    auth_price_lbp = float(db_item['wholesale_price_lbp'])
                else:
                    auth_price_lbp = float(db_item['price_lbp'] or 0.0)

                validated_items.append({
                    'item_id': db_item['id'],
                    'name': db_item['name'],
                    'quantity': q,
                    'price_lbp': auth_price_lbp,
                    'is_wholesale': it_is_ws,
                    'track_stock': db_item['track_stock'],
                    'stock_qty': float(db_item['stock_qty'] or 0.0),
                    'cost_price_lbp': float(db_item['cost_price_lbp'] or 0.0),
                    'cost_price_usd': float(db_item['cost_price_usd'] or 0.0),
                    'item_type': it.get('item_type') or 'cafe'
                })
            else:
                # أصناف مخصصة أو جلسات ألعاب بدون item_id
                custom_price = max(0.0, float(it.get('price_lbp') or 0.0))
                validated_items.append({
                    'item_id': None,
                    'name': it.get('name', 'صنف مخصص'),
                    'quantity': q,
                    'price_lbp': custom_price,
                    'is_wholesale': 0,
                    'track_stock': 0,
                    'stock_qty': 9999.0,
                    'cost_price_lbp': 0.0,
                    'cost_price_usd': 0.0,
                    'item_type': it.get('item_type') or 'others'
                })

        # Calculate totals centrally using Decimal precision with server-validated prices
        calc = calculate_order_totals(validated_items, rate)
        subtotal_lbp = calc['total_lbp']
        subtotal_usd = calc['total_usd']
        computed_items = calc['items']

        # Process discounts by currency amount first (حسم نقدي بالعملة)
        discount_lbp = float(order_data.get('discount_lbp') or 0.0)
        discount_usd = float(order_data.get('discount_usd') or 0.0)
        discount_percent = float(order_data.get('discount_percent') or 0.0)
        discount_reason = (order_data.get('discount_reason') or '').strip()

        if discount_lbp > 0:
            discount_usd = round(discount_lbp / rate, 2) if rate > 0 else 0.0
            discount_percent = round((discount_lbp / subtotal_lbp) * 100, 1) if subtotal_lbp > 0 else 0.0
        elif discount_usd > 0:
            discount_lbp = round(discount_usd * rate, 0)
            discount_percent = round((discount_lbp / subtotal_lbp) * 100, 1) if subtotal_lbp > 0 else 0.0
        elif discount_percent > 0:
            if discount_percent > 100.0:
                discount_percent = 100.0
            discount_lbp = round(subtotal_lbp * (discount_percent / 100.0), 0)
            discount_usd = round(subtotal_usd * (discount_percent / 100.0), 2)

        discount_lbp = min(discount_lbp, subtotal_lbp)
        discount_usd = min(discount_usd, subtotal_usd)
        total_lbp = max(0.0, subtotal_lbp - discount_lbp)
        total_usd = max(0.0, subtotal_usd - discount_usd)

        customer_name = (order_data.get('customer_name') or '').strip() or 'زبون كاش'
        notes = order_data.get('notes', '')
        paid_amount = total_lbp if payment_method in ('cash', 'card') else 0.0

        # 2. Check stock availability & Coffee Bag Batch BEFORE starting transaction
        coffee_items_found = []
        for it in computed_items:
            i_id = it.get('item_id')
            i_name = it.get('name', 'صنف')
            if is_coffee_item(i_name, item_id=i_id):
                coffee_items_found.append(i_name)

        if coffee_items_found:
            cursor.execute("SELECT id, batch_code FROM coffee_bag_batches WHERE status = 'active' ORDER BY id DESC LIMIT 1")
            act_b_check = cursor.fetchone()
            if not act_b_check:
                conn.close()
                first_coffee = coffee_items_found[0]
                return False, f"⚠️ لا يمكن إتمام الطلب! الصنف ({first_coffee}) مرتبط بحبوب البن، ولا يوجد كيلو قهوة مفتوح حالياً في المحل. يجب فتح كيلو جديد أولاً من زر 'فتح كيلو ☕' في قسم القهوة."

        # Stock Guard: Only enforce availability on tracked products (track_stock == 1)
        for it in computed_items:
            item_id = it.get('item_id')
            item_name = it.get('name', 'صنف')
            item_type = it.get('item_type') or 'cafe'
            q = float(it.get('quantity') or 1.0)
            if item_id and item_type != 'gaming' and not is_coffee_item(item_name, item_id=item_id):
                cursor.execute("SELECT stock_qty, name, track_stock FROM cafe_items WHERE id = ?", (item_id,))
                st_row = cursor.fetchone()
                if st_row and int(st_row['track_stock'] or 0) == 1:
                    available = float(st_row['stock_qty'] or 0.0)
                    if available <= 0:
                        conn.close()
                        return False, f"⚠️ لا يمكن إتمام الطلب! الصنف ({st_row['name']}) غير مجرود أو رصيده (0) في المخزن. يمنع بيع أي منتج غير متوفر لحماية الجرد."
                    elif available < q:
                        conn.close()
                        return False, f"⚠️ الكمية المطلوبة ({q}) غير متوفرة في المخزون للمنتج: {st_row['name']} (المتوفر حالياً بالمحل: {int(available) if available.is_integer() else available} فقط)."

        # Read previously recorded item batch IDs if settling an open tab
        tab_item_batches = {}
        if tab_id:
            try:
                cursor.execute("SELECT item_id, item_name, coffee_batch_id FROM cafe_order_items WHERE order_id = ? AND coffee_batch_id IS NOT NULL", (tab_id,))
                for tb in cursor.fetchall():
                    key = tb['item_id'] or tb['item_name']
                    tab_item_batches[key] = tb['coffee_batch_id']
            except Exception:
                pass

        # 3. BEGIN ATOMIC TRANSACTION
        conn.execute("BEGIN IMMEDIATE")

        emp_id = order_data.get('employee_id')
        emp_name = order_data.get('employee_name', 'كاشير')
        order_type = order_data.get('order_type', 'takeaway')
        table_number = order_data.get('table_number', '') or order_data.get('dining_table_name', '')
        order_status = order_data.get('status', 'paid')

        if tab_id:
            # 1. استرجاع مؤقت لرصيد الطاولة المفتوحة لتطبيق الخصم النهائي للفاتورة بدقة ومنع التكرار
            cursor.execute("SELECT item_id, item_name, quantity FROM cafe_order_items WHERE order_id = ?", (tab_id,))
            old_tab_items = cursor.fetchall()
            for ot in old_tab_items:
                ot_id = ot['item_id']
                ot_q = float(ot['quantity'] or 0.0)
                if ot_id and not is_coffee_item(ot['item_name'], item_id=ot_id):
                    cursor.execute("UPDATE cafe_items SET stock_qty = stock_qty + ? WHERE id = ? AND track_stock = 1", (ot_q, ot_id))

            cursor.execute("""
            UPDATE cafe_orders SET
                customer_name = ?,
                total_lbp = ?,
                total_usd = ?,
                paid_amount = ?,
                payment_method = ?,
                notes = ?,
                status = ?,
                is_tab = 0,
                is_wholesale = ?,
                order_type = COALESCE(?, order_type, 'takeaway'),
                dining_table_name = COALESCE(?, dining_table_name, ''),
                employee_id = COALESCE(?, employee_id),
                employee_name = COALESCE(?, employee_name),
                created_at = ?
            WHERE id = ?
            """, (customer_name, total_lbp, total_usd, paid_amount, payment_method, notes, order_status, is_wholesale, order_type, table_number, emp_id, emp_name, get_local_now(), tab_id))
            order_id = tab_id
            cursor.execute("SELECT order_number, tracking_number FROM cafe_orders WHERE id = ?", (order_id,))
            row = cursor.fetchone()
            order_num = row['order_number'] if row and row['order_number'] else generate_order_number()
            tracking_number = row['tracking_number'] if row and row['tracking_number'] else f"TRK-{get_local_now().replace('-', '')[2:8]}-{tab_id:04d}"
            cursor.execute("UPDATE cafe_orders SET tracking_number = COALESCE(tracking_number, ?) WHERE id = ?", (tracking_number, tab_id))
            cursor.execute("DELETE FROM cafe_order_items WHERE order_id = ?", (order_id,))
        else:
            order_num = generate_order_number()
            tracking_number = f"TRK-{get_local_now().replace('-', '')[2:8]}-{random.randint(1000, 9999)}"
            cursor.execute("""
            INSERT INTO cafe_orders (order_number, total_lbp, total_usd, paid_amount, payment_method, customer_name, notes, status, is_tab, employee_id, employee_name, is_wholesale, order_type, dining_table_name, idempotency_key, tracking_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_num, total_lbp, total_usd, paid_amount, payment_method, customer_name, notes, order_status, emp_id, emp_name, is_wholesale, order_type, table_number, idempotency_key or None, tracking_number, get_local_now()))
            order_id = cursor.lastrowid

        # حفظ تفاصيل المجموع قبل الخصم والخصم وسببه
        cursor.execute("""
            UPDATE cafe_orders SET subtotal_lbp = ?, subtotal_usd = ?, discount_lbp = ?, discount_usd = ?,
                   discount_percent = ?, discount_reason = ?
            WHERE id = ?
        """, (subtotal_lbp, subtotal_usd, discount_lbp, discount_usd, discount_percent, discount_reason, order_id))

        total_order_cogs_lbp = 0.0
        _net_ratio = (total_lbp / subtotal_lbp) if subtotal_lbp > 0 else 1.0
        coffee_batches_allocation = {}

        # Get latest active batch id as default fallback
        cursor.execute("SELECT id FROM coffee_bag_batches WHERE status = 'active' ORDER BY id DESC LIMIT 1")
        latest_act_row = cursor.fetchone()
        latest_act_id = latest_act_row['id'] if latest_act_row else None

        for it in computed_items:
            item_id = it.get('item_id')
            item_name = it.get('name', 'صنف')
            item_type = it.get('item_type') or ('gaming' if 'gaming' in item_name.lower() or 'ألعاب' in item_name or 'كمبيوتر' in item_name else ('others' if it.get('is_custom') or not item_id else 'cafe'))
            q = it['quantity']
            u_lbp = it['price_lbp']
            u_usd = it['price_usd']
            sub_lbp = it['subtotal_lbp']
            sub_usd = it['subtotal_usd']
            item_is_wholesale = 1 if (it.get('is_wholesale') or is_wholesale) else 0

            # Coffee batch tracking
            item_is_coffee_bean_linked = is_coffee_item(item_name, item_id=item_id)
            target_batch_id = None
            if item_is_coffee_bean_linked:
                key = item_id or item_name
                target_batch_id = tab_item_batches.get(key) or latest_act_id
                if target_batch_id:
                    if target_batch_id not in coffee_batches_allocation:
                        coffee_batches_allocation[target_batch_id] = {'cups': 0, 'rev_lbp': 0.0, 'rev_usd': 0.0}
                    coffee_batches_allocation[target_batch_id]['cups'] += q
                    coffee_batches_allocation[target_batch_id]['rev_lbp'] += sub_lbp * _net_ratio
                    coffee_batches_allocation[target_batch_id]['rev_usd'] += sub_usd * _net_ratio

            unit_cogs_lbp = 0.0
            unit_cogs_usd = 0.0

            # Deduct stock for finalized sales
            if item_is_coffee_bean_linked:
                pass
            elif item_id:
                # 1. Direct finished goods stock deduction
                cursor.execute("SELECT stock_qty, name, track_stock, cost_price_lbp, cost_price_usd FROM cafe_items WHERE id = ?", (item_id,))
                cur_item_row = cursor.fetchone()
                if cur_item_row:
                    q_before = float(cur_item_row['stock_qty'] or 0.0)
                    q_after = max(0.0, q_before - q)
                    cursor.execute("UPDATE cafe_items SET stock_qty = ? WHERE id = ?", (q_after, item_id))
                    
                    try:
                        cursor.execute("""
                            INSERT INTO stock_movements (
                                movement_type, item_type, item_id, item_name, quantity,
                                qty_before, qty_after, reference_type, reference_id,
                                user_name, notes
                            ) VALUES ('SALE_OUT', 'cafe_item', ?, ?, ?, ?, ?, 'cafe_orders', ?, ?, ?)
                        """, (item_id, item_name, q, q_before, q_after, order_id, emp_name, f"مبيع فاتورة #{order_num}"))
                    except Exception:
                        pass

                # 2. Recipe Consumption & Raw Material Stock Deduction
                cursor.execute("""
                    SELECT r.required_qty, r.unit as recipe_unit, i.id as inv_id, i.name as raw_name,
                           i.stock_qty as raw_stock, i.cost_per_unit
                    FROM recipes r
                    JOIN inventory i ON r.inventory_id = i.id
                    WHERE r.cafe_item_id = ?
                """, (item_id,))
                raw_recipes = cursor.fetchall()
                if raw_recipes:
                    item_recipe_cogs = 0.0
                    for rec in raw_recipes:
                        consumed_qty = float(rec['required_qty'] or 0.0) * q
                        raw_id = rec['inv_id']
                        raw_before = float(rec['raw_stock'] or 0.0)
                        raw_after = round(raw_before - consumed_qty, 4)
                        cost_unit = float(rec['cost_per_unit'] or 0.0)
                        total_cogs = consumed_qty * cost_unit
                        item_recipe_cogs += total_cogs
                        total_order_cogs_lbp += total_cogs

                        cursor.execute("UPDATE inventory SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (raw_after, raw_id))
                        movement_note = f"استهلاك مبيع ({q} {item_name})"
                        if raw_after < 0:
                            movement_note += f" [⚠️ عجز مخزون: {abs(raw_after)}]"
                        try:
                            cursor.execute("""
                                INSERT INTO stock_movements (
                                    movement_type, item_type, item_id, item_name, quantity,
                                    qty_before, qty_after, unit_cost_lbp, total_cost_lbp,
                                    reference_type, reference_id, user_name, notes
                                ) VALUES ('RECIPE_CONSUMPTION', 'inventory', ?, ?, ?, ?, ?, ?, ?, 'cafe_orders', ?, ?, ?)
                            """, (raw_id, rec['raw_name'], consumed_qty, raw_before, raw_after, cost_unit, total_cogs, order_id, emp_name, movement_note))
                        except Exception:
                            pass
                    unit_cogs_lbp = round(item_recipe_cogs / q, 2) if q > 0 else 0.0
                    unit_cogs_usd = round(unit_cogs_lbp / rate, 4) if rate > 0 else 0.0
                elif cur_item_row:
                    # COGS for standalone finished goods (بدون وصفة خام)
                    unit_cogs_lbp = float(cur_item_row['cost_price_lbp'] or 0.0)
                    unit_cogs_usd = float(cur_item_row['cost_price_usd'] or 0.0)
                    if unit_cogs_usd <= 0 and unit_cogs_lbp > 0 and rate > 0:
                        unit_cogs_usd = round(unit_cogs_lbp / rate, 4)
                    total_order_cogs_lbp += (unit_cogs_lbp * q)

            cursor.execute("""
            INSERT INTO cafe_order_items (order_id, item_id, item_name, item_type, quantity, unit_price_lbp, unit_price_usd, subtotal_lbp, subtotal_usd, is_wholesale, coffee_batch_id, unit_cost_lbp, unit_cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, item_id, item_name, item_type, q, u_lbp, u_usd, sub_lbp, sub_usd, item_is_wholesale, target_batch_id, unit_cogs_lbp, unit_cogs_usd))

        # Update order total cost in cafe_orders
        if total_order_cogs_lbp > 0:
            total_order_cogs_usd = round(total_order_cogs_lbp / rate, 2) if rate > 0 else 0.0
            cursor.execute("UPDATE cafe_orders SET total_cost_lbp = ?, total_cost_usd = ? WHERE id = ?", (total_order_cogs_lbp, total_order_cogs_usd, order_id))

        # If payment is debt (آجل), automatically insert into customer_debts
        if payment_method == 'debt':
            cursor.execute("""
            INSERT INTO customer_debts (customer_name, phone, order_id, order_number, amount_lbp, amount_usd, paid_lbp, paid_usd, remaining_lbp, remaining_usd, status, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0.0, 0.0, ?, ?, 'unpaid', ?, ?)
            """, (customer_name, order_data.get('phone', ''), order_id, order_num, total_lbp, total_usd, total_lbp, total_usd, notes or 'فاتورة كاشير معلقة على الحساب', get_local_now()))

        # Update each target Coffee Bag Batch
        for b_id, alloc in coffee_batches_allocation.items():
            try:
                cursor.execute("SELECT * FROM coffee_bag_batches WHERE id = ?", (b_id,))
                act_b = cursor.fetchone()
                if act_b:
                    n_sold = int(act_b['cups_sold'] or 0) + alloc['cups']
                    n_rev_lbp = float(act_b['total_revenue_lbp'] or 0.0) + alloc['rev_lbp']
                    n_rev_usd = float(act_b['total_revenue_usd'] or 0.0) + alloc['rev_usd']
                    n_damaged = int(act_b['cups_damaged'] or 0)
                    n_tot = n_sold + n_damaged
                    c_kg_lbp = float(act_b['cost_per_kg_lbp'] or 0.0)
                    c_kg_usd = float(act_b['cost_per_kg_usd'] or 0.0)
                    n_prof_lbp = n_rev_lbp - c_kg_lbp
                    n_prof_usd = n_rev_usd - c_kg_usd

                    cost_cup_lbp = round(c_kg_lbp / max(1, n_tot), 2) if n_tot > 0 else 0.0
                    cost_cup_usd = round(c_kg_usd / max(1, n_tot), 4) if n_tot > 0 else 0.0

                    cursor.execute("""
                        UPDATE coffee_bag_batches
                        SET cups_sold = ?,
                            total_cups = ?,
                            total_revenue_lbp = ?,
                            total_revenue_usd = ?,
                            cost_per_cup_lbp = ?,
                            cost_per_cup_usd = ?,
                            net_profit_lbp = ?,
                            net_profit_usd = ?
                        WHERE id = ?
                    """, (n_sold, n_tot, n_rev_lbp, n_rev_usd, cost_cup_lbp, cost_cup_usd, n_prof_lbp, n_prof_usd, b_id))
            except Exception as e:
                logger.error(f"Error updating coffee batch {b_id}: {e}")

        # 4. Atomic Financial Ledger & Double-Entry Accounting in the SAME transaction
        if payment_method == 'cash':
            lid = record_financial_ledger_entry(
                entry_type='sale',
                source='customer',
                destination='drawer',
                amount_lbp=total_lbp,
                amount_usd=total_usd,
                reference_table='cafe_orders',
                reference_id=order_id,
                user_id=emp_id,
                user_name=emp_name,
                notes=f"مبيع نقدي فاتورة #{order_num} ({customer_name})",
                exchange_rate=rate,
                business_date=get_business_date(),
                db_conn=conn
            )
            if not lid or lid <= 0:
                raise RuntimeError("تعذر تسجيل القيد المالي في الدفتر المركزي")

            # Double Entry: Dr Drawer (net) + Dr Discounts 4100, Cr Sales Revenue 4010 (gross)
            _lines = [
                {'account_code': '1010', 'debit_lbp': total_lbp, 'credit_lbp': 0.0, 'debit_usd': total_usd, 'credit_usd': 0.0, 'memo': f"قبض نقدي #{order_num}"}
            ]
            if discount_lbp > 0:
                _lines.append({'account_code': '4100', 'debit_lbp': discount_lbp, 'credit_lbp': 0.0, 'debit_usd': discount_usd, 'credit_usd': 0.0, 'memo': f"خصم #{order_num} {discount_reason}".strip()})
            _lines.append({'account_code': '4010', 'debit_lbp': 0.0, 'credit_lbp': subtotal_lbp, 'debit_usd': 0.0, 'credit_usd': subtotal_usd, 'memo': f"إيراد مبيعات كافيه #{order_num}"})
            ok_je, je_err = record_double_entry_journal(
                description=f"مبيع نقدي فاتورة #{order_num} ({customer_name})",
                lines=_lines,
                reference_type='cafe_orders',
                reference_id=order_id,
                user_name=emp_name,
                db_conn=conn
            )
            if not ok_je:
                raise RuntimeError(f"تعذر ترحيل القيد المحاسبي المزدوج: {je_err}")

        elif payment_method == 'debt':
            # Double Entry: Dr Receivable (net) + Dr Discounts 4100, Cr Sales Revenue 4010 (gross)
            _lines = [
                {'account_code': '1030', 'debit_lbp': total_lbp, 'credit_lbp': 0.0, 'debit_usd': total_usd, 'credit_usd': 0.0, 'memo': f"ذمة مدينة #{order_num}"}
            ]
            if discount_lbp > 0:
                _lines.append({'account_code': '4100', 'debit_lbp': discount_lbp, 'credit_lbp': 0.0, 'debit_usd': discount_usd, 'credit_usd': 0.0, 'memo': f"خصم #{order_num} {discount_reason}".strip()})
            _lines.append({'account_code': '4010', 'debit_lbp': 0.0, 'credit_lbp': subtotal_lbp, 'debit_usd': 0.0, 'credit_usd': subtotal_usd, 'memo': f"إيراد مبيعات آجل #{order_num}"})
            ok_je, je_err = record_double_entry_journal(
                description=f"مبيع آجل دين على الزبون فاتورة #{order_num} ({customer_name})",
                lines=_lines,
                reference_type='cafe_orders',
                reference_id=order_id,
                user_name=emp_name,
                db_conn=conn
            )
            if not ok_je:
                raise RuntimeError(f"تعذر ترحيل القيد المحاسبي المزدوج: {je_err}")

        elif payment_method == 'card':
            # Double Entry: Dr Card/Bank 1020 (net) + Dr Discounts 4100, Cr Sales Revenue 4010 (gross)
            _lines = [
                {'account_code': '1020', 'debit_lbp': total_lbp, 'credit_lbp': 0.0, 'debit_usd': total_usd, 'credit_usd': 0.0, 'memo': f"قبض بطاقة مصرفية #{order_num}"}
            ]
            if discount_lbp > 0:
                _lines.append({'account_code': '4100', 'debit_lbp': discount_lbp, 'credit_lbp': 0.0, 'debit_usd': discount_usd, 'credit_usd': 0.0, 'memo': f"خصم #{order_num} {discount_reason}".strip()})
            _lines.append({'account_code': '4010', 'debit_lbp': 0.0, 'credit_lbp': subtotal_lbp, 'debit_usd': 0.0, 'credit_usd': subtotal_usd, 'memo': f"إيراد مبيعات بطاقة #{order_num}"})
            ok_je, je_err = record_double_entry_journal(
                description=f"مبيع بطاقة بنكية فاتورة #{order_num} ({customer_name})",
                lines=_lines,
                reference_type='cafe_orders',
                reference_id=order_id,
                user_name=emp_name,
                db_conn=conn
            )
            if not ok_je:
                raise RuntimeError(f"تعذر ترحيل القيد المحاسبي المزدوج: {je_err}")

        conn.commit()
        conn.close()

        return True, {
            'order_id': order_id, 'order_number': order_num,
            'tracking_number': tracking_number,
            'subtotal_lbp': subtotal_lbp, 'discount_lbp': discount_lbp,
            'discount_percent': discount_percent, 'discount_reason': discount_reason,
            'total_lbp': total_lbp, 'total_usd': total_usd, 'payment_method': payment_method
        }
    except Exception as e:
        logger.error("Error creating order: %s", e, exc_info=True)
        if conn:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
        return False, str(e)

def save_customer_tab(customer_name, items_list=None, tab_id=None, notes='', discount_lbp=0.0, discount_usd=0.0, discount_percent=0.0, discount_reason=''):
    """Save or update an open customer tab (الزبائن الجالسون بالمحل) including discounts."""
    items_list = items_list or []
    customer_name = (customer_name or '').strip() or 'زبون في المحل'
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    calc = calculate_order_totals(items_list, rate)
    subtotal_lbp = calc['total_lbp']
    subtotal_usd = calc['total_usd']
    computed_items = calc['items']

    discount_lbp = float(discount_lbp or 0.0)
    discount_usd = float(discount_usd or 0.0)
    discount_percent = float(discount_percent or 0.0)
    discount_reason = (discount_reason or '').strip()

    if discount_lbp > 0:
        discount_usd = round(discount_lbp / rate, 2) if rate > 0 else 0.0
        discount_percent = round((discount_lbp / subtotal_lbp) * 100, 1) if subtotal_lbp > 0 else 0.0
    elif discount_usd > 0:
        discount_lbp = round(discount_usd * rate, 0)
        discount_percent = round((discount_lbp / subtotal_lbp) * 100, 1) if subtotal_lbp > 0 else 0.0
    elif discount_percent > 0:
        if discount_percent > 100.0:
            discount_percent = 100.0
        discount_lbp = round(subtotal_lbp * (discount_percent / 100.0), 0)
        discount_usd = round(subtotal_usd * (discount_percent / 100.0), 2)

    discount_lbp = min(discount_lbp, subtotal_lbp)
    discount_usd = min(discount_usd, subtotal_usd)
    total_lbp = max(0.0, subtotal_lbp - discount_lbp)
    total_usd = max(0.0, subtotal_usd - discount_usd)

    conn = get_db()
    cursor = conn.cursor()
    try:
        conn.execute("BEGIN IMMEDIATE")

        # 0. إذا كان الحساب موجوداً مسبقاً، استرجاع الأصناف السابقة مؤقتاً لتقييم الرصيد الدقيق ومنع التعارض
        if tab_id:
            cursor.execute("SELECT item_id, item_name, quantity FROM cafe_order_items WHERE order_id = ?", (tab_id,))
            old_tab_held = cursor.fetchall()
            for oth in old_tab_held:
                oth_id = oth['item_id']
                oth_q = float(oth['quantity'] or 0.0)
                if oth_id and not is_coffee_item(oth['item_name'], item_id=oth_id):
                    cursor.execute("UPDATE cafe_items SET stock_qty = stock_qty + ? WHERE id = ? AND track_stock = 1", (oth_q, oth_id))

        # ☕ Atomic Guard: prevent adding coffee items to customer tab if no active coffee batch
        coffee_items_found = []
        for it in computed_items:
            i_id = it.get('item_id')
            i_name = it.get('name', 'صنف')
            if is_coffee_item(i_name, item_id=i_id):
                coffee_items_found.append(i_name)

        if coffee_items_found:
            cursor.execute("SELECT id FROM coffee_bag_batches WHERE status = 'active' ORDER BY id DESC LIMIT 1")
            if not cursor.fetchone():
                conn.rollback()
                conn.close()
                first_coffee = coffee_items_found[0]
                return False, f"⚠️ لا يمكن إضافة القهوة للحساب! الصنف ({first_coffee}) يتطلب حبوب بن، ولا يوجد كيلو قهوة مفتوح حالياً في المحل. يجب فتح كيلو جديد أولاً ☕"

        # 🛑 Strict Stock Guard: Prevent adding out-of-stock items to open customer tabs
        for it in computed_items:
            item_id = it.get('item_id')
            item_name = it.get('name', 'صنف')
            item_type = it.get('item_type') or 'cafe'
            q = float(it.get('quantity') or 1.0)
            if item_id and item_type != 'gaming' and not is_coffee_item(item_name, item_id=item_id):
                cursor.execute("SELECT stock_qty, name, track_stock FROM cafe_items WHERE id = ?", (item_id,))
                st_row = cursor.fetchone()
                if st_row and st_row['track_stock'] == 1:
                    available = float(st_row['stock_qty'] or 0.0)
                    if available <= 0:
                        conn.rollback()
                        conn.close()
                        return False, f"⚠️ لا يمكن إضافة الصنف! ({st_row['name']}) غير مجرود أو رصيده (0) في المخزن. يمنع بيعه أو إضافته لحساب الطاولة."
                    elif available < q:
                        conn.rollback()
                        conn.close()
                        return False, f"⚠️ الكمية المطلوبة ({q}) غير متوفرة في المخزون للمنتج: {st_row['name']} (المتوفر حالياً: {int(available) if available.is_integer() else available} فقط)."

        existing_batch_map = {}
        if tab_id:
            # Preserve existing batch IDs for items that were already placed on this tab
            cursor.execute("SELECT item_name, quantity, coffee_batch_id FROM cafe_order_items WHERE order_id = ?", (tab_id,))
            old_rows = cursor.fetchall()
            for r in old_rows:
                b_id = r['coffee_batch_id']
                if b_id:
                    existing_batch_map.setdefault(r['item_name'], []).append(b_id)

            # Audit check: detect item removal or quantity modification
            old_summary = ", ".join([f"{r['item_name']} (x{r['quantity']})" for r in old_rows])
            new_summary = ", ".join([f"{it.get('name') or it.get('item_name') or 'صنف'} (x{it['quantity']})" for it in computed_items])
            if old_summary and old_summary != new_summary:
                cursor.execute("""
                    INSERT INTO audit_log
                       (actor, action, table_name, record_id, old_value, new_value, reason, ip_address)
                    VALUES (?, 'MODIFY_TAB_ITEMS', 'cafe_orders', ?, ?, ?, ?, '127.0.0.1')
                """, (
                    'كاشير',
                    tab_id,
                    old_summary,
                    new_summary,
                    f"تعديل أصناف حساب الزبون ({customer_name})"
                ))

            # Update existing open tab
            cursor.execute("""
            UPDATE cafe_orders SET
                customer_name = ?,
                subtotal_lbp = ?,
                subtotal_usd = ?,
                discount_lbp = ?,
                discount_usd = ?,
                discount_percent = ?,
                discount_reason = ?,
                total_lbp = ?,
                total_usd = ?,
                notes = ?,
                status = 'open',
                is_tab = 1
            WHERE id = ?
            """, (customer_name, subtotal_lbp, subtotal_usd, discount_lbp, discount_usd, discount_percent, discount_reason, total_lbp, total_usd, notes, tab_id))
            order_id = tab_id
            cursor.execute("SELECT order_number FROM cafe_orders WHERE id = ?", (order_id,))
            row = cursor.fetchone()
            order_num = row['order_number'] if row else generate_order_number()
            cursor.execute("DELETE FROM cafe_order_items WHERE order_id = ?", (order_id,))
        else:
            # Create new open tab
            order_num = generate_order_number()
            cursor.execute("""
            INSERT INTO cafe_orders (order_number, subtotal_lbp, subtotal_usd, discount_lbp, discount_usd, discount_percent, discount_reason, total_lbp, total_usd, paid_amount, payment_method, customer_name, notes, status, is_tab, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 'tab', ?, ?, 'open', 1, ?)
            """, (order_num, subtotal_lbp, subtotal_usd, discount_lbp, discount_usd, discount_percent, discount_reason, total_lbp, total_usd, customer_name, notes, get_local_now()))
            order_id = cursor.lastrowid

        cursor.execute("SELECT id FROM coffee_bag_batches WHERE status = 'active' ORDER BY id DESC LIMIT 1")
        active_batch_row = cursor.fetchone()
        current_active_batch_id = active_batch_row['id'] if active_batch_row else None

        for it in computed_items:
            item_id = it.get('item_id')
            item_name = it.get('name', 'صنف')
            item_type = it.get('item_type') or ('gaming' if 'gaming' in item_name.lower() or 'ألعاب' in item_name or 'كمبيوتر' in item_name else ('others' if it.get('is_custom') or not item_id else 'cafe'))
            q = it['quantity']
            u_lbp = it['price_lbp']
            u_usd = it['price_usd']
            sub_lbp = it['subtotal_lbp']
            sub_usd = it['subtotal_usd']
            
            # If item was already in tab, reuse its original coffee_batch_id; otherwise use current active batch
            item_coffee_batch = None
            if is_coffee_item(item_name, item_id=item_id):
                if existing_batch_map.get(item_name):
                    item_coffee_batch = existing_batch_map[item_name].pop(0)
                else:
                    item_coffee_batch = current_active_batch_id

            cursor.execute("""
            INSERT INTO cafe_order_items (order_id, item_id, item_name, item_type, quantity, unit_price_lbp, unit_price_usd, subtotal_lbp, subtotal_usd, coffee_batch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, item_id, item_name, item_type, q, u_lbp, u_usd, sub_lbp, sub_usd, item_coffee_batch))

            # 🚀 الخصم الفوري اللحظي للمخزون بمجرد خروج الصنف للطاولة
            if item_id and not is_coffee_item(item_name, item_id=item_id):
                cursor.execute("SELECT stock_qty, track_stock FROM cafe_items WHERE id = ?", (item_id,))
                cur_st = cursor.fetchone()
                if cur_st and cur_st['track_stock'] == 1:
                    q_cur_before = float(cur_st['stock_qty'] or 0.0)
                    q_cur_after = max(0.0, q_cur_before - q)
                    cursor.execute("UPDATE cafe_items SET stock_qty = ? WHERE id = ?", (q_cur_after, item_id))
                    try:
                        cursor.execute("""
                            INSERT INTO stock_movements (
                                movement_type, item_type, item_id, item_name, quantity,
                                qty_before, qty_after, reference_type, reference_id,
                                user_name, notes
                            ) VALUES ('TAB_OUT', 'cafe_item', ?, ?, ?, ?, ?, 'cafe_orders', ?, 'كاشير', ?)
                        """, (item_id, item_name, q, q_cur_before, q_cur_after, order_id, f"خروج فوري لطاولة #{order_num} ({customer_name})"))
                    except Exception:
                        pass

        conn.commit()
        conn.close()
        return True, {'tab_id': order_id, 'order_number': order_num, 'customer_name': customer_name, 'total_lbp': total_lbp, 'total_usd': total_usd}
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)

def get_open_tabs():
    """Get all open seated customer tabs currently in the cafe."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT o.*, COUNT(i.id) as items_count, COALESCE(SUM(i.quantity), 0) as total_qty
    FROM cafe_orders o
    LEFT JOIN cafe_order_items i ON o.id = i.order_id
    WHERE o.status = 'open'
    GROUP BY o.id
    ORDER BY o.id DESC
    """)
    tabs = [dict(r) for r in cursor.fetchall()]
    for t in tabs:
        cursor.execute("SELECT * FROM cafe_order_items WHERE order_id = ? ORDER BY id ASC", (t['id'],))
        t['items'] = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return tabs


# ----------------- SHIFT CLOSING LOG -----------------

def log_shift_close(employee_id, employee_name, total_sales_lbp, cash_sales_lbp, production_note='', date=None):
    """تسجيل إغلاق وردية الموظف مع ملاحظات الإنتاج."""
    if date is None:
        date = get_business_date()
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Ensure shift_logs table exists
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shift_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            employee_name TEXT,
            date TEXT,
            total_sales_lbp REAL DEFAULT 0,
            cash_sales_lbp REAL DEFAULT 0,
            production_note TEXT,
            closed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        INSERT INTO shift_logs (employee_id, employee_name, date, total_sales_lbp, cash_sales_lbp, production_note, closed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (employee_id, employee_name, date, total_sales_lbp, cash_sales_lbp, production_note, get_local_now()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        try: conn.close()
        except: pass
        return False

def get_shift_logs(target_date=None, employee_id=None, limit=50):
    """جلب سجلات إغلاق الورديات."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shift_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            employee_name TEXT,
            date TEXT,
            total_sales_lbp REAL DEFAULT 0,
            cash_sales_lbp REAL DEFAULT 0,
            production_note TEXT,
            closed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
        query = "SELECT * FROM shift_logs WHERE 1=1"
        params = []
        if target_date:
            query += " AND date = ?"
            params.append(target_date)
        if employee_id:
            query += " AND employee_id = ?"
            params.append(employee_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception:
        try: conn.close()
        except: pass
        return []

# ----------------- LOW STOCK ALERTS -----------------

def get_low_stock_items():
    """جلب المنتجات التي وصل مخزونها للحد الأدنى أو نفد."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        SELECT i.*, c.name as category_name
        FROM cafe_items i
        LEFT JOIN cafe_categories c ON i.category_id = c.id
        WHERE i.is_active = 1 AND i.track_stock = 1 AND i.stock_qty <= i.low_stock_limit
        ORDER BY i.stock_qty ASC
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception:
        try: conn.close()
        except: pass
        return []

def get_inventory_alerts_count():
    """عدد المنتجات التي نفدت أو على وشك النفاد."""
    items = get_low_stock_items()
    out_of_stock = sum(1 for i in items if i.get('stock_qty', 0) <= 0)
    low_stock = sum(1 for i in items if 0 < i.get('stock_qty', 0) <= i.get('low_stock_limit', 5))
    return {'total': len(items), 'out_of_stock': out_of_stock, 'low_stock': low_stock}


def delete_tab(tab_id, cancelled_by=None, reason=None, is_waste=False):
    """إلغاء طاولة/حساب زبون مع توثيق رقابي إلزامي ومسار تدقيق، مع خيار توثيق الأصناف التالفة."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        # 1. Fetch order details before deletion
        cursor.execute("SELECT customer_name, total_lbp, total_usd FROM cafe_orders WHERE id = ? AND status = 'open'", (tab_id,))
        order_row = cursor.fetchone()
        if not order_row:
            conn.close()
            return False, "الحساب غير موجود أو تم إغلاقه مسبقاً"

        customer_name = order_row['customer_name'] or 'طاولة زبون'
        total_lbp = float(order_row['total_lbp'] or 0.0)
        total_usd = float(order_row['total_usd'] or 0.0)

        # 2. Fetch order items
        cursor.execute("SELECT item_id, item_name, quantity, unit_price_lbp, unit_price_usd, item_type FROM cafe_order_items WHERE order_id = ?", (tab_id,))
        items = [dict(r) for r in cursor.fetchall()]
        items_summary = ", ".join([f"{it['item_name']} (x{it['quantity']})" for it in items]) or "بدون أصناف"

        # 3. If marked as waste (تالف/هدر مواد)، record into stock movements and coffee waste
        actor_name = cancelled_by or 'كاشير'
        waste_reason = reason or 'إلغاء طاولة / تلف طلب'
        if is_waste and items:
            for it in items:
                cursor.execute("""
                    INSERT INTO stock_movements (
                        movement_type, item_type, item_id, item_name, quantity,
                        reference_type, reference_id, user_name, notes, created_at
                    ) VALUES ('WASTE', 'cafe_item', ?, ?, ?, 'tab_void_waste', ?, ?, ?, CURRENT_TIMESTAMP)
                """, (it.get('item_id') or 0, it['item_name'], it['quantity'], tab_id, actor_name, f"تلف عند إلغاء طاولة ({customer_name}): {waste_reason}"))
                
                # If coffee item, log to coffee waste if available
                if 'قهوة' in it['item_name'] or 'اسبريسو' in it['item_name']:
                    try:
                        record_coffee_waste(qty=it['quantity'], reason=f"إلغاء حساب {customer_name}: {waste_reason}", employee_name=actor_name)
                    except Exception:
                        pass
        elif not is_waste and items:
            # 🔄 استرجاع فوري للمخزون عند إلغاء الطاولة بدون تلف (إعادة للرف/البراد)
            for it in items:
                it_id = it.get('item_id')
                it_q = float(it['quantity'] or 0.0)
                if it_id and not is_coffee_item(it['item_name'], item_id=it_id):
                    cursor.execute("UPDATE cafe_items SET stock_qty = stock_qty + ? WHERE id = ? AND track_stock = 1", (it_q, it_id))
                    try:
                        cursor.execute("""
                            INSERT INTO stock_movements (
                                movement_type, item_type, item_id, item_name, quantity,
                                reference_type, reference_id, user_name, notes, created_at
                            ) VALUES ('RETURN_IN', 'cafe_item', ?, ?, ?, 'tab_void_return', ?, ?, ?, CURRENT_TIMESTAMP)
                        """, (it_id, it['item_name'], it_q, tab_id, actor_name, f"إرجاع للمستودع عند إلغاء طاولة ({customer_name}): {waste_reason}"))
                    except Exception:
                        pass

        # 4. Write audit log (سجل التدقيق الرقابي الإلزامي)
        cursor.execute("""
            INSERT INTO audit_log
               (actor, action, table_name, record_id, old_value, new_value, reason, ip_address)
            VALUES (?, 'VOID_CUSTOMER_TAB', 'cafe_orders', ?, ?, 'CANCELLED_VOID', ?, '127.0.0.1')
        """, (
            actor_name,
            tab_id,
            f"الزبون: {customer_name} | الإجمالي: {total_lbp:,.0f} ل.ل ({total_usd:.2f}$) | الأصناف: {items_summary}",
            f"{waste_reason}{' [تم تسجيله كتالف]' if is_waste else ''}"
        ))

        # 5. Delete open tab items and order
        cursor.execute("DELETE FROM cafe_order_items WHERE order_id = ?", (tab_id,))
        cursor.execute("DELETE FROM cafe_orders WHERE id = ? AND status = 'open'", (tab_id,))
        conn.commit()
        conn.close()
        return True, f"تم إلغاء حساب ({customer_name}) بنجاح وتوثيق العملية في سجل الرقابة."
    except Exception as e:
        logger.error(f"Error in delete_tab: {e}", exc_info=True)
        conn.rollback()
        conn.close()
        return False, str(e)


def record_spoilage_waste(item_id=None, item_name="", qty=1.0, unit="قطعة", reason="", employee_name="كاشير", notes=""):
    """تسجيل بضاعة تالفة أو مهدورة وخصمها من المخزون مع توثيق إلزامي في السجل الرقابي."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        qty = float(qty or 1.0)
        actor_name = employee_name or 'كاشير'
        clean_reason = reason or 'تلف أثناء العمل'
        
        # Deduct from cafe_items or inventory if item_id provided
        if item_id:
            cursor.execute("SELECT name, stock_qty, track_stock FROM cafe_items WHERE id = ?", (item_id,))
            ci = cursor.fetchone()
            if ci:
                item_name = ci['name']
                if ci['track_stock']:
                    cursor.execute("UPDATE cafe_items SET stock_qty = MAX(0, stock_qty - ?) WHERE id = ?", (qty, item_id))
            else:
                cursor.execute("SELECT name, stock_qty FROM inventory WHERE id = ?", (item_id,))
                inv = cursor.fetchone()
                if inv:
                    item_name = inv['name']
                    cursor.execute("UPDATE inventory SET stock_qty = MAX(0, stock_qty - ?) WHERE id = ?", (qty, item_id))

        if not item_name:
            item_name = "صنف عام"

        # If it's coffee, log coffee waste as well
        if 'قهوة' in item_name or 'اسبريسو' in item_name:
            try:
                record_coffee_waste(qty=int(qty), reason=clean_reason, employee_name=actor_name, notes=notes)
            except Exception:
                pass

        # Record in stock_movements
        cursor.execute("""
            INSERT INTO stock_movements (
                movement_type, item_type, item_id, item_name, quantity,
                reference_type, user_name, notes, created_at
            ) VALUES ('WASTE', 'spoilage', ?, ?, ?, 'manual_spoilage', ?, ?, CURRENT_TIMESTAMP)
        """, (item_id or 0, item_name, qty, actor_name, f"سبب التلف: {clean_reason} | {notes}"))

        # Write audit log directly in the same transaction
        cursor.execute("""
            INSERT INTO audit_log
               (actor, action, table_name, record_id, old_value, new_value, reason, ip_address)
            VALUES (?, 'RECORD_WASTE_SPOILAGE', 'stock_movements', ?, ?, 'SPOILED_WASTE', ?, '127.0.0.1')
        """, (
            actor_name,
            item_id or 0,
            f"كمية {qty} {unit} من ({item_name})",
            clean_reason
        ))

        conn.commit()
        conn.close()
        return True, f"تم تسجيل تالف {qty} من ({item_name}) وتوثيقها رقابياً بنجاح."
    except Exception as e:
        logger.error(f"Error in record_spoilage_waste: {e}", exc_info=True)
        conn.rollback()
        conn.close()
        return False, str(e)

def get_orders(target_date=None, limit=5000, employee_id=None, status=None, start_date=None, end_date=None, order_type=None, search=None, include_all_statuses=False):
    conn = get_db()
    cursor = conn.cursor()
    query = """
    SELECT 
        o.*,
        COUNT(i.id) as items_count,
        COALESCE(SUM(i.quantity), 0) as total_cups,
        GROUP_CONCAT(i.item_name || ' (x' || i.quantity || ')', ' + ') as items_summary
    FROM cafe_orders o
    LEFT JOIN cafe_order_items i ON o.id = i.order_id
    WHERE 1=1
    """
    params = []
    
    if not include_all_statuses and status != 'all' and not status:
        query += " AND (o.status = 'paid' OR o.status IS NULL OR o.status = '')"
    elif status and status != 'all':
        query += " AND o.status = ?"
        params.append(status)

    if target_date and target_date != 'all':
        query += " AND (DATE(datetime(o.created_at, '-5 hours')) = DATE(?) OR DATE(o.created_at) = DATE(?))"
        params.extend([target_date, target_date])
    elif start_date and end_date:
        query += " AND DATE(o.created_at) BETWEEN DATE(?) AND DATE(?)"
        params.extend([start_date, end_date])
        
    if employee_id is not None:
        query += " AND (o.employee_id = ? OR o.employee_id IS NULL)"
        params.append(employee_id)
        
    if order_type and order_type != 'all':
        query += " AND (o.order_type = ? OR (o.order_type IS NULL AND ? = 'takeaway'))"
        params.extend([order_type, order_type])
        
    if search:
        s = f"%{str(search).strip()}%"
        query += " AND (o.order_number LIKE ? OR o.tracking_number LIKE ? OR o.customer_name LIKE ? OR o.notes LIKE ?)"
        params.extend([s, s, s, s])
        
    query += " GROUP BY o.id ORDER BY o.id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = []
    for r in cursor.fetchall():
        d = dict(r)
        if not d.get('tracking_number'):
            d['tracking_number'] = f"TRK-{d['id']:04d}"
        rows.append(d)
    conn.close()
    return rows


def get_orders_kpi_summary(target_date=None, start_date=None, end_date=None):
    """
    حساب مؤشرات أداء الطلبات (KPIs) بشكل دقيق ومفصل بدون أي تداخل أو تضليل للمستخدم:
    - إجمالي الطلبات
    - الطلبات الجديدة (new / open)
    - الطلبات قيد التحضير (preparing)
    - الطلبات الجاهزة (ready)
    - الطلبات المكتملة أو المدفوعة (completed / paid)
    - الطلبات الملغاة (cancelled)
    - إجمالي المبيعات المحققة
    """
    conn = get_db()
    cursor = conn.cursor()
    where_clauses = []
    params = []
    if target_date and target_date != 'all':
        where_clauses.append("(DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))")
        params.extend([target_date, target_date])
    elif start_date and end_date:
        where_clauses.append("DATE(created_at) BETWEEN DATE(?) AND DATE(?)")
        params.extend([start_date, end_date])
    
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    
    cursor.execute(f"""
        SELECT 
            COUNT(*) as total_orders,
            SUM(CASE WHEN status IN ('new', 'open') THEN 1 ELSE 0 END) as new_orders,
            SUM(CASE WHEN status = 'preparing' THEN 1 ELSE 0 END) as preparing_orders,
            SUM(CASE WHEN status = 'ready' THEN 1 ELSE 0 END) as ready_orders,
            SUM(CASE WHEN status IN ('completed', 'paid') THEN 1 ELSE 0 END) as completed_orders,
            SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled_orders,
            SUM(CASE WHEN status IN ('completed', 'paid') THEN total_lbp ELSE 0 END) as revenue_lbp,
            SUM(CASE WHEN status IN ('completed', 'paid') THEN total_usd ELSE 0 END) as revenue_usd
        FROM cafe_orders
        {where_sql}
    """, params)
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            'total_orders': int(row['total_orders'] or 0),
            'new_orders': int(row['new_orders'] or 0),
            'preparing_orders': int(row['preparing_orders'] or 0),
            'ready_orders': int(row['ready_orders'] or 0),
            'completed_orders': int(row['completed_orders'] or 0),
            'cancelled_orders': int(row['cancelled_orders'] or 0),
            'revenue_lbp': float(row['revenue_lbp'] or 0.0),
            'revenue_usd': float(row['revenue_usd'] or 0.0),
        }
    return {
        'total_orders': 0, 'new_orders': 0, 'preparing_orders': 0, 'ready_orders': 0,
        'completed_orders': 0, 'cancelled_orders': 0, 'revenue_lbp': 0.0, 'revenue_usd': 0.0
    }


def update_order_status(order_id: int, new_status: str, updated_by: str = 'كاشير', notes: str = '') -> tuple:
    """
    تحديث حالة الطلب مع التحقق من تسلسل المراحل المسموح بها ومسار تدقيق رسمي:
    - 'new' -> 'preparing' -> 'ready' -> 'completed' / 'paid'
    - أو 'cancelled' عبر cancel_order
    """
    new_status = str(new_status).strip().lower()
    valid_statuses = ['new', 'open', 'preparing', 'ready', 'completed', 'paid', 'cancelled']
    if new_status not in valid_statuses:
        return False, f"حالة الطلب ({new_status}) غير صحيحة"

    if new_status == 'cancelled':
        return cancel_order(order_id, cancelled_by=updated_by, reason=notes or 'إلغاء الطلب من لوحة إدارة الطلبات')

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, order_number, status, customer_name FROM cafe_orders WHERE id = ?", (order_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "الطلب غير موجود"

        old_status = row['status']
        if old_status == 'cancelled':
            conn.close()
            return False, "لا يمكن تغيير حالة طلب ملغي مسبقاً"

        if old_status == new_status:
            conn.close()
            return True, f"الطلب موجود بالفعل في حالة ({new_status})"

        note_append = f" | حالة: {new_status} ({updated_by})"
        if notes:
            note_append += f" - {notes}"

        cursor.execute("""
            UPDATE cafe_orders 
            SET status = ?, 
                notes = COALESCE(notes, '') || ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_status, note_append, order_id))

        # Log to audit_log
        try:
            cursor.execute("""
                INSERT INTO audit_log (actor, action, table_name, record_id, old_value, new_value, reason, ip_address)
                VALUES (?, 'ORDER_STATUS_UPDATE', 'cafe_orders', ?, ?, ?, ?, '127.0.0.1')
            """, (updated_by, order_id, old_status, new_status, notes or f"تغيير الحالة إلى {new_status}"))
        except Exception:
            pass

        conn.commit()
        conn.close()
        return True, f"تم تحديث حالة الطلب #{row['order_number']} إلى ({new_status}) بنجاح"
    except Exception as e:
        try: conn.close()
        except: pass
        return False, str(e)


def update_order_invoice_details(order_id: int, customer_name: str = None, order_type: str = None, notes: str = None, payment_method: str = None, updated_by: str = 'كاشير') -> tuple:
    """
    تعديل وتنظيم بيانات الفاتورة (اسم الزبون، نوع الطلب: صالة/سفري/دليفري، الملاحظات، طريقة الدفع)
    مع التوثيق الكامل في سجل التدقيق ومراعاة السلامة المالية.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, order_number, status, customer_name, order_type, notes, payment_method FROM cafe_orders WHERE id = ?", (order_id,))
        order = cursor.fetchone()
        if not order:
            conn.close()
            return False, "الفاتورة غير موجودة"

        updates = []
        params = []
        old_vals = {}
        new_vals = {}

        if customer_name is not None:
            c_name = str(customer_name).strip() or 'زبون كاش'
            updates.append("customer_name = ?")
            params.append(c_name)
            old_vals['customer_name'] = order['customer_name']
            new_vals['customer_name'] = c_name

        if order_type is not None:
            o_type = str(order_type).strip().lower()
            if o_type in ('takeaway', 'dine_in', 'delivery'):
                updates.append("order_type = ?")
                params.append(o_type)
                old_vals['order_type'] = order['order_type']
                new_vals['order_type'] = o_type

        if notes is not None:
            n_text = str(notes).strip()
            updates.append("notes = ?")
            params.append(n_text)
            old_vals['notes'] = order['notes']
            new_vals['notes'] = n_text

        if payment_method is not None:
            p_method = str(payment_method).strip().lower()
            if p_method in ('cash', 'debt', 'split', 'free'):
                updates.append("payment_method = ?")
                params.append(p_method)
                old_vals['payment_method'] = order['payment_method']
                new_vals['payment_method'] = p_method

        if not updates:
            conn.close()
            return True, "لا توجد تعديلات لحفظها"

        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = f"UPDATE cafe_orders SET {', '.join(updates)} WHERE id = ?"
        params.append(order_id)
        cursor.execute(sql, params)

        # Audit log
        try:
            cursor.execute("""
                INSERT INTO audit_log (actor, action, table_name, record_id, old_value, new_value, reason, ip_address)
                VALUES (?, 'INVOICE_DETAILS_UPDATE', 'cafe_orders', ?, ?, ?, ?, '127.0.0.1')
            """, (updated_by, order_id, str(old_vals), str(new_vals), f"تعديل بيانات الفاتورة #{order['order_number']}"))
        except Exception:
            pass

        conn.commit()
        conn.close()
        return True, f"تم تعديل وحفظ بيانات الفاتورة #{order['order_number']} بنجاح"
    except Exception as e:
        try: conn.close()
        except: pass
        return False, str(e)


def get_product_sales_breakdown(target_date=None, start_date=None, end_date=None):
    """Return detailed sales breakdown of each sold product (name, category, qty, revenue, pct)."""
    target_date = target_date or start_date
    conn = get_db()
    cursor = conn.cursor()

    query = """
    SELECT 
        i.item_name,
        COALESCE(i.item_type, 'cafe') as item_type,
        COALESCE(c.name, 'أخرى') as category_name,
        SUM(i.quantity) as total_qty,
        SUM(CASE WHEN i.is_wholesale = 1 OR o.is_wholesale = 1 THEN i.quantity ELSE 0 END) as wholesale_qty,
        SUM(CASE WHEN (i.is_wholesale = 0 OR i.is_wholesale IS NULL) AND (o.is_wholesale = 0 OR o.is_wholesale IS NULL) THEN i.quantity ELSE 0 END) as retail_qty,
        SUM(i.subtotal_lbp * (CASE WHEN o.subtotal_lbp > 0 THEN o.total_lbp / o.subtotal_lbp ELSE 1.0 END)) as total_lbp,
        SUM(i.subtotal_usd * (CASE WHEN o.subtotal_usd > 0 THEN o.total_usd / o.subtotal_usd ELSE 1.0 END)) as total_usd,
        SUM(CASE WHEN i.is_wholesale = 1 OR o.is_wholesale = 1 THEN i.subtotal_lbp * (CASE WHEN o.subtotal_lbp > 0 THEN o.total_lbp / o.subtotal_lbp ELSE 1.0 END) ELSE 0 END) as wholesale_revenue_lbp,
        SUM(CASE WHEN (i.is_wholesale = 0 OR i.is_wholesale IS NULL) AND (o.is_wholesale = 0 OR o.is_wholesale IS NULL) THEN i.subtotal_lbp * (CASE WHEN o.subtotal_lbp > 0 THEN o.total_lbp / o.subtotal_lbp ELSE 1.0 END) ELSE 0 END) as retail_revenue_lbp,
        ROUND(AVG(i.unit_price_lbp), 0) as avg_price_lbp,
        ROUND(AVG(i.unit_price_usd), 2) as avg_price_usd,
        COALESCE(
            CASE 
                WHEN (ci.is_coffee_bean_linked = 1 OR i.item_name LIKE '%قهوة%') AND (ci.cost_price_lbp IS NULL OR ci.cost_price_lbp <= 0)
                THEN (CASE WHEN i.item_name LIKE '%دوبل%' THEN 50586.0 ELSE 25293.0 END)
                ELSE ci.cost_price_lbp
            END, 0
        ) as unit_cost_lbp,
        COALESCE(ci.wholesale_price_lbp, 0) as unit_wholesale_lbp,
        SUM(COALESCE(
            CASE 
                WHEN (ci.is_coffee_bean_linked = 1 OR i.item_name LIKE '%قهوة%') AND (ci.cost_price_lbp IS NULL OR ci.cost_price_lbp <= 0)
                THEN (CASE WHEN i.item_name LIKE '%دوبل%' THEN 50586.0 ELSE 25293.0 END)
                ELSE ci.cost_price_lbp
            END, 0
        ) * i.quantity) as total_cost_lbp,
        SUM((i.subtotal_lbp * (CASE WHEN o.subtotal_lbp > 0 THEN o.total_lbp / o.subtotal_lbp ELSE 1.0 END)) - (COALESCE(
            CASE 
                WHEN (ci.is_coffee_bean_linked = 1 OR i.item_name LIKE '%قهوة%') AND (ci.cost_price_lbp IS NULL OR ci.cost_price_lbp <= 0)
                THEN (CASE WHEN i.item_name LIKE '%دوبل%' THEN 50586.0 ELSE 25293.0 END)
                ELSE ci.cost_price_lbp
            END, 0
        ) * i.quantity)) as net_profit_lbp
    FROM cafe_order_items i
    JOIN cafe_orders o ON i.order_id = o.id
    LEFT JOIN cafe_items ci ON i.item_id = ci.id
    LEFT JOIN cafe_categories c ON ci.category_id = c.id
    WHERE (o.status = 'paid' OR o.status IS NULL OR o.status = '')
    """
    params = []

    if target_date and str(target_date).lower() != 'all':
        if end_date and end_date != target_date:
            query += " AND DATE(datetime(o.created_at, '-5 hours')) >= DATE(?) AND DATE(datetime(o.created_at, '-5 hours')) <= DATE(?)"
            params.extend([target_date, end_date])
        else:
            query += " AND DATE(datetime(o.created_at, '-5 hours')) = DATE(?)"
            params.append(target_date)

    query += " GROUP BY i.item_name ORDER BY total_qty DESC, total_lbp DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    grand_total_lbp = sum(float(r['total_lbp'] or 0) for r in rows)
    grand_total_qty = sum(int(r['total_qty'] or 0) for r in rows)
    grand_total_wholesale_lbp = sum(float(r.get('wholesale_revenue_lbp') or 0) for r in rows)
    grand_total_retail_lbp = sum(float(r.get('retail_revenue_lbp') or 0) for r in rows)
    grand_total_cost_lbp = sum(float(r.get('total_cost_lbp') or 0) for r in rows)
    grand_total_profit_lbp = sum(float(r.get('net_profit_lbp') or 0) for r in rows)

    for r in rows:
        tot = float(r['total_lbp'] or 0)
        profit = float(r.get('net_profit_lbp') or 0)
        r['pct'] = round((tot / grand_total_lbp * 100), 1) if grand_total_lbp > 0 else 0.0
        r['margin_pct'] = round((profit / tot * 100), 1) if tot > 0 else 0.0
        # Determine icon
        name = r['item_name'].lower()
        if 'شاي' in name or 'tea' in name:
            r['icon'] = '🍵'
        elif 'قهوة' in name or 'كوفي' in name or 'coffee' in name or 'لاتيه' in name or 'اسبريسو' in name:
            r['icon'] = '☕'
        elif 'مياه' in name or 'ماء' in name or 'water' in name:
            r['icon'] = '💧'
        elif 'عصير' in name or 'juice' in name or 'موهيتو' in name:
            r['icon'] = '🍹'
        elif 'سناك' in name or 'كيك' in name or 'شوكولا' in name:
            r['icon'] = '🥐'
        elif 'gaming' in name or 'لعب' in name or 'ساعة' in name:
            r['icon'] = '🎮'
        else:
            r['icon'] = '📦'

    return {
        'products_list': rows,
        'grand_total_lbp': grand_total_lbp,
        'grand_total_qty': grand_total_qty,
        'grand_total_wholesale_lbp': grand_total_wholesale_lbp,
        'grand_total_retail_lbp': grand_total_retail_lbp,
        'grand_total_cost_lbp': grand_total_cost_lbp,
        'grand_total_profit_lbp': grand_total_profit_lbp,
        'overall_margin_pct': round((grand_total_profit_lbp / grand_total_lbp * 100), 1) if grand_total_lbp > 0 else 0.0,
        'unique_products_count': len(rows)
    }

def get_order_details(order_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cafe_orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    res = dict(row)
    if not res.get('tracking_number'):
        res['tracking_number'] = f"TRK-{res['id']:04d}"
    cursor.execute("SELECT * FROM cafe_order_items WHERE order_id = ? ORDER BY id ASC", (order_id,))
    items_list = [dict(r) for r in cursor.fetchall()]
    res['items'] = items_list
    res['order_items'] = items_list
    try:
        cursor.execute("SELECT actor, action, old_value, new_value, reason, created_at FROM audit_log WHERE table_name = 'cafe_orders' AND record_id = ? ORDER BY id ASC", (order_id,))
        res['history'] = [dict(h) for h in cursor.fetchall()]
    except Exception:
        res['history'] = []
    conn.close()
    return res

def cancel_order(order_id: int, cancelled_by: str = 'المدير', reason: str = '') -> tuple:
    """
    إلغاء فاتورة بطريقة محاسبية آمنة (Non-Destructive Cancellation):
    - يضع status='cancelled' بدل الحذف الفيزيائي
    - يستعيد المخزون تلقائياً لجميع الأصناف
    - يلغي أي ذمة دين مرتبطة بالفاتورة
    - يلغي أي قيد في السجل المالي المركزي مرتبط بها
    - يوثق عملية الإلغاء في سجل التدقيق (audit_log)
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM cafe_orders WHERE id = ?", (order_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "الفاتورة غير موجودة"

        order = dict(row)
        if order.get('status') == 'cancelled':
            conn.close()
            return False, "الفاتورة ملغاة مسبقاً"

        now_str = get_local_now()

        # 1. Mark order as cancelled instead of deleting
        cursor.execute("""
            UPDATE cafe_orders 
            SET status = 'cancelled', notes = COALESCE(notes, '') || ' | إلغاء: ' || ?
            WHERE id = ?
        """, (f"{reason} (بواسطة {cancelled_by})", order_id))

        # 2. Restore inventory for all items (finished goods, raw recipe materials, and coffee bean yield)
        cursor.execute("""
            SELECT item_id, item_name, quantity, coffee_batch_id, subtotal_lbp, subtotal_usd
            FROM cafe_order_items 
            WHERE order_id = ?
        """, (order_id,))
        for item_row in cursor.fetchall():
            iid = item_row['item_id']
            i_name = item_row['item_name'] or 'صنف'
            qty = float(item_row['quantity'] or 0.0)
            c_batch_id = item_row['coffee_batch_id']
            sub_lbp = float(item_row['subtotal_lbp'] or 0.0)
            sub_usd = float(item_row['subtotal_usd'] or 0.0)

            # 2.a Restore Turkish Coffee Bean Yield (استرجاع فنجان القهوة للكيس المفتوح والإنتاجية)
            if c_batch_id or is_coffee_item(i_name, item_id=iid):
                target_b_id = c_batch_id
                if not target_b_id:
                    cursor.execute("SELECT id FROM coffee_bag_batches WHERE status = 'active' ORDER BY id DESC LIMIT 1")
                    act_b_row = cursor.fetchone()
                    target_b_id = act_b_row['id'] if act_b_row else None

                if target_b_id:
                    cursor.execute("SELECT * FROM coffee_bag_batches WHERE id = ?", (target_b_id,))
                    b_data = cursor.fetchone()
                    if b_data:
                        cur_sold = int(b_data['cups_sold'] or 0)
                        restored_sold = max(0, cur_sold - int(qty))
                        cur_rev_lbp = float(b_data['total_revenue_lbp'] or 0.0)
                        cur_rev_usd = float(b_data['total_revenue_usd'] or 0.0)
                        restored_rev_lbp = max(0.0, cur_rev_lbp - sub_lbp)
                        restored_rev_usd = max(0.0, cur_rev_usd - sub_usd)
                        c_kg_lbp = float(b_data['cost_per_kg_lbp'] or 0.0)
                        restored_profit_lbp = restored_rev_lbp - c_kg_lbp
                        cur_damaged = int(b_data['cups_damaged'] or 0)
                        restored_tot_cups = restored_sold + cur_damaged
                        
                        cursor.execute("""
                            UPDATE coffee_bag_batches
                            SET cups_sold = ?, total_revenue_lbp = ?, total_revenue_usd = ?,
                                total_cups = ?, net_profit_lbp = ?
                            WHERE id = ?
                        """, (restored_sold, restored_rev_lbp, restored_rev_usd, restored_tot_cups, restored_profit_lbp, target_b_id))

            # 2.b Restore finished cafe item stock if tracked
            if iid:
                cursor.execute("""
                UPDATE cafe_items
                SET stock_qty = stock_qty + ?
                WHERE id = ? AND track_stock = 1
                """, (qty, iid))

                # 2.c Restore Raw Recipe Ingredients in inventory
                cursor.execute("""
                    SELECT r.required_qty, i.id as inv_id, i.name as raw_name, i.stock_qty as raw_stock
                    FROM recipes r
                    JOIN inventory i ON r.inventory_id = i.id
                    WHERE r.cafe_item_id = ?
                """, (iid,))
                for rec in cursor.fetchall():
                    raw_return = float(rec['required_qty'] or 0.0) * qty
                    cursor.execute("UPDATE inventory SET stock_qty = stock_qty + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (raw_return, rec['inv_id']))
                    try:
                        cursor.execute("""
                            INSERT INTO stock_movements (
                                movement_type, item_type, item_id, item_name, quantity,
                                reference_type, reference_id, user_name, notes
                            ) VALUES ('CANCEL_RESTORE_RECIPE', 'inventory', ?, ?, ?, 'cafe_orders', ?, ?, ?)
                        """, (rec['inv_id'], rec['raw_name'], raw_return, order_id, cancelled_by, f"استرجاع مواد خام لإلغاء فاتورة #{order.get('order_number', order_id)}"))
                    except Exception:
                        pass

        # 3. Cancel associated debt if this was a credit/debt sale
        cursor.execute("SELECT id FROM customer_debts WHERE order_id = ?", (order_id,))
        debt_rows = cursor.fetchall()
        for dr in debt_rows:
            cursor.execute("""
                UPDATE customer_debts
                SET status = 'cancelled', notes = COALESCE(notes, '') || ' | ألغيت بواسطة: ' || ?
                WHERE id = ?
            """, (cancelled_by, dr['id']))

        # 4. Cancel associated financial ledger entries
        cursor.execute("""
            UPDATE financial_ledger
            SET status = 'cancelled', cancelled_by = ?, cancelled_at = ?, cancel_reason = ?
            WHERE reference_table = 'cafe_orders' AND reference_id = ? AND status = 'active'
        """, (cancelled_by, now_str, (reason or 'إلغاء فاتورة').strip(), order_id))

        conn.commit()
        conn.close()

        # 5. Reverse Double-Entry Journal (قيد عكسي محاسبي رسمي وفق معايير المحاسبة المزدوجة)
        try:
            pay_method = order.get('payment_method')
            ord_num = order.get('order_number', str(order_id))
            tot_lbp = float(order.get('total_lbp') or 0.0)
            tot_usd = float(order.get('total_usd') or 0.0)
            if pay_method == 'cash' and tot_lbp > 0:
                record_double_entry_journal(
                    description=f"عكس قيد مبيعات نقدية لإلغاء الفاتورة #{ord_num} ({reason or 'إلغاء'})",
                    lines=[
                        {'account_code': '4010', 'debit_lbp': tot_lbp, 'credit_lbp': 0.0, 'debit_usd': tot_usd, 'credit_usd': 0.0, 'memo': f"مردودات مبيعات كافيه #{ord_num}"},
                        {'account_code': '1010', 'debit_lbp': 0.0, 'credit_lbp': tot_lbp, 'debit_usd': 0.0, 'credit_usd': tot_usd, 'memo': f"إرجاع كاش من الصندوق #{ord_num}"}
                    ],
                    reference_type='cafe_orders',
                    reference_id=order_id,
                    user_name=cancelled_by
                )
            elif pay_method == 'debt' and tot_lbp > 0:
                record_double_entry_journal(
                    description=f"عكس قيد مبيعات آجلة لإلغاء الفاتورة #{ord_num} ({reason or 'إلغاء'})",
                    lines=[
                        {'account_code': '4010', 'debit_lbp': tot_lbp, 'credit_lbp': 0.0, 'debit_usd': tot_usd, 'credit_usd': 0.0, 'memo': f"مردودات مبيعات آجلة #{ord_num}"},
                        {'account_code': '1030', 'debit_lbp': 0.0, 'credit_lbp': tot_lbp, 'debit_usd': 0.0, 'credit_usd': tot_usd, 'memo': f"إلغاء ذمة زبون #{ord_num}"}
                    ],
                    reference_type='cafe_orders',
                    reference_id=order_id,
                    user_name=cancelled_by
                )
        except Exception as je:
            logger.warning(f"Error creating reverse journal entry in cancel_order: {je}")

        database.write_audit_log(
            actor=cancelled_by,
            action='CANCEL_ORDER',
            table_name='cafe_orders',
            record_id=order_id,
            reason=f"{reason} | مبلغ: {order.get('total_lbp', 0):,.0f} ل.ل"
        )
        return True, f"تم إلغاء الفاتورة #{order.get('order_number', order_id)} وتحديث المخزون وقيد اليومية العكسي"

    except Exception as e:
        logger.error(f"Error in cancel_order: {e}", exc_info=True)
        conn.rollback()
        conn.close()
        return False, str(e)


def delete_order(order_id):
    """حذف/إلغاء فاتورة مع استرجاع المخزون تلقائياً وإلغاء أي ذمة مرتبطة (legacy wrapper → cancel_order)."""
    ok, msg = cancel_order(order_id, cancelled_by='المدير', reason='حذف من لوحة الإدارة')
    return ok



def log_single_pc_click(price_lbp=None, note='استخدام كمبيوتر GAMING', employee_id=None, employee_name=None):
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    p_lbp = float(price_lbp) if price_lbp else float(settings.get('pc_price_per_click_lbp') or 100000.0)
    p_usd = round(p_lbp / rate, 2) if rate > 0 else 0.0

    # Record as instant order so it integrates seamlessly in sales & receipts
    items_list = [{
        'name': 'كمبيوتر ألعاب GAMING 🎮',
        'price_lbp': p_lbp,
        'quantity': 1,
        'item_type': 'gaming',
        'item_id': None
    }]
    order_data = {
        'customer_name': 'لاعب GAMING',
        'notes': note,
        'payment_method': 'cash',
        'employee_id': employee_id,
        'employee_name': employee_name or 'كاشير'
    }
    success, res = create_order(order_data, items_list)
    return success, res

def get_pc_logs(target_date=None, limit=50):
    conn = get_db()
    cursor = conn.cursor()
    query = """
    SELECT o.id, o.order_number, o.created_at, i.unit_price_lbp as price_lbp, i.unit_price_usd as price_usd, i.quantity, i.subtotal_lbp, i.subtotal_usd, i.item_name, o.customer_name as player_name, o.notes
    FROM cafe_order_items i
    JOIN cafe_orders o ON i.order_id = o.id
    WHERE (
        i.item_type IN ('gaming', 'computer') 
        OR i.item_name LIKE '%GAMING%' 
        OR i.item_name LIKE '%ألعاب%' 
        OR i.item_name LIKE '%العاب%' 
        OR i.item_name LIKE '%كمبيوتر%' 
        OR i.item_name LIKE '%بلايستيشن%'
        OR i.item_name LIKE '%ساعة%'
        OR i.item_name LIKE '%ساعات%'
    )
    """
    params = []
    if target_date:
        query += " AND DATE(datetime(o.created_at, '-5 hours')) = DATE(?)"
        params.append(target_date)
    query += " ORDER BY o.id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def delete_pc_log(log_id):
    return delete_order(log_id)

# ----------------- EXPENSES -----------------

def add_expense(title, amount_lbp, category='مصاريف عامة', notes='', source='drawer', employee_id=None, employee_name='كاشير'):
    """
    تسجيل مصروف جديد مع تحديد مصدر الدفع:
    - 'drawer': مدفوع نقداً من درج الكاشير (يُخصم من كاش الدرج وصافي أرباح التشغيل)
    - 'safe': مدفوع من الخزنة الخاصة (يُخصم من رصيد الخزنة مع تسجيل حركة سحب تلقائية)
    """
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    a_lbp = float(amount_lbp or 0)
    a_usd = round(a_lbp / rate, 2) if rate > 0 else 0.0
    src = 'safe' if str(source).lower() in ('safe', 'خزنة', 'الخزنة') else 'drawer'
    emp_name = str(employee_name or 'كاشير').strip()

    conn = get_db()
    cursor = conn.cursor()
    try:
        # التأكد من وجود الأعمدة
        try:
            cursor.execute("ALTER TABLE expenses ADD COLUMN source TEXT DEFAULT 'drawer'")
            cursor.execute("ALTER TABLE expenses ADD COLUMN employee_id INTEGER")
            cursor.execute("ALTER TABLE expenses ADD COLUMN employee_name TEXT DEFAULT 'كاشير'")
            conn.commit()
        except Exception:
            pass

        now_str = get_local_now()
        cursor.execute("""
        INSERT INTO expenses (title, amount_lbp, amount_usd, category, notes, source, employee_id, employee_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title.strip(), a_lbp, a_usd, category, notes.strip(), src, employee_id, emp_name, now_str))
        eid = cursor.lastrowid

        # إذا كان المصروف مسدداً من الخزنة، نربطه بحركة سحب في الخزنة
        if src == 'safe':
            cursor.execute("""
            INSERT INTO safe_transfers (amount_lbp, amount_usd, note, transferred_by, operation_type, source, target, employee_id, employee_name, created_at)
            VALUES (?, ?, ?, ?, 'withdraw', 'safe', 'expense', ?, ?, ?)
            """, (a_lbp, a_usd, f"مصروف من الخزنة: {title.strip()}", emp_name, employee_id, emp_name, now_str))

        conn.commit()
        conn.close()

        # قيد سجل الحركة المالية المركزي
        try:
            record_financial_ledger_entry(
                entry_type='expense',
                source=src,
                destination='expense',
                amount_lbp=a_lbp,
                amount_usd=a_usd,
                reference_table='expenses',
                reference_id=eid,
                user_id=employee_id,
                user_name=emp_name,
                notes=f"مصروف: {title.strip()} ({category})",
                exchange_rate=rate,
                business_date=get_business_date()
            )

            # Double Entry Accounting for Expense: Debit Expenses (5020), Credit Drawer/Safe (1010/1020)
            credit_acc = '1020' if src == 'safe' else '1010'
            credit_memo = 'صادر من الخزنة' if src == 'safe' else 'صادر من درج الكاشير'
            record_double_entry_journal(
                description=f"مصروف: {title.strip()} ({category})",
                lines=[
                    {'account_code': '5020', 'debit_lbp': a_lbp, 'credit_lbp': 0.0, 'debit_usd': a_usd, 'credit_usd': 0.0, 'memo': f"مصروف {title.strip()}"},
                    {'account_code': credit_acc, 'debit_lbp': 0.0, 'credit_lbp': a_lbp, 'debit_usd': 0.0, 'credit_usd': a_usd, 'memo': credit_memo}
                ],
                reference_type='expenses',
                reference_id=eid,
                user_name=emp_name
            )
        except Exception:
            pass

        return True, eid
    except Exception as e:
        conn.close()
        return False, str(e)

def get_expenses(target_date=None, limit=200, source=None):
    """جلب سجل المصاريف مع دعم التصفية باليوم ومصدر السداد."""
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM expenses WHERE (status != 'cancelled' OR status IS NULL)"
    params = []
    if target_date:
        query += " AND (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))"
        params.extend([target_date, target_date])
    if source and source != 'all':
        query += " AND source = ?"
        params.append(source)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    for r in rows:
        r['source_label'] = 'من الخزنة الخاصة 🏦' if r.get('source') == 'safe' else 'من درج الصندوق 💵'
    return rows

def cancel_expense(expense_id: int, cancelled_by: str = 'المدير', reason: str = '') -> tuple:
    """
    إلغاء مصروف بطريقة محاسبية آمنة:
    - يضع status='cancelled' بدلاً من الحذف
    - يلغي حركة السحب من الخزنة إذا كان المصروف من الخزنة
    - يلغي القيد في السجل المالي المركزي
    - يوثق الإلغاء في سجل التدقيق
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "المصروف غير موجود"

    exp = dict(row)
    if exp.get('status') == 'cancelled':
        conn.close()
        return False, "المصروف ملغى مسبقاً"

    now_str = get_local_now()

    # Add status column if missing
    try:
        cursor.execute("ALTER TABLE expenses ADD COLUMN status TEXT DEFAULT 'active'")
        cursor.execute("ALTER TABLE expenses ADD COLUMN cancelled_by TEXT")
        cursor.execute("ALTER TABLE expenses ADD COLUMN cancelled_at TIMESTAMP")
        cursor.execute("ALTER TABLE expenses ADD COLUMN cancel_reason TEXT")
        conn.commit()
    except Exception:
        pass

    # Mark as cancelled (non-destructive)
    cursor.execute("""
        UPDATE expenses
        SET status = 'cancelled', cancelled_by = ?, cancelled_at = ?, cancel_reason = ?
        WHERE id = ?
    """, (cancelled_by, now_str, (reason or 'إلغاء مصروف').strip(), expense_id))

    # Cancel associated safe transfer if expense was from safe
    if exp.get('source') == 'safe':
        cursor.execute("""
            UPDATE safe_transfers
            SET status = 'cancelled', cancelled_by = ?, cancelled_at = ?, cancel_reason = ?
            WHERE note LIKE ? AND operation_type = 'withdraw' AND (status != 'cancelled' OR status IS NULL)
        """, (cancelled_by, now_str, reason or 'إلغاء مصروف مرتبط', f"%مصروف من الخزنة: {exp.get('title', '')}%"))

    # Cancel associated financial ledger entry
    cursor.execute("""
        UPDATE financial_ledger
        SET status = 'cancelled', cancelled_by = ?, cancelled_at = ?, cancel_reason = ?
        WHERE reference_table = 'expenses' AND reference_id = ? AND status = 'active'
    """, (cancelled_by, now_str, (reason or 'إلغاء مصروف').strip(), expense_id))

    conn.commit()
    conn.close()

    database.write_audit_log(
        actor=cancelled_by,
        action='CANCEL_EXPENSE',
        table_name='expenses',
        record_id=expense_id,
        reason=f"{reason} | {exp.get('title', '')} - {exp.get('amount_lbp', 0):,.0f} ل.ل"
    )
    return True, f"تم إلغاء المصروف '{exp.get('title', '')}' بنجاح"


def delete_expense(expense_id):
    """حذف مصروف وإلغاء أثره المحاسبي (legacy wrapper → cancel_expense)."""
    ok, msg = cancel_expense(expense_id, cancelled_by='المدير', reason='حذف من لوحة الإدارة')
    return ok



# ----------------- DAILY SUMMARY & EXECUTIVE PRODUCTION -----------------

def get_daily_summary(target_date=None):
    """
    Professional Accounting Breakdown:
    1. ☕ Cafe Drinks & Snacks
    2. 🎮 GAMING Computer
    3. ✍️ Others manual items
    4. 💵 Pure Cash Collected (Real Treasury)
    5. 📝 Credit / Debt Sales (Out of Register)
    6. 📥 Repaid Debts Collected Today
    7. 💸 Expenses
    8. 💎 Net Cash Profit & Total Production Value
    """
    target_date = target_date or get_business_date()
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    conn = get_db()
    cursor = conn.cursor()

    # Total Orders (All production created today)
    cursor.execute("""
    SELECT 
        COUNT(id) as orders_count,
        COALESCE(SUM(total_lbp), 0) as total_lbp,
        COALESCE(SUM(total_usd), 0) as total_usd,
        COALESCE(SUM(CASE WHEN subtotal_lbp > 0 THEN subtotal_lbp ELSE total_lbp END), 0) as gross_production_lbp,
        COALESCE(SUM(CASE WHEN subtotal_usd > 0 THEN subtotal_usd ELSE total_usd END), 0) as gross_production_usd,
        COALESCE(SUM(discount_lbp), 0) as total_discounts_lbp,
        COALESCE(SUM(discount_usd), 0) as total_discounts_usd,
        COALESCE(SUM(CASE WHEN payment_method = 'cash' THEN total_lbp ELSE 0 END), 0) as cash_sales_lbp,
        COALESCE(SUM(CASE WHEN payment_method = 'cash' THEN total_usd ELSE 0 END), 0) as cash_sales_usd,
        COALESCE(SUM(CASE WHEN payment_method = 'debt' THEN total_lbp ELSE 0 END), 0) as debt_sales_lbp,
        COALESCE(SUM(CASE WHEN payment_method = 'debt' THEN total_usd ELSE 0 END), 0) as debt_sales_usd
    FROM cafe_orders
    WHERE DATE(datetime(created_at, '-5 hours')) = DATE(?) AND (status != 'cancelled' AND (status != 'open' OR is_tab = 0))
    """, (target_date,))
    all_orders = dict(cursor.fetchone() or {})

    # Collected Debt Repayments Today (Cash brought in from past or today's debts)
    cursor.execute("""
    SELECT 
        COALESCE(SUM(amount_lbp), 0) as debt_collected_lbp,
        COALESCE(SUM(amount_usd), 0) as debt_collected_usd,
        COUNT(id) as repayments_count
    FROM debt_payments
    WHERE DATE(datetime(created_at, '-5 hours')) = DATE(?)
    """, (target_date,))
    debt_rep = dict(cursor.fetchone() or {})

    # 1. Cafe items breakdown (coffee, drinks, snacks) - Net revenue after discounts
    cursor.execute("""
    SELECT 
        COALESCE(SUM(i.quantity), 0) as cups_count,
        COALESCE(SUM(i.subtotal_lbp * (CASE WHEN o.subtotal_lbp > 0 THEN o.total_lbp / o.subtotal_lbp ELSE 1.0 END)), 0) as total_lbp,
        COALESCE(SUM(i.subtotal_usd * (CASE WHEN o.subtotal_usd > 0 THEN o.total_usd / o.subtotal_usd ELSE 1.0 END)), 0) as total_usd
    FROM cafe_order_items i
    JOIN cafe_orders o ON i.order_id = o.id
    WHERE DATE(datetime(o.created_at, '-5 hours')) = DATE(?) AND (o.status != 'cancelled' AND (o.status != 'open' OR o.is_tab = 0)) AND (
        i.item_type = 'cafe' 
        OR (
            (i.item_type IS NULL OR i.item_type = '' OR i.item_type NOT IN ('gaming', 'computer', 'others'))
            AND i.item_name NOT LIKE '%GAMING%' 
            AND i.item_name NOT LIKE '%ألعاب%' 
            AND i.item_name NOT LIKE '%العاب%' 
            AND i.item_name NOT LIKE '%كمبيوتر%' 
            AND i.item_name NOT LIKE '%بلايستيشن%'
            AND i.item_name NOT LIKE '%ساعة%'
            AND i.item_name NOT LIKE '%ساعات%'
        )
    )
    """, (target_date,))
    cafe_res = dict(cursor.fetchone() or {})
    cafe_res['orders_count'] = all_orders['orders_count']

    # 2. GAMING PC & Computer breakdown - Net revenue after discounts
    cursor.execute("""
    SELECT 
        COALESCE(SUM(i.quantity), 0) as clicks_count,
        COALESCE(SUM(i.subtotal_lbp * (CASE WHEN o.subtotal_lbp > 0 THEN o.total_lbp / o.subtotal_lbp ELSE 1.0 END)), 0) as total_lbp,
        COALESCE(SUM(i.subtotal_usd * (CASE WHEN o.subtotal_usd > 0 THEN o.total_usd / o.subtotal_usd ELSE 1.0 END)), 0) as total_usd
    FROM cafe_order_items i
    JOIN cafe_orders o ON i.order_id = o.id
    WHERE DATE(datetime(o.created_at, '-5 hours')) = DATE(?) AND (o.status != 'cancelled' AND (o.status != 'open' OR o.is_tab = 0)) AND (
        i.item_type IN ('gaming', 'computer') 
        OR i.item_name LIKE '%GAMING%' 
        OR i.item_name LIKE '%ألعاب%' 
        OR i.item_name LIKE '%العاب%' 
        OR i.item_name LIKE '%كمبيوتر%' 
        OR i.item_name LIKE '%بلايستيشن%' 
        OR i.item_name LIKE '%ساعة%' 
        OR i.item_name LIKE '%ساعات%'
    )
    """, (target_date,))
    pc_res = dict(cursor.fetchone() or {})
    pc_res['profit_lbp'] = pc_res['total_lbp']
    pc_res['profit_usd'] = pc_res['total_usd']

    # 3. Others breakdown - Net revenue after discounts
    cursor.execute("""
    SELECT 
        COALESCE(SUM(i.quantity), 0) as count,
        COALESCE(SUM(i.subtotal_lbp * (CASE WHEN o.subtotal_lbp > 0 THEN o.total_lbp / o.subtotal_lbp ELSE 1.0 END)), 0) as total_lbp,
        COALESCE(SUM(i.subtotal_usd * (CASE WHEN o.subtotal_usd > 0 THEN o.total_usd / o.subtotal_usd ELSE 1.0 END)), 0) as total_usd
    FROM cafe_order_items i
    JOIN cafe_orders o ON i.order_id = o.id
    WHERE DATE(datetime(o.created_at, '-5 hours')) = DATE(?) AND (o.status != 'cancelled' AND (o.status != 'open' OR o.is_tab = 0)) AND i.item_type = 'others'
    """, (target_date,))
    others_res = dict(cursor.fetchone() or {})

    # 4. Open Customer Tabs Currently in Cafe
    cursor.execute("""
    SELECT 
        COUNT(id) as count,
        COALESCE(SUM(total_lbp), 0) as total_lbp,
        COALESCE(SUM(total_usd), 0) as total_usd
    FROM cafe_orders
    WHERE status = 'open'
    """)
    open_tabs_res = dict(cursor.fetchone() or {})

    # 5. Expenses (مفصولة بدقة: مصاريف مسددة من درج الكاشير مقابل مصاريف مسددة من الخزنة الخاصة)
    cursor.execute("""
    SELECT 
        COUNT(id) as expenses_count,
        COALESCE(SUM(amount_lbp), 0) as total_lbp,
        COALESCE(SUM(amount_usd), 0) as total_usd,
        COALESCE(SUM(CASE WHEN source = 'safe' THEN amount_lbp ELSE 0 END), 0) as expenses_safe_lbp,
        COALESCE(SUM(CASE WHEN source != 'safe' OR source IS NULL THEN amount_lbp ELSE 0 END), 0) as expenses_drawer_lbp,
        COALESCE(SUM(CASE WHEN source = 'safe' THEN amount_usd ELSE 0 END), 0) as expenses_safe_usd,
        COALESCE(SUM(CASE WHEN source != 'safe' OR source IS NULL THEN amount_usd ELSE 0 END), 0) as expenses_drawer_usd
    FROM expenses
    WHERE DATE(datetime(created_at, '-5 hours')) = DATE(?)
      AND (status != 'cancelled' OR status IS NULL)
    """, (target_date,))
    exp_res = dict(cursor.fetchone() or {})

    # 5b. Coffee Waste Loss for this day (خسائر هدر وتلف القهوة)
    cursor.execute("""
        SELECT 
            COALESCE(SUM(loss_cost_lbp), 0) as waste_loss_lbp,
            COALESCE(SUM(loss_cost_usd), 0) as waste_loss_usd,
            COALESCE(SUM(qty), 0) as waste_cups_count
        FROM coffee_waste_logs
        WHERE DATE(datetime(created_at, '-5 hours')) = DATE(?)
    """, (target_date,))
    c_waste_row = dict(cursor.fetchone() or {})

    # 6. Safe Transfers for this day (المرحل للخزنة الخاصة لهذا اليوم)
    cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN operation_type = 'deposit' AND (source != 'external' OR source IS NULL) THEN amount_lbp ELSE 0 END), 0) as drawer_to_safe_lbp,
            COALESCE(SUM(CASE WHEN operation_type = 'deposit' THEN amount_lbp ELSE 0 END), 0) as safe_deposit_lbp,
            COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_lbp ELSE 0 END), 0) as safe_withdraw_lbp,
            COALESCE(SUM(CASE WHEN operation_type = 'deposit' AND (source != 'external' OR source IS NULL) THEN amount_usd ELSE 0 END), 0) as drawer_to_safe_usd,
            COALESCE(SUM(CASE WHEN operation_type = 'deposit' THEN amount_usd ELSE 0 END), 0) as safe_deposit_usd,
            COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_usd ELSE 0 END), 0) as safe_withdraw_usd,
            COUNT(id) as transfers_count
        FROM safe_transfers
        WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?) OR note LIKE ?)
          AND (status != 'cancelled' OR status IS NULL)
    """, (target_date, target_date, f"%{target_date}%"))
    safe_day_row = dict(cursor.fetchone() or {})

    # خصومات اليوم (خصم الزبائن الدائمين والضيافة)
    try:
        cursor.execute("""
            SELECT COALESCE(SUM(discount_lbp), 0) as disc_lbp, COUNT(CASE WHEN discount_lbp > 0 THEN 1 END) as disc_count
            FROM cafe_orders
            WHERE DATE(datetime(created_at, '-5 hours')) = DATE(?) AND (status = 'paid' OR status IS NULL OR status = '')
        """, (target_date,))
        disc_row = dict(cursor.fetchone() or {})
    except Exception:
        disc_row = {}
    discounts_lbp = float(disc_row.get('disc_lbp') or 0.0)
    discounts_count = int(disc_row.get('disc_count') or 0)

    conn.close()

    total_production_lbp = all_orders['total_lbp']
    total_production_usd = round(total_production_lbp / rate, 2) if rate > 0 else 0.0

    cash_sales_lbp = all_orders.get('cash_sales_lbp', 0.0)
    debt_sales_lbp = all_orders.get('debt_sales_lbp', 0.0)
    debt_collected_lbp = debt_rep.get('debt_collected_lbp', 0.0)

    # Actual Cash In Drawer = Direct Cash Sales + Debt Repayments Collected
    actual_cash_in_lbp = cash_sales_lbp + debt_collected_lbp
    actual_cash_in_usd = round(actual_cash_in_lbp / rate, 2) if rate > 0 else 0.0

    expenses_drawer_lbp = float(exp_res.get('expenses_drawer_lbp') or 0.0)
    expenses_safe_lbp = float(exp_res.get('expenses_safe_lbp') or 0.0)
    total_expenses_lbp = float(exp_res.get('total_lbp') or 0.0)

    # Net Operating Cash Profit = actual cash collected - all expenses
    net_cash_profit_lbp = actual_cash_in_lbp - total_expenses_lbp
    net_cash_profit_usd = round(net_cash_profit_lbp / rate, 2) if rate > 0 else 0.0

    # صافي ما تم ترحيله من درج الكاشير للخزنة الخاصة لهذا اليوم
    drawer_to_safe_lbp = float(safe_day_row.get('drawer_to_safe_lbp') or 0.0)
    if drawer_to_safe_lbp == 0.0 and float(safe_day_row.get('safe_deposit_lbp') or 0.0) > 0.0:
        drawer_to_safe_lbp = float(safe_day_row.get('safe_deposit_lbp') or 0.0)
    safe_transferred_day_lbp = drawer_to_safe_lbp
    safe_transferred_day_usd = round(safe_transferred_day_lbp / rate, 2) if rate > 0 else 0.0

    # المتبقي الفعلي في درج الصندوق لهذا اليوم = الكاش الوارد - مصاريف الدرج - ما تم ترحيله للخزنة
    drawer_remaining_lbp = max(0.0, actual_cash_in_lbp - expenses_drawer_lbp - safe_transferred_day_lbp)
    drawer_remaining_usd = round(drawer_remaining_lbp / rate, 2) if rate > 0 else 0.0

    gross_production_lbp = float(all_orders.get('gross_production_lbp') or total_production_lbp)
    gross_production_usd = round(gross_production_lbp / rate, 2) if rate > 0 else 0.0

    grand_totals = {
        'discounts_lbp': discounts_lbp,
        'discounts_usd': round(discounts_lbp / rate, 2) if rate > 0 else 0.0,
        'discounts_count': discounts_count,
        'revenue_lbp': actual_cash_in_lbp,
        'revenue_usd': actual_cash_in_usd,
        'gross_production_lbp': gross_production_lbp,
        'gross_production_usd': gross_production_usd,
        'total_production_lbp': total_production_lbp,
        'total_production_usd': total_production_usd,
        'cash_sales_lbp': cash_sales_lbp,
        'cash_sales_usd': round(cash_sales_lbp / rate, 2) if rate > 0 else 0.0,
        'debt_sales_lbp': debt_sales_lbp,
        'debt_sales_usd': round(debt_sales_lbp / rate, 2) if rate > 0 else 0.0,
        'debt_collected_lbp': debt_collected_lbp,
        'debt_collected_usd': round(debt_collected_lbp / rate, 2) if rate > 0 else 0.0,
        'expenses_drawer_lbp': expenses_drawer_lbp,
        'expenses_drawer_usd': round(expenses_drawer_lbp / rate, 2) if rate > 0 else 0.0,
        'expenses_safe_lbp': expenses_safe_lbp,
        'expenses_safe_usd': round(expenses_safe_lbp / rate, 2) if rate > 0 else 0.0,
        'expenses_total_lbp': total_expenses_lbp,
        'expenses_total_usd': round(total_expenses_lbp / rate, 2) if rate > 0 else 0.0,
        'transferred_to_safe_lbp': safe_transferred_day_lbp,
        'transferred_to_safe_usd': safe_transferred_day_usd,
        'drawer_remaining_lbp': drawer_remaining_lbp,
        'drawer_remaining_usd': drawer_remaining_usd,
        'net_profit_lbp': net_cash_profit_lbp,
        'net_profit_usd': net_cash_profit_usd,
        'coffee_waste_loss_lbp': float(c_waste_row.get('waste_loss_lbp', 0.0)),
        'coffee_waste_loss_usd': float(c_waste_row.get('waste_loss_usd', 0.0)),
        'coffee_waste_cups': int(c_waste_row.get('waste_cups_count', 0))
    }

    return {
        'target_date': target_date,
        'exchange_rate': rate,
        'cafe': cafe_res,
        'pc': pc_res,
        'others': others_res,
        'open_tabs': open_tabs_res,
        'expenses': exp_res,
        'recent_expenses': get_expenses(target_date=target_date, limit=100),
        'safe_day': {
            'transferred_lbp': safe_transferred_day_lbp,
            'transferred_usd': safe_transferred_day_usd,
            'deposits_lbp': float(safe_day_row.get('safe_deposit_lbp') or 0.0),
            'withdrawals_lbp': float(safe_day_row.get('safe_withdraw_lbp') or 0.0),
            'transfers_count': int(safe_day_row.get('transfers_count') or 0)
        },
        'debt_info': {
            'debt_sales_lbp': debt_sales_lbp,
            'debt_sales_usd': round(debt_sales_lbp / rate, 2) if rate > 0 else 0.0,
            'debt_collected_lbp': debt_collected_lbp,
            'debt_collected_usd': round(debt_collected_lbp / rate, 2) if rate > 0 else 0.0,
            'cash_sales_lbp': cash_sales_lbp,
            'cash_sales_usd': round(cash_sales_lbp / rate, 2) if rate > 0 else 0.0,
        },
        'grand_totals': grand_totals,
        'gross_production_lbp': gross_production_lbp,
        'gross_production_usd': gross_production_usd,
        'total_production_lbp': total_production_lbp,
        'total_production_usd': total_production_usd,
        'total_revenue_lbp': actual_cash_in_lbp,
        'total_revenue_usd': actual_cash_in_usd,
        'transferred_to_safe_lbp': safe_transferred_day_lbp,
        'transferred_to_safe_usd': safe_transferred_day_usd,
        'drawer_remaining_lbp': drawer_remaining_lbp,
        'drawer_remaining_usd': drawer_remaining_usd,
        'net_profit_lbp': net_cash_profit_lbp,
        'net_profit_usd': net_cash_profit_usd,
        'cafe_share_pct': round((cafe_res['total_lbp'] / total_production_lbp * 100), 1) if total_production_lbp > 0 else 0,
        'pc_share_pct': round((pc_res['total_lbp'] / total_production_lbp * 100), 1) if total_production_lbp > 0 else 0,
        'others_share_pct': round((others_res['total_lbp'] / total_production_lbp * 100), 1) if total_production_lbp > 0 else 0,
    }

def get_weekly_trend():
    days = []
    today = datetime.now()
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        s = get_daily_summary(d)
        days.append({
            'date': d,
            'label': datetime.strptime(d, '%Y-%m-%d').strftime('%m/%d'),
            'cafe_lbp': s['cafe']['total_lbp'],
            'pc_lbp': s['pc']['total_lbp'],
            'others_lbp': s['others']['total_lbp'],
            'total_lbp': s['total_revenue_lbp'],
            'net_profit_lbp': s['net_profit_lbp']
        })
    return days

def factory_reset(reset_type='full', admin_pin=None, actor='المدير'):
    """
    Reset system to factory default or clear transactions.
    reset_type: 
        'transactions_only': clears all orders, items, expenses, logs, debts, vault/safe transfers,
                             general financial ledger, journal entries, shift closings, stock movements,
                             resets table occupancies, and resets SQLite sequence counters.
                             KEEPS: Menu items, categories, recipes, employees, suppliers, settings.
        'full': completely resets database, drops all tables, recreates schema with custom or preserved admin credentials
                and base STARGATE settings so the system starts 100% clean and secure.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Capture existing admin credentials if doing a full reset without providing a new PIN
        preserved_admin_hash = None
        if reset_type == 'full':
            try:
                cursor.execute("SELECT admin_password FROM settings WHERE id = 1")
                row_pwd = cursor.fetchone()
                if row_pwd and row_pwd['admin_password']:
                    preserved_admin_hash = str(row_pwd['admin_password']).strip()
            except Exception:
                pass

        if reset_type == 'transactions_only':
            # Clear all transactional data tables
            tx_tables = [
                'cafe_order_items', 'cafe_orders', 'expenses', 'pc_usage_logs',
                'debt_payments', 'customer_debts', 'safe_transfers',
                'financial_ledger', 'journal_entry_lines', 'journal_entries',
                'shift_closings', 'shift_logs', 'stock_movements', 'audit_log'
            ]
            for t in tx_tables:
                try:
                    cursor.execute(f"DELETE FROM {t}")
                except Exception as te:
                    logger.warning(f"Error clearing table {t}: {te}")

            # Reset dining tables status to clean/available
            try:
                cursor.execute("""
                    UPDATE dining_tables 
                    SET status = 'available', current_order_id = NULL
                """)
            except Exception as dte:
                logger.warning(f"Error resetting dining tables: {dte}")

            # Reset auto-increment counters for all transactional tables
            try:
                placeholders = ','.join(f"'{tbl}'" for tbl in tx_tables)
                cursor.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})")
            except Exception:
                pass

            conn.commit()
            try:
                cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            conn.close()

            database.write_audit_log(
                actor=actor,
                action='FACTORY_RESET',
                table_name='ALL_TRANSACTIONS',
                reason='تصفير كامل الحركات المالية والعمليات مع الحفاظ على البيانات الأساسية'
            )
            return True, "تم تصفير وتسفير جميع المبيعات والفواتير والمصاريف والديون والخزنة والورديات بنجاح 100%! تم الحفاظ على قائمة الأصناف والأسعار والموردين والموظفين."

        else: # 'full' (ضبط المصنع الشامل 100% صفر بكل شيء)
            # Drop all user tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = [row[0] for row in cursor.fetchall()]
            for t in tables:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {t}")
                except Exception as de:
                    logger.warning(f"Error dropping table {t}: {de}")
            try:
                cursor.execute("DELETE FROM sqlite_sequence")
            except Exception:
                pass
            conn.commit()
            try:
                cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            conn.close()

            # Re-initialize clean fresh database schema WITHOUT any default items or seed menus
            database.init_db(seed_items=False)

            # Clean settings to 100% virgin state: no default password, setup_complete = 0
            conn2 = get_db()
            conn2.execute("""
                UPDATE settings 
                SET company_name = 'STARGATE CAFE', exchange_rate = 89500.0, 
                    pc_price_per_click_lbp = 100000.0, is_seeded = 0,
                    setup_complete = 0, admin_password = ''
                WHERE id = 1
            """)
            # Ensure NO default employees exist
            conn2.execute("DELETE FROM employees")
            conn2.execute("DELETE FROM cafe_items")
            conn2.execute("DELETE FROM cafe_categories")
            conn2.commit()
            try:
                conn2.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            conn2.close()

            database.write_audit_log(
                actor=actor,
                action='FACTORY_RESET',
                table_name='ALL_TABLES',
                reason='استعادة ضبط المصنع الشامل 100% صفر بكل شيء وبدون أي حسابات افتراضية'
            )
            return True, "تمت استعادة ضبط المصنع الشامل بنجاح 100%! تم تفريغ وتصفير كل شيء (0 منتجات، 0 موظفين، 0 فواتير)، والنظام الآن بانتظار إعداد حساب الإدارة الأول."

    except Exception as e:
        logger.error(f"Error in factory_reset: {e}", exc_info=True)
        return False, f"فشل أثناء ضبط المصنع والتصفير: {str(e)}"

# ----------------- CUSTOMER DEBTS (سجل ديون الزبائن والآجل) -----------------

def add_manual_debt(customer_name, amount_lbp, phone='', notes=''):
    """Record a manual customer debt."""
    customer_name = (customer_name or '').strip()
    if not customer_name:
        return False, "اسم الزبون مطلوب"
    
    amount_lbp = float(amount_lbp or 0)
    if amount_lbp <= 0:
        return False, "المبلغ يجب أن يكون أكبر من صفر"
    
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    amount_usd = round(amount_lbp / rate, 2) if rate > 0 else 0.0

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO customer_debts (customer_name, phone, amount_lbp, amount_usd, paid_lbp, paid_usd, remaining_lbp, remaining_usd, status, notes)
        VALUES (?, ?, ?, ?, 0.0, 0.0, ?, ?, 'unpaid', ?)
        """, (customer_name, phone.strip(), amount_lbp, amount_usd, amount_lbp, amount_usd, notes.strip()))
        debt_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return True, debt_id
    except Exception as e:
        conn.close()
        return False, str(e)

def get_debts_summary():
    """Get aggregated summary of all outstanding and settled debts."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Total remaining active debts
    cursor.execute("""
    SELECT 
        COALESCE(SUM(remaining_lbp), 0) as total_remaining_lbp,
        COALESCE(SUM(remaining_usd), 0) as total_remaining_usd,
        COUNT(id) as total_debts_count
    FROM customer_debts
    WHERE (status != 'cancelled' OR status IS NULL) AND remaining_lbp > 0
    """)
    active_res = dict(cursor.fetchone() or {})
    
    # Distinct active debtors count
    cursor.execute("SELECT COUNT(DISTINCT customer_name) as customers_count FROM customer_debts WHERE (status != 'cancelled' OR status IS NULL) AND remaining_lbp > 0")
    row_c = cursor.fetchone()
    active_res['customers_count'] = row_c['customers_count'] if row_c else 0

    # Total collected debt repayments today (with timezone offset for accuracy)
    today_str = get_business_date()
    cursor.execute("""
    SELECT 
        COALESCE(SUM(amount_lbp), 0) as collected_today_lbp,
        COALESCE(SUM(amount_usd), 0) as collected_today_usd,
        COUNT(id) as payments_count_today
    FROM debt_payments
    WHERE DATE(datetime(created_at, '-5 hours')) = DATE(?)
    """, (today_str,))
    today_rep = dict(cursor.fetchone() or {})
    active_res['collected_today_lbp'] = today_rep['collected_today_lbp']
    active_res['collected_today_usd'] = today_rep['collected_today_usd']

    conn.close()
    return active_res

def get_customers_debt_balances(search=None):
    """Get grouped balances per customer with remaining debts."""
    conn = get_db()
    cursor = conn.cursor()
    query = """
    SELECT 
        customer_name,
        MAX(phone) as phone,
        COUNT(id) as debts_count,
        COALESCE(SUM(amount_lbp), 0) as total_amount_lbp,
        COALESCE(SUM(paid_lbp), 0) as total_paid_lbp,
        COALESCE(SUM(remaining_lbp), 0) as balance_lbp,
        COALESCE(SUM(remaining_usd), 0) as balance_usd,
        MAX(created_at) as last_debt_date
    FROM customer_debts
    WHERE (status != 'cancelled' OR status IS NULL) AND remaining_lbp > 0
    """
    params = []
    if search:
        query += " AND customer_name LIKE ?"
        params.append(f"%{search.strip()}%")
    query += " GROUP BY customer_name ORDER BY balance_lbp DESC, last_debt_date DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_all_debts(status=None, search=None, limit=100):
    """Get full list of individual debt records with order details."""
    conn = get_db()
    cursor = conn.cursor()
    params = []
    if status == 'cancelled':
        query = "SELECT * FROM customer_debts WHERE status = 'cancelled'"
    else:
        query = "SELECT * FROM customer_debts WHERE (status != 'cancelled' OR status IS NULL)"
        if status == 'active':
            query += " AND remaining_lbp > 0"
        elif status == 'paid':
            query += " AND remaining_lbp <= 0"
    
    if search:
        query += " AND (customer_name LIKE ? OR order_number LIKE ? OR notes LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(query, params)
    debts = [dict(r) for r in cursor.fetchall()]

    for d in debts:
        if d.get('order_id'):
            cursor.execute("SELECT item_name, quantity, unit_price_lbp, subtotal_lbp FROM cafe_order_items WHERE order_id = ?", (d['order_id'],))
            d['order_items'] = [dict(r) for r in cursor.fetchall()]
        else:
            d['order_items'] = []
    conn.close()
    return debts

def pay_debt(debt_id, amount_lbp, payment_method='cash', notes=''):
    """Record payment for a specific debt record."""
    amount_lbp = float(amount_lbp or 0)
    if amount_lbp <= 0:
        return False, "مبلغ السداد يجب أن يكون أكبر من صفر"
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customer_debts WHERE id = ?", (debt_id,))
    debt = cursor.fetchone()
    if not debt:
        conn.close()
        return False, "سجل الدين غير موجود"
    
    debt = dict(debt)
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    amount_usd = round(amount_lbp / rate, 2) if rate > 0 else 0.0

    new_paid_lbp = debt['paid_lbp'] + amount_lbp
    new_paid_usd = round(new_paid_lbp / rate, 2) if rate > 0 else 0.0
    new_remaining_lbp = max(0.0, debt['amount_lbp'] - new_paid_lbp)
    new_remaining_usd = round(new_remaining_lbp / rate, 2) if rate > 0 else 0.0
    new_status = 'paid' if new_remaining_lbp <= 0 else 'partial'

    try:
        # Log payment
        cursor.execute("""
        INSERT INTO debt_payments (debt_id, customer_name, amount_lbp, amount_usd, payment_method, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (debt_id, debt['customer_name'], amount_lbp, amount_usd, payment_method, notes))
        pid = cursor.lastrowid

        # Update debt
        cursor.execute("""
        UPDATE customer_debts SET
            paid_lbp = ?,
            paid_usd = ?,
            remaining_lbp = ?,
            remaining_usd = ?,
            status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (new_paid_lbp, new_paid_usd, new_remaining_lbp, new_remaining_usd, new_status, debt_id))

        conn.commit()
        conn.close()

        # قيد سجل الحركة المالية المركزي لسداد الدين
        if payment_method == 'cash':
            try:
                record_financial_ledger_entry(
                    entry_type='debt_payment',
                    source='customer',
                    destination='drawer',
                    amount_lbp=amount_lbp,
                    amount_usd=amount_usd,
                    reference_table='debt_payments',
                    reference_id=pid,
                    user_name='كاشير',
                    notes=f"سداد دين الزبون: {debt['customer_name']}",
                    exchange_rate=rate,
                    business_date=get_business_date()
                )
            except Exception:
                pass

        # قيد محاسبي مزدوج لسداد الدين: مدين صندوق الكاشير (1010) / دائن ذمة الزبون (1030)
        try:
            dest_acc = '1010' if payment_method == 'cash' else '1020'
            record_double_entry_journal(
                description=f"سداد دين الزبون ({debt['customer_name']})",
                lines=[
                    {'account_code': dest_acc, 'debit_lbp': amount_lbp, 'credit_lbp': 0.0, 'debit_usd': amount_usd, 'credit_usd': 0.0, 'memo': f"قبض نقدي سداد دين #{pid}"},
                    {'account_code': '1030', 'debit_lbp': 0.0, 'credit_lbp': amount_lbp, 'debit_usd': 0.0, 'credit_usd': amount_usd, 'memo': f"تخفيض ذمة الزبون {debt['customer_name']}"}
                ],
                reference_type='debt_payments',
                reference_id=pid,
                user_name='كاشير'
            )
        except Exception:
            pass

        return True, {'debt_id': debt_id, 'paid_lbp': amount_lbp, 'remaining_lbp': new_remaining_lbp, 'status': new_status}
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)

def pay_customer_balance(customer_name, amount_lbp, payment_method='cash', notes=''):
    """Pay off customer debts across multiple records (oldest first)."""
    customer_name = (customer_name or '').strip()
    amount_to_pay = float(amount_lbp or 0)
    if amount_to_pay <= 0:
        return False, "المبلغ يجب أن يكون أكبر من صفر"

    # BUG-FIX: fetch debts then close connection before calling pay_debt
    # (pay_debt opens its own connection internally)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM customer_debts
    WHERE customer_name = ? AND remaining_lbp > 0
    ORDER BY id ASC
    """, (customer_name,))
    debts = [dict(r) for r in cursor.fetchall()]
    conn.close()  # close before calling pay_debt which opens its own connection

    if not debts:
        return False, "لا توجد ديون معلقة لهذا الزبون"

    remaining_payment = amount_to_pay
    for d in debts:
        if remaining_payment <= 0:
            break
        pay_chunk = min(remaining_payment, d['remaining_lbp'])
        pay_debt(d['id'], pay_chunk, payment_method=payment_method, notes=notes)
        remaining_payment -= pay_chunk

    return True, "تم تسجيل دفعة السداد بنجاح وتحديث حساب الزبون!"

def delete_debt(debt_id, cancelled_by='المدير', reason='إلغاء من لوحة الديون'):
    """
    إلغاء دين بطريقة محاسبية آمنة (Non-Destructive Soft Cancel):
    - يضع status='cancelled' بدلاً من الحذف الفيزيائي للحفاظ على مسار التدقيق (Audit Trail)
    - يلغي دفعات السداد المرتبطة بالدين
    - يلغي قيود السجل المالي المركزي المرتبطة بالدين
    - يوثق العملية في سجل التدقيق audit_log
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM customer_debts WHERE id = ?", (debt_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "سجل الدين غير موجود"

        debt = dict(row)
        if debt.get('status') == 'cancelled':
            conn.close()
            return False, "سجل الدين ملغي مسبقاً"

        now_str = get_local_now()
        cancel_note = f"{reason} (بواسطة {cancelled_by})"

        # 1. Soft Cancel Debt
        cursor.execute("""
            UPDATE customer_debts 
            SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP,
                notes = COALESCE(notes, '') || ' | إلغاء: ' || ?
            WHERE id = ?
        """, (cancel_note, debt_id))

        # 2. Mark payments as cancelled
        cursor.execute("""
            UPDATE debt_payments 
            SET notes = COALESCE(notes, '') || ' [ملغى مع إلغاء الدين]'
            WHERE debt_id = ?
        """, (debt_id,))

        # 3. Cancel associated financial ledger entries
        cursor.execute("""
            UPDATE financial_ledger 
            SET status = 'cancelled', cancelled_by = ?, cancelled_at = ?, cancel_reason = ?
            WHERE (reference_table = 'customer_debts' AND reference_id = ?)
               OR (reference_table = 'debt_payments' AND reference_id IN (SELECT id FROM debt_payments WHERE debt_id = ?))
        """, (cancelled_by, now_str, cancel_note, debt_id, debt_id))

        conn.commit()
        conn.close()

        database.write_audit_log(
            actor=cancelled_by,
            action='CANCEL_DEBT',
            table_name='customer_debts',
            record_id=debt_id,
            reason=f"{reason} | دين الزبون: {debt.get('customer_name')} بمبلغ {debt.get('amount_lbp', 0):,.0f} ل.ل"
        )
        return True, "تم إلغاء سجل الدين بنجاح وتوثيق مسار التدقيق المالي"
    except Exception as e:
        logger.error(f"Error in delete_debt: {e}", exc_info=True)
        conn.rollback()
        conn.close()
        return False, str(e)

# ----------------- DATA EXPORT & IMPORT ENGINE -----------------

def export_menu_data():
    """Export all categories and items as a clean dictionary."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, icon, sort_order FROM cafe_categories ORDER BY sort_order ASC, id ASC")
    categories = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("""
    SELECT i.id, i.category_id, c.name as category_name, i.name, i.price_lbp, i.price_usd, i.icon, i.item_type, i.sort_order, i.is_active
    FROM cafe_items i
    LEFT JOIN cafe_categories c ON i.category_id = c.id
    ORDER BY i.sort_order ASC, i.id ASC
    """)
    items = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    return {
        'app': 'STARGATE',
        'type': 'menu_export',
        'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'categories': categories,
        'items': items
    }

def import_menu_data(data):
    """Import categories and items from JSON dictionary."""
    if not isinstance(data, dict) or ('categories' not in data and 'items' not in data):
        return False, "تنسيق البيانات غير صحيح (الملف لا يحتوي على أقسام أو منتجات)"
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        cat_id_map = {}
        # 1. Insert/Find Categories
        for cat in data.get('categories', []):
            name = (cat.get('name') or '').strip()
            if not name:
                continue
            icon = cat.get('icon') or '☕'
            sort_order = int(cat.get('sort_order') or 0)
            
            cursor.execute("SELECT id FROM cafe_categories WHERE name = ?", (name,))
            existing = cursor.fetchone()
            if existing:
                cat_id_map[cat.get('id', name)] = existing['id']
                cat_id_map[name] = existing['id']
            else:
                cursor.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES (?, ?, ?)", (name, icon, sort_order))
                new_id = cursor.lastrowid
                cat_id_map[cat.get('id', name)] = new_id
                cat_id_map[name] = new_id

        # 2. Insert/Update Items
        added_count = 0
        for item in data.get('items', []):
            name = (item.get('name') or '').strip()
            if not name:
                continue
            
            target_cat_id = None
            if item.get('category_id') in cat_id_map:
                target_cat_id = cat_id_map[item.get('category_id')]
            elif item.get('category_name') in cat_id_map:
                target_cat_id = cat_id_map[item.get('category_name')]
            else:
                cursor.execute("SELECT id FROM cafe_categories LIMIT 1")
                first_cat = cursor.fetchone()
                if first_cat:
                    target_cat_id = first_cat['id']
                else:
                    cursor.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES (?, ?, ?)", ('عام', '☕', 1))
                    target_cat_id = cursor.lastrowid
            
            price_lbp = float(item.get('price_lbp') or 0.0)
            price_usd = float(item.get('price_usd') or 0.0)
            icon = item.get('icon') or '☕'
            item_type = item.get('item_type') or 'cafe'
            sort_order = int(item.get('sort_order') or 0)
            is_active = int(item.get('is_active', 1))

            cursor.execute("SELECT id FROM cafe_items WHERE name = ? AND category_id = ?", (name, target_cat_id))
            existing_item = cursor.fetchone()
            if existing_item:
                cursor.execute("""
                UPDATE cafe_items 
                SET price_lbp = ?, price_usd = ?, icon = ?, item_type = ?, sort_order = ?, is_active = ?
                WHERE id = ?
                """, (price_lbp, price_usd, icon, item_type, sort_order, is_active, existing_item['id']))
            else:
                cursor.execute("""
                INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, icon, item_type, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (target_cat_id, name, price_lbp, price_usd, icon, item_type, sort_order, is_active))
                added_count += 1

        conn.commit()
        try:
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        conn.close()
        return True, "تم استيراد قائمة المنيو والأسعار بنجاح وتحديث كافة المنتجات!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, f"فشل أثناء استيراد المنيو: {str(e)}"

def export_full_system_data():
    """Export complete system data (Settings, Categories, Menu, Debts, Expenses, Orders, Inventory, Ledger, Journals) as JSON dictionary."""
    conn = get_db()
    cursor = conn.cursor()
    
    settings = get_settings()
    
    def _fetch_all(table, order_by="id ASC"):
        try:
            cursor.execute(f"SELECT * FROM {table} ORDER BY {order_by}")
            return [dict(r) for r in cursor.fetchall()]
        except Exception:
            return []

    categories = _fetch_all("cafe_categories", "sort_order ASC, id ASC")
    items = _fetch_all("cafe_items", "sort_order ASC, id ASC")
    debts = _fetch_all("customer_debts")
    debt_payments = _fetch_all("debt_payments")
    expenses = _fetch_all("expenses")
    pc_logs = _fetch_all("pc_usage_logs")
    orders = _fetch_all("cafe_orders")
    order_items = _fetch_all("cafe_order_items")
    safe_transfers = _fetch_all("safe_transfers")
    inventory = _fetch_all("inventory")
    recipes = _fetch_all("recipes")
    suppliers = _fetch_all("suppliers")
    purchase_invoices = _fetch_all("purchase_invoices")
    purchase_items = _fetch_all("purchase_invoice_items")
    employees = _fetch_all("employees")
    financial_ledger = _fetch_all("financial_ledger")
    journal_entries = _fetch_all("journal_entries")
    journal_entry_lines = _fetch_all("journal_entry_lines")
    coffee_bag_batches = _fetch_all("coffee_bag_batches")
    
    conn.close()
    
    return {
        'app': 'STARGATE',
        'version': '6.1.0',
        'export_type': 'full_system_backup',
        'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'settings': settings,
        'categories': categories,
        'items': items,
        'debts': debts,
        'debt_payments': debt_payments,
        'expenses': expenses,
        'pc_logs': pc_logs,
        'orders': orders,
        'order_items': order_items,
        'safe_transfers': safe_transfers,
        'inventory': inventory,
        'recipes': recipes,
        'suppliers': suppliers,
        'purchase_invoices': purchase_invoices,
        'purchase_items': purchase_items,
        'employees': employees,
        'financial_ledger': financial_ledger,
        'journal_entries': journal_entries,
        'journal_entry_lines': journal_entry_lines,
        'coffee_bag_batches': coffee_bag_batches
    }

def import_full_system_data(data):
    """Safely restore all system data from full JSON dictionary."""
    if not isinstance(data, dict) or data.get('app') != 'STARGATE':
        return False, "ملف غير صالح أو لا يتبع لنظام STARGATE"

    conn = get_db()
    cursor = conn.cursor()
    try:
        conn.execute("BEGIN IMMEDIATE")

        # 1. Settings
        if 'settings' in data and data['settings']:
            s = data['settings']
            cursor.execute("""
            UPDATE settings 
            SET company_name = ?, exchange_rate = ?, pc_price_per_click_lbp = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """, (s.get('company_name', 'STARGATE'), float(s.get('exchange_rate') or 89500), float(s.get('pc_price_per_click_lbp') or 100000)))

        # 2. Categories & Items
        if 'categories' in data and data['categories']:
            cursor.execute("DELETE FROM cafe_categories")
            for c in data['categories']:
                cursor.execute("INSERT OR REPLACE INTO cafe_categories (id, name, icon, sort_order) VALUES (?, ?, ?, ?)",
                               (c.get('id'), c.get('name'), c.get('icon', '☕'), c.get('sort_order', 0)))

        if 'items' in data and data['items']:
            cursor.execute("DELETE FROM cafe_items")
            for i in data['items']:
                cursor.execute("""
                INSERT OR REPLACE INTO cafe_items (id, category_id, name, price_lbp, price_usd, icon, item_type, sort_order, is_active, stock_qty, track_stock, cost_price_lbp, cost_price_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (i.get('id'), i.get('category_id'), i.get('name'), float(i.get('price_lbp') or 0), float(i.get('price_usd') or 0),
                      i.get('icon', '☕'), i.get('item_type', 'cafe'), i.get('sort_order', 0), int(i.get('is_active', 1)),
                      float(i.get('stock_qty') or 0.0), int(i.get('track_stock') or 0), float(i.get('cost_price_lbp') or 0.0), float(i.get('cost_price_usd') or 0.0)))

        # 3. Debts & Payments
        if 'debts' in data and data['debts']:
            cursor.execute("DELETE FROM customer_debts")
            for d in data['debts']:
                cursor.execute("""
                INSERT OR REPLACE INTO customer_debts (id, customer_name, phone, order_id, order_number, amount_lbp, amount_usd, paid_lbp, paid_usd, remaining_lbp, remaining_usd, status, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (d.get('id'), d.get('customer_name'), d.get('phone', ''), d.get('order_id'), d.get('order_number', ''),
                      float(d.get('amount_lbp') or 0), float(d.get('amount_usd') or 0), float(d.get('paid_lbp') or 0), float(d.get('paid_usd') or 0),
                      float(d.get('remaining_lbp') or 0), float(d.get('remaining_usd') or 0), d.get('status', 'unpaid'), d.get('notes', ''),
                      d.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S')), d.get('updated_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))))

        if 'debt_payments' in data and data['debt_payments']:
            cursor.execute("DELETE FROM debt_payments")
            for p in data['debt_payments']:
                cursor.execute("""
                INSERT OR REPLACE INTO debt_payments (id, debt_id, customer_name, amount_lbp, amount_usd, payment_method, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (p.get('id'), p.get('debt_id'), p.get('customer_name'), float(p.get('amount_lbp') or 0), float(p.get('amount_usd') or 0),
                      p.get('payment_method', 'cash'), p.get('notes', ''), p.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))))

        # 4. Expenses
        if 'expenses' in data and data['expenses']:
            cursor.execute("DELETE FROM expenses")
            for e in data['expenses']:
                cursor.execute("""
                INSERT OR REPLACE INTO expenses (id, title, amount_lbp, amount_usd, category, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (e.get('id'), e.get('title'), float(e.get('amount_lbp') or 0), float(e.get('amount_usd') or 0),
                      e.get('category', 'مصاريف عامة'), e.get('notes', ''), e.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))))

        # 5. Orders & Order Items
        if 'orders' in data and data['orders']:
            cursor.execute("DELETE FROM cafe_orders")
            for o in data['orders']:
                cursor.execute("""
                INSERT OR REPLACE INTO cafe_orders (id, order_number, total_lbp, total_usd, paid_amount, payment_method, customer_name, notes, created_at, status, is_tab, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (o.get('id'), o.get('order_number'), float(o.get('total_lbp') or 0), float(o.get('total_usd') or 0), float(o.get('paid_amount') or 0),
                      o.get('payment_method', 'cash'), o.get('customer_name', 'زبون كاش'), o.get('notes', ''), o.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                      o.get('status', 'paid'), int(o.get('is_tab', 0)), o.get('updated_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))))

        if 'order_items' in data and data['order_items']:
            cursor.execute("DELETE FROM cafe_order_items")
            for oi in data['order_items']:
                cursor.execute("""
                INSERT OR REPLACE INTO cafe_order_items (id, order_id, item_id, item_name, item_type, quantity, unit_price_lbp, unit_price_usd, subtotal_lbp, subtotal_usd, created_at, unit_cost_lbp, unit_cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (oi.get('id'), oi.get('order_id'), oi.get('item_id'), oi.get('item_name'), oi.get('item_type', 'cafe'),
                      int(oi.get('quantity', 1)), float(oi.get('unit_price_lbp') or 0), float(oi.get('unit_price_usd') or 0),
                      float(oi.get('subtotal_lbp') or 0), float(oi.get('subtotal_usd') or 0), oi.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                      float(oi.get('unit_cost_lbp') or 0.0), float(oi.get('unit_cost_usd') or 0.0)))

        # 6. Safe Transfers (سجل الخزنة)
        if 'safe_transfers' in data and data['safe_transfers']:
            cursor.execute("DELETE FROM safe_transfers")
            for st in data['safe_transfers']:
                cursor.execute("""
                INSERT OR REPLACE INTO safe_transfers (id, amount_lbp, amount_usd, note, transferred_by, operation_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (st.get('id'), float(st.get('amount_lbp') or 0), float(st.get('amount_usd') or 0),
                      st.get('note', ''), st.get('transferred_by', 'المدير'), st.get('operation_type', 'deposit'),
                      st.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))))

        # 7. Inventory & Recipes
        if 'inventory' in data and data['inventory']:
            cursor.execute("DELETE FROM inventory")
            for inv in data['inventory']:
                cursor.execute("""
                INSERT OR REPLACE INTO inventory (id, name, unit, stock_qty, min_limit, cost_per_unit, currency, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (inv.get('id'), inv.get('name'), inv.get('unit', 'قطعة'), float(inv.get('stock_qty') or 0.0),
                      float(inv.get('min_limit') or 5.0), float(inv.get('cost_per_unit') or 0.0), inv.get('currency', 'LBP'),
                      inv.get('updated_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))))

        if 'recipes' in data and data['recipes']:
            cursor.execute("DELETE FROM recipes")
            for r in data['recipes']:
                cursor.execute("""
                INSERT OR REPLACE INTO recipes (id, cafe_item_id, inventory_id, required_qty, unit)
                VALUES (?, ?, ?, ?, ?)
                """, (r.get('id'), r.get('cafe_item_id'), r.get('inventory_id'), float(r.get('required_qty') or 1.0), r.get('unit', 'g')))

        conn.commit()
        try:
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        conn.close()
        return True, "تمت استعادة كافة بيانات النظام والمخزون والمنيو والديون بنجاح!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, f"فشل أثناء استعادة البيانات: {str(e)}"

def export_sales_csv():
    """Export sales, debts, and expenses to standard UTF-8 CSV string for Excel."""
    import io
    import csv
    
    output = io.StringIO()
    # Write BOM for Arabic UTF-8 Excel support
    output.write('\ufeff')
    writer = csv.writer(output)
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Orders Section with Detailed Sold Products
    writer.writerow(["=== سجل الفواتير والمبيعات مع بيان المنتجات المباعة ==="])
    writer.writerow(["رقم الفاتورة", "التاريخ والوقت", "اسم الموظف", "اسم الزبون", "المنتجات المباعة بالتفصيل", "الإجمالي (ل.ل)", "الإجمالي ($)", "طريقة الدفع", "الحالة"])
    cursor.execute("""
    SELECT 
        o.order_number, 
        o.created_at, 
        COALESCE(o.employee_name, 'كاشير') as employee_name,
        o.customer_name, 
        o.total_lbp, 
        o.total_usd, 
        o.payment_method, 
        o.status,
        GROUP_CONCAT(i.item_name || ' (الكمية: ' || i.quantity || ')', ' | ') as items_detail
    FROM cafe_orders o
    LEFT JOIN cafe_order_items i ON o.id = i.order_id
    GROUP BY o.id
    ORDER BY o.id DESC
    """)
    for r in cursor.fetchall():
        writer.writerow([
            r['order_number'], 
            r['created_at'], 
            r['employee_name'], 
            r['customer_name'], 
            r['items_detail'] or '-', 
            f"{r['total_lbp']:,.0f}", 
            f"{r['total_usd']:.2f}", 
            r['payment_method'], 
            r['status']
        ])

    writer.writerow([])
    # 1.5 Product-by-Product Total Sales Aggregation
    writer.writerow(["=== إحصائيات مبيعات كل منتج على حدة (الكمية والمبيعات) ==="])
    writer.writerow(["اسم المنتج", "نوع المنتج", "إجمالي الكمية المباعة", "إجمالي المبيعات (ل.ل)", "إجمالي المبيعات ($)"])
    cursor.execute("""
    SELECT 
        i.item_name,
        COALESCE(i.item_type, 'cafe') as item_type,
        SUM(i.quantity) as total_qty,
        SUM(i.subtotal_lbp) as total_lbp,
        SUM(i.subtotal_usd) as total_usd
    FROM cafe_order_items i
    JOIN cafe_orders o ON i.order_id = o.id
    WHERE (o.status = 'paid' OR o.status IS NULL)
    GROUP BY i.item_name
    ORDER BY total_qty DESC
    """)
    for r in cursor.fetchall():
        writer.writerow([r['item_name'], r['item_type'], r['total_qty'], f"{r['total_lbp']:,.0f}", f"{r['total_usd']:.2f}"])
    
    writer.writerow([])
    # 2. Debts Section
    writer.writerow(["=== سجل ديون الزبائن ==="])
    writer.writerow(["اسم الزبون", "رقم الهاتف", "إجمالي الدين (ل.ل)", "المسدد (ل.ل)", "المتبقي (ل.ل)", "المتبقي ($)", "الحالة", "تاريخ التسجيل"])
    cursor.execute("SELECT customer_name, phone, amount_lbp, paid_lbp, remaining_lbp, remaining_usd, status, created_at FROM customer_debts ORDER BY id DESC")
    for r in cursor.fetchall():
        writer.writerow([r['customer_name'], r['phone'], f"{r['amount_lbp']:,.0f}", f"{r['paid_lbp']:,.0f}", f"{r['remaining_lbp']:,.0f}", f"{r['remaining_usd']:.2f}", r['status'], r['created_at']])
    
    writer.writerow([])
    # 3. Expenses Section
    writer.writerow(["=== سجل المصاريف والنثريات ==="])
    writer.writerow(["بند المصروف", "التصنيف", "المبلغ (ل.ل)", "المبلغ ($)", "ملاحظات", "التاريخ"])
    cursor.execute("SELECT title, category, amount_lbp, amount_usd, notes, created_at FROM expenses ORDER BY id DESC")
    for r in cursor.fetchall():
        writer.writerow([r['title'], r['category'], f"{r['amount_lbp']:,.0f}", f"{r['amount_usd']:.2f}", r['notes'], r['created_at']])
        
    conn.close()
    return output.getvalue()





def quick_update_item_field(item_id, field, value):
    """Ultra-fast inline edit for item price (LBP or USD), name, or stock quantity with movement logging."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        settings = get_settings()
        rate = float(settings.get('exchange_rate') or 89500.0)
        updated_data = {}
        if field == 'price_lbp':
            p_lbp = float(value or 0)
            cursor.execute("UPDATE cafe_items SET price_lbp = ? WHERE id = ?", (p_lbp, item_id))
            cursor.execute("SELECT price_usd FROM cafe_items WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            curr_usd = float(row['price_usd'] or 0) if row else 0
            if curr_usd == 0 and rate > 0 and p_lbp > 0:
                p_usd = round(p_lbp / rate, 2)
                cursor.execute("UPDATE cafe_items SET price_usd = ? WHERE id = ?", (p_usd, item_id))
                updated_data = {'price_lbp': p_lbp, 'price_usd': p_usd}
            else:
                updated_data = {'price_lbp': p_lbp}
        elif field == 'price_usd':
            p_usd = float(value or 0)
            cursor.execute("UPDATE cafe_items SET price_usd = ? WHERE id = ?", (p_usd, item_id))
            cursor.execute("SELECT price_lbp FROM cafe_items WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            curr_lbp = float(row['price_lbp'] or 0) if row else 0
            if curr_lbp == 0 and rate > 0 and p_usd > 0:
                p_lbp = round(p_usd * rate, 0)
                cursor.execute("UPDATE cafe_items SET price_lbp = ? WHERE id = ?", (p_lbp, item_id))
                updated_data = {'price_lbp': p_lbp, 'price_usd': p_usd}
            else:
                updated_data = {'price_usd': p_usd}
        elif field == 'wholesale_price_lbp':
            w_lbp = float(value or 0)
            cursor.execute("UPDATE cafe_items SET wholesale_price_lbp = ? WHERE id = ?", (w_lbp, item_id))
            updated_data = {'wholesale_price_lbp': w_lbp}
        elif field == 'wholesale_price_usd':
            w_usd = float(value or 0)
            cursor.execute("UPDATE cafe_items SET wholesale_price_usd = ? WHERE id = ?", (w_usd, item_id))
            updated_data = {'wholesale_price_usd': w_usd}
        elif field == 'cost_price_lbp':
            c_lbp = float(value or 0)
            cursor.execute("UPDATE cafe_items SET cost_price_lbp = ? WHERE id = ?", (c_lbp, item_id))
            updated_data = {'cost_price_lbp': c_lbp}
        elif field == 'cost_price_usd':
            c_usd = float(value or 0)
            cursor.execute("UPDATE cafe_items SET cost_price_usd = ? WHERE id = ?", (c_usd, item_id))
            updated_data = {'cost_price_usd': c_usd}
        elif field == 'stock_qty':
            cursor.execute("SELECT name, stock_qty, cost_price_lbp, cost_price_usd FROM cafe_items WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            if row:
                item_name = row['name']
                old_qty = float(row['stock_qty'] or 0)
                new_qty = float(value or 0)
                if is_coffee_item(item_name, item_id=item_id):
                    cursor.execute("UPDATE cafe_items SET stock_qty = 0, track_stock = 0 WHERE id = ?", (item_id,))
                    updated_data = {'stock_qty': 0, 'track_stock': 0, 'is_coffee': True}
                else:
                    cursor.execute("UPDATE cafe_items SET stock_qty = ?, track_stock = 1 WHERE id = ?", (new_qty, item_id))
                    updated_data = {'stock_qty': new_qty, 'track_stock': 1, 'is_coffee': False}
                    diff = new_qty - old_qty
                    if diff != 0:
                        m_type = 'INVENTORY_ADJUST_IN' if diff > 0 else 'INVENTORY_ADJUST_OUT'
                        cursor.execute("""
                            INSERT INTO stock_movements (
                                movement_type, item_type, item_id, item_name, quantity,
                                qty_before, qty_after, unit_cost_lbp, unit_cost_usd,
                                total_cost_lbp, total_cost_usd, reference_type, reference_id,
                                user_name, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            m_type, 'cafe_item', item_id, item_name, abs(diff),
                            old_qty, new_qty, float(row['cost_price_lbp'] or 0), float(row['cost_price_usd'] or 0),
                            abs(diff) * float(row['cost_price_lbp'] or 0), abs(diff) * float(row['cost_price_usd'] or 0),
                            'MANUAL_ADJUST', item_id, 'الإدارة', 'تعديل جرد يدوي فوري'
                        ))
        elif field == 'is_coffee_bean_linked':
            val = 1 if int(value or 0) == 1 else 0
            if val == 1:
                cursor.execute("UPDATE cafe_items SET is_coffee_bean_linked = 1, track_stock = 0, stock_qty = 0 WHERE id = ?", (item_id,))
            else:
                cursor.execute("UPDATE cafe_items SET is_coffee_bean_linked = 0 WHERE id = ?", (item_id,))
            updated_data = {'is_coffee_bean_linked': val}
        elif field == 'name':
            cursor.execute("UPDATE cafe_items SET name = ? WHERE id = ?", (str(value).strip(), item_id))
            updated_data = {'name': str(value).strip()}
        conn.commit()
        conn.close()
        return True, updated_data
    except Exception as e:
        conn.close()
        return False, str(e)

def get_inventory_stock():
    """Retrieve all items with their stock information, category name, cost, and wholesale prices."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        i.id,
        i.name,
        i.price_lbp,
        i.price_usd,
        COALESCE(i.wholesale_price_lbp, 0) as wholesale_price_lbp,
        COALESCE(i.wholesale_price_usd, 0) as wholesale_price_usd,
        COALESCE(i.cost_price_lbp, 0) as cost_price_lbp,
        COALESCE(i.cost_price_usd, 0) as cost_price_usd,
        i.icon,
        i.item_type,
        i.is_active,
        COALESCE(i.stock_qty, 0) as stock_qty,
        COALESCE(i.track_stock, 0) as track_stock,
        COALESCE(i.low_stock_limit, 5) as low_stock_limit,
        COALESCE(i.is_coffee_bean_linked, 0) as is_coffee_bean_linked,
        COALESCE((
            SELECT SUM(oi.quantity)
            FROM cafe_order_items oi
            JOIN cafe_orders o ON oi.order_id = o.id
            WHERE o.status = 'open' AND oi.item_id = i.id
        ), 0) as on_table_qty,
        c.id as category_id,
        c.name as category_name,
        c.icon as category_icon
    FROM cafe_items i
    LEFT JOIN cafe_categories c ON i.category_id = c.id
    ORDER BY c.sort_order ASC, i.sort_order ASC, i.id ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


# ==========================================
# EMPLOYEE & PERFORMANCE MANAGEMENT FUNCTIONS
# ==========================================

def get_all_employees():
    """Return list of all active/inactive employees."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, name, username, pin, role, phone, is_active, created_at
    FROM employees
    ORDER BY role DESC, name ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_employee_by_id(emp_id):
    """Retrieve a single employee record by ID."""
    if not emp_id:
        return None
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, name, username, pin, role, phone, is_active, created_at
    FROM employees
    WHERE id = ?
    """, (emp_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def add_employee(data):
    """Add new employee with hashed password and PIN."""
    name = (data.get('name') or '').strip()
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    pin = (data.get('pin') or '').strip()
    role = data.get('role', 'cashier').strip()
    phone = (data.get('phone') or '').strip()

    if not name or not username or not password:
        return False, "الاسم، اسم المستخدم، وكلمة المرور حقول مطلوبة"
    if len(password) < 4:
        return False, "كلمة المرور يجب ألا تقل عن 4 أحرف"

    hashed_pwd = hash_password(password)
    hashed_pin = hash_password(pin) if pin else None

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO employees (name, username, password, pin, role, phone, is_active, password_is_hashed)
        VALUES (?, ?, ?, ?, ?, ?, 1, 1)
        """, (name, username, hashed_pwd, hashed_pin, role, phone))
        conn.commit()
        emp_id = cursor.lastrowid
        conn.close()
        return True, emp_id
    except sqlite3.IntegrityError:
        conn.close()
        return False, "اسم المستخدم مستخدم مسبقاً، يرجى اختيار اسم آخر"
    except Exception as e:
        conn.close()
        return False, str(e)

def update_employee(emp_id, data):
    """Update employee details (hashes new password/PIN if provided)."""
    name = (data.get('name') or '').strip()
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    pin = (data.get('pin') or '').strip()
    role = data.get('role', 'cashier').strip()
    phone = (data.get('phone') or '').strip()
    is_active = 1 if data.get('is_active') in (1, '1', True, 'on') else 0

    conn = get_db()
    cursor = conn.cursor()
    try:
        if password:
            if len(password) < 4:
                conn.close()
                return False, "كلمة المرور يجب ألا تقل عن 4 أحرف"
            hashed_pwd = hash_password(password)
            hashed_pin = hash_password(pin) if pin else None
            cursor.execute("""
            UPDATE employees SET name=?, username=?, password=?, pin=?,
                                 role=?, phone=?, is_active=?, password_is_hashed=1
            WHERE id=?
            """, (name, username, hashed_pwd, hashed_pin, role, phone, is_active, emp_id))
        else:
            if pin:
                hashed_pin = hash_password(pin)
                cursor.execute("""
                UPDATE employees SET name=?, username=?, pin=?,
                                     role=?, phone=?, is_active=?
                WHERE id=?
                """, (name, username, hashed_pin, role, phone, is_active, emp_id))
            else:
                cursor.execute("""
                UPDATE employees SET name=?, username=?, role=?, phone=?, is_active=?
                WHERE id=?
                """, (name, username, role, phone, is_active, emp_id))
        conn.commit()
        conn.close()
        return True, "تم تعديل بيانات الموظف بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)

def delete_employee(emp_id):
    """Permanently delete employee."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Preserve historic employee name on orders
        cursor.execute("SELECT name FROM employees WHERE id = ?", (emp_id,))
        row = cursor.fetchone()
        emp_name = row['name'] if row else 'موظف محذوف'
        cursor.execute("UPDATE cafe_orders SET employee_name = ? WHERE employee_id = ?", (emp_name, emp_id))
        cursor.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
        conn.commit()
        conn.close()
        return True, "تم حذف الموظف بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)

def authenticate_employee(identifier, secret):
    """
    Authenticate employee by username+password OR by quick PIN.
    Supports hashed passwords with transparent legacy plain-text upgrade.
    """
    conn = get_db()
    cursor = conn.cursor()

    if secret is None or secret == '':
        # PIN-based login: retrieve candidates and verify hash
        cursor.execute(
            "SELECT * FROM employees WHERE is_active=1",
        )
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            stored_pin = row['pin'] or ''
            if stored_pin and verify_password(identifier, stored_pin):
                emp = dict(row)
                _auto_upgrade_pin(emp, identifier)
                return emp
        return None
    else:
        # Username + password login
        cursor.execute(
            "SELECT * FROM employees WHERE username=? AND is_active=1",
            (identifier,)
        )
        row = cursor.fetchone()
        conn.close()
        if row and verify_password(secret, row['password'] or ''):
            emp = dict(row)
            _auto_upgrade_password(emp, secret)
            return emp
        return None


def _auto_upgrade_pin(emp, plain_pin):
    """If PIN was stored as plain text, upgrade to hash silently."""
    if not _needs_hash_upgrade(emp.get('pin', '')):
        return
    try:
        conn = get_db()
        conn.execute(
            "UPDATE employees SET pin=?, password_is_hashed=1 WHERE id=?",
            (hash_password(plain_pin), emp['id'])
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _auto_upgrade_password(emp, plain_pwd):
    """If password was stored as plain text, upgrade to hash silently."""
    if not _needs_hash_upgrade(emp.get('password', '')):
        return
    try:
        conn = get_db()
        conn.execute(
            "UPDATE employees SET password=?, password_is_hashed=1 WHERE id=?",
            (hash_password(plain_pwd), emp['id'])
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_employee_performance_summary(target_date=None, all_time=False):
    """Return breakdown of orders count and revenue generated by each employee (daily or all-time)."""
    conn = get_db()
    cursor = conn.cursor()
    
    if all_time:
        cursor.execute("""
        SELECT 
            COALESCE(e.id, 0) as employee_id,
            COALESCE(e.name, o.employee_name, 'كاشير عام') as employee_name,
            COALESCE(e.role, 'cashier') as role,
            COUNT(o.id) as orders_count,
            COALESCE(SUM(o.total_lbp), 0) as total_lbp,
            COALESCE(SUM(o.total_usd), 0) as total_usd,
            COALESCE(SUM(CASE WHEN o.payment_method = 'cash' THEN o.total_lbp ELSE 0 END), 0) as cash_lbp,
            COALESCE(SUM(CASE WHEN o.payment_method = 'debt' THEN o.total_lbp ELSE 0 END), 0) as debt_lbp
        FROM cafe_orders o
        LEFT JOIN employees e ON o.employee_id = e.id
        WHERE (o.status = 'paid' OR o.status IS NULL)
        GROUP BY COALESCE(e.id, 0), COALESCE(e.name, o.employee_name, 'كاشير عام')
        ORDER BY total_lbp DESC
        """)
    else:
        target_date = target_date or get_business_date()
        cursor.execute("""
        SELECT 
            COALESCE(e.id, 0) as employee_id,
            COALESCE(e.name, o.employee_name, 'كاشير عام') as employee_name,
            COALESCE(e.role, 'cashier') as role,
            COUNT(o.id) as orders_count,
            COALESCE(SUM(o.total_lbp), 0) as total_lbp,
            COALESCE(SUM(o.total_usd), 0) as total_usd,
            COALESCE(SUM(CASE WHEN o.payment_method = 'cash' THEN o.total_lbp ELSE 0 END), 0) as cash_lbp,
            COALESCE(SUM(CASE WHEN o.payment_method = 'debt' THEN o.total_lbp ELSE 0 END), 0) as debt_lbp
        FROM cafe_orders o
        LEFT JOIN employees e ON o.employee_id = e.id
        WHERE DATE(datetime(o.created_at, '-5 hours')) = DATE(?) AND (o.status = 'paid' OR o.status IS NULL)
        GROUP BY COALESCE(e.id, 0), COALESCE(e.name, o.employee_name, 'كاشير عام')
        ORDER BY total_lbp DESC
        """, (target_date,))
        
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


# ============================================================

# ============================================================
# 🏦 وظائف الخزنة الخاصة والمحاسبة المركزية (Advanced Safe/Vault Management)
# ============================================================

def add_safe_transfer(amount_lbp=0.0, note='', transferred_by='المدير', rate=None, amount_usd=None, operation_type='deposit', employee_id=None, source='drawer', target='safe', employee_name=None):
    """نقل أو سحب مبلغ من/إلى الخزنة الخاصة مع التمييز الدقيق بين مصادر النقدية والوجهات وتوثيقه في السجل المالي."""
    if employee_name and (not transferred_by or transferred_by == 'المدير'):
        transferred_by = employee_name
    transferred_by = transferred_by or 'المدير'
    note = note or ''
    settings = get_settings()
    rate = rate or float(settings.get('exchange_rate') or 89500.0)
    amount_lbp = float(amount_lbp or 0.0)
    op_type = 'withdraw' if str(operation_type).lower() in ('withdraw', 'سحب', 'out') else 'deposit'

    if amount_usd is not None and float(amount_usd) > 0 and amount_lbp <= 0:
        amount_usd = float(amount_usd)
        amount_lbp = round(amount_usd * rate, 0)
    elif amount_usd is not None and float(amount_usd) > 0 and amount_lbp > 0:
        amount_usd = float(amount_usd)
    else:
        amount_usd = round(amount_lbp / rate, 2) if rate > 0 else 0.0

    if amount_lbp <= 0 and (amount_usd is None or float(amount_usd) <= 0):
        return None

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE safe_transfers ADD COLUMN employee_id INTEGER")
        cursor.execute("ALTER TABLE safe_transfers ADD COLUMN source TEXT DEFAULT 'drawer'")
        cursor.execute("ALTER TABLE safe_transfers ADD COLUMN target TEXT DEFAULT 'safe'")
        cursor.execute("ALTER TABLE safe_transfers ADD COLUMN employee_name TEXT DEFAULT 'المدير'")
        cursor.execute("ALTER TABLE safe_transfers ADD COLUMN status TEXT DEFAULT 'active'")
        cursor.execute("ALTER TABLE safe_transfers ADD COLUMN cancelled_by TEXT")
        cursor.execute("ALTER TABLE safe_transfers ADD COLUMN cancelled_at TIMESTAMP")
        cursor.execute("ALTER TABLE safe_transfers ADD COLUMN cancel_reason TEXT")
        conn.commit()
    except Exception:
        pass

    # 1. حماية ضد النقر المزدوج والتكرار السريع (Idempotency Lock - 10s)
    cursor.execute("""
        SELECT id FROM safe_transfers 
        WHERE amount_lbp = ? AND operation_type = ? AND source = ? AND target = ? AND status = 'active'
          AND datetime(created_at) >= datetime('now', '-10 seconds')
        ORDER BY id DESC LIMIT 1
    """, (amount_lbp, op_type, source, target))
    dup_row = cursor.fetchone()
    if dup_row:
        conn.close()
        return dup_row[0]

    # 2. ضمان نقل كامل المبلغ المتاح في الدرج دون أي اقتطاع أو تعليق
    if op_type == 'deposit' and source == 'drawer':
        try:
            drawer_curr = get_drawer_cash_status()
            drawer_avail = float(drawer_curr.get('total_untransferred_lbp') or 0.0)
            if amount_lbp >= (drawer_avail - 100.0) and drawer_avail > 0:
                amount_lbp = drawer_avail
                amount_usd = round(amount_lbp / rate, 2) if rate > 0 else 0.0
        except Exception:
            pass

    now_str = get_local_now()
    cursor.execute("""
        INSERT INTO safe_transfers (amount_lbp, amount_usd, note, transferred_by, operation_type, source, target, employee_id, employee_name, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
    """, (amount_lbp, amount_usd, note.strip(), transferred_by.strip(), op_type, source, target, employee_id, transferred_by.strip(), now_str))
    conn.commit()
    transfer_id = cursor.lastrowid
    conn.close()

    # تسجيل في سجل الحركة المالية المركزي
    try:
        if op_type == 'deposit' and source == 'drawer':
            l_type = 'drawer_to_safe'
            l_src = 'drawer'
            l_dst = 'safe'
        elif op_type == 'deposit':
            l_type = 'safe_deposit'
            l_src = 'external'
            l_dst = 'safe'
        elif op_type == 'withdraw' and target == 'drawer':
            l_type = 'safe_to_drawer'
            l_src = 'safe'
            l_dst = 'drawer'
        else:
            l_type = 'safe_withdraw'
            l_src = 'safe'
            l_dst = 'external'

        record_financial_ledger_entry(
            entry_type=l_type,
            source=l_src,
            destination=l_dst,
            amount_lbp=amount_lbp,
            amount_usd=amount_usd,
            reference_table='safe_transfers',
            reference_id=transfer_id,
            user_id=employee_id,
            user_name=transferred_by,
            notes=note or 'حركة خزنة خاصة',
            exchange_rate=rate,
            business_date=get_business_date()
        )

        # Double Entry Accounting for Safe Transfers
        if l_type == 'drawer_to_safe':
            # Debit Safe (1020), Credit Drawer (1010)
            record_double_entry_journal(
                description=f"تحويل كاش من الدرج إلى الخزنة: {note or ''}",
                lines=[
                    {'account_code': '1020', 'debit_lbp': amount_lbp, 'credit_lbp': 0.0, 'debit_usd': amount_usd, 'credit_usd': 0.0, 'memo': 'إيداع بالخزنة'},
                    {'account_code': '1010', 'debit_lbp': 0.0, 'credit_lbp': amount_lbp, 'debit_usd': 0.0, 'credit_usd': amount_usd, 'memo': 'صادر من الدرج'}
                ],
                reference_type='safe_transfers',
                reference_id=transfer_id,
                user_name=transferred_by
            )
        elif l_type == 'safe_to_drawer':
            # Debit Drawer (1010), Credit Safe (1020)
            record_double_entry_journal(
                description=f"سحب كاش من الخزنة إلى الدرج: {note or ''}",
                lines=[
                    {'account_code': '1010', 'debit_lbp': amount_lbp, 'credit_lbp': 0.0, 'debit_usd': amount_usd, 'credit_usd': 0.0, 'memo': 'وارد للدرج'},
                    {'account_code': '1020', 'debit_lbp': 0.0, 'credit_lbp': amount_lbp, 'debit_usd': 0.0, 'credit_usd': amount_usd, 'memo': 'صادر من الخزنة'}
                ],
                reference_type='safe_transfers',
                reference_id=transfer_id,
                user_name=transferred_by
            )
    except Exception:
        pass

    return transfer_id


def cancel_safe_transfer(transfer_id: int, cancelled_by: str = 'المدير', reason: str = ''):
    """
    إلغاء حركة خزنة خاصة مع الحفاظ التام على السجل وتوثيق سبب الإلغاء ومنع الحذف النهائي.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM safe_transfers WHERE id = ?", (transfer_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "الحركة غير موجودة"

    st = dict(row)
    if st.get('status') == 'cancelled':
        conn.close()
        return False, "الحركة ملغاة مسبقاً"

    now_str = get_local_now()
    cursor.execute("""
        UPDATE safe_transfers 
        SET status = 'cancelled', cancelled_by = ?, cancelled_at = ?, cancel_reason = ? 
        WHERE id = ?
    """, (cancelled_by, now_str, (reason or 'إلغاء حركة خزنة').strip(), transfer_id))

    cursor.execute("""
        UPDATE financial_ledger
        SET status = 'cancelled', cancelled_by = ?, cancelled_at = ?, cancel_reason = ?
        WHERE reference_table = 'safe_transfers' AND reference_id = ?
    """, (cancelled_by, now_str, (reason or 'إلغاء حركة خزنة').strip(), transfer_id))

    conn.commit()
    conn.close()

    database.write_audit_log(
        actor=cancelled_by,
        action='CANCEL_SAFE_TRANSFER',
        table_name='safe_transfers',
        record_id=transfer_id,
        reason=reason
    )
    return True, "تم إلغاء الحركة وتحديث رصيد الخزنة بنجاح"


def get_safe_transfers(start_date=None, end_date=None, search_query=None, limit=500, target_date=None):
    """
    جلب سجل عمليات الخزنة مع البحث بالتواريخ (يوم محدد أو فترة من - إلى) والبحث النصي والحالة.
    """
    if target_date and not start_date:
        if str(target_date).lower() != 'all':
            start_date = target_date
            end_date = target_date

    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM safe_transfers WHERE 1=1"
    params = []

    if start_date and str(start_date).lower() != 'all':
        if end_date and end_date != start_date:
            query += " AND DATE(datetime(created_at, '-5 hours')) >= DATE(?) AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)"
            params.extend([start_date, end_date])
        else:
            query += " AND (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))"
            params.extend([start_date, start_date])

    if search_query and search_query.strip():
        q = f"%{search_query.strip()}%"
        query += " AND (note LIKE ? OR transferred_by LIKE ?)"
        params.extend([q, q])

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Format fields
    for r in rows:
        r['operation_type'] = r.get('operation_type') or 'deposit'
        r['is_withdraw'] = (r['operation_type'] == 'withdraw')
        r['type_label'] = 'سحب / صادر 🔴' if r['is_withdraw'] else 'إيداع / وارد 🟢'
        r['is_cancelled'] = (r.get('status') == 'cancelled')
        r['status_badge'] = 'ملغاة 🚫' if r['is_cancelled'] else 'نشطة ومحسوبة 🟢'
    return rows


def get_safe_balance():
    """
    حساب الرصيد الإجمالي الحقيقي للخزنة اعتماداً على سجل الحركة المالية المركزي المزدوج (financial_ledger):
    SUM(destination = 'safe' - source = 'safe') لجميع العمليات النشطة غير الملغاة.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN destination = 'safe' AND (status = 'active' OR status IS NULL) THEN amount_lbp ELSE 0 END), 0) as total_deposit_lbp,
            COALESCE(SUM(CASE WHEN source = 'safe' AND (status = 'active' OR status IS NULL) THEN amount_lbp ELSE 0 END), 0) as total_withdraw_lbp,
            COALESCE(SUM(CASE WHEN destination = 'safe' AND (status = 'active' OR status IS NULL) THEN amount_usd ELSE 0 END), 0) as total_deposit_usd,
            COALESCE(SUM(CASE WHEN source = 'safe' AND (status = 'active' OR status IS NULL) THEN amount_usd ELSE 0 END), 0) as total_withdraw_usd,
            COUNT(CASE WHEN (destination = 'safe' OR source = 'safe') AND (status = 'active' OR status IS NULL) THEN id END) as transfers_count
        FROM financial_ledger
    """)
    row = dict(cursor.fetchone() or {})
    
    cnt = int(row.get('transfers_count') or 0)
    # إذا لم توجد حركات في الليدجر بعد، نرجع كاحتياط إلى safe_transfers القديم لضمان عدم تأثر البيانات السابقة
    if cnt == 0:
        cursor.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_lbp END), 0) as total_deposit_lbp,
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_lbp ELSE 0 END), 0) as total_withdraw_lbp,
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_usd END), 0) as total_deposit_usd,
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_usd ELSE 0 END), 0) as total_withdraw_usd,
                COUNT(id) as transfers_count
            FROM safe_transfers
            WHERE (status != 'cancelled' OR status IS NULL)
        """)
        row = dict(cursor.fetchone() or {})
        cnt = int(row.get('transfers_count') or 0)
    else:
        # مطابقة ذكية: أي حركة خزنة نشطة لم يُكتب لها قيد في السجل المركزي (بسبب قفل/خطأ) تُحتسب فوراً
        # حتى لا يظهر المبلغ "معلقاً" أبداً
        try:
            cursor.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_lbp END), 0),
                    COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_lbp ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_usd END), 0),
                    COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_usd ELSE 0 END), 0),
                    COUNT(id)
                FROM safe_transfers st
                WHERE (st.status != 'cancelled' OR st.status IS NULL)
                  AND COALESCE(st.target, 'safe') != 'expense'
                  AND NOT EXISTS (
                      SELECT 1 FROM financial_ledger fl
                      WHERE fl.reference_table = 'safe_transfers' AND fl.reference_id = st.id
                  )
            """)
            orphan = cursor.fetchone()
            if orphan and int(orphan[4] or 0) > 0:
                row['total_deposit_lbp'] = float(row.get('total_deposit_lbp') or 0) + float(orphan[0] or 0)
                row['total_withdraw_lbp'] = float(row.get('total_withdraw_lbp') or 0) + float(orphan[1] or 0)
                row['total_deposit_usd'] = float(row.get('total_deposit_usd') or 0) + float(orphan[2] or 0)
                row['total_withdraw_usd'] = float(row.get('total_withdraw_usd') or 0) + float(orphan[3] or 0)
                cnt += int(orphan[4] or 0)
        except Exception as e:
            logger.warning(f"Safe orphan reconciliation skipped: {e}")

    conn.close()

    dep_lbp = float(row.get('total_deposit_lbp') or 0.0)
    wth_lbp = float(row.get('total_withdraw_lbp') or 0.0)
    bal_lbp = dep_lbp - wth_lbp

    dep_usd = float(row.get('total_deposit_usd') or 0.0)
    wth_usd = float(row.get('total_withdraw_usd') or 0.0)
    bal_usd = dep_usd - wth_usd

    return {
        'total_lbp': bal_lbp,
        'total_usd': bal_usd,
        'balance_lbp': bal_lbp,
        'balance_usd': bal_usd,
        'total_deposit_lbp': dep_lbp,
        'total_deposit_usd': dep_usd,
        'total_withdraw_lbp': wth_lbp,
        'total_withdraw_usd': wth_usd,
        'transfers_count': cnt
    }


def get_safe_daily_summary(target_date=None, start_date=None, end_date=None):
    """ملخص حركة الخزنة لفترة محددة (اليوم أو نطاق زمني) مع استبعاد الحركات الملغاة."""
    target_date = target_date or start_date or get_business_date()
    end_date = end_date or target_date

    conn = get_db()
    cursor = conn.cursor()
    if start_date and end_date and start_date != end_date:
        cursor.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_lbp END), 0) as deposit_lbp,
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_lbp ELSE 0 END), 0) as withdraw_lbp,
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_usd END), 0) as deposit_usd,
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_usd ELSE 0 END), 0) as withdraw_usd,
                COUNT(id) as transfers_count
            FROM safe_transfers
            WHERE (status != 'cancelled' OR status IS NULL)
              AND DATE(datetime(created_at, '-5 hours')) >= DATE(?) AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)
        """, (start_date, end_date))
    else:
        cursor.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_lbp END), 0) as deposit_lbp,
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_lbp ELSE 0 END), 0) as withdraw_lbp,
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_usd END), 0) as deposit_usd,
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_usd ELSE 0 END), 0) as withdraw_usd,
                COUNT(id) as transfers_count
            FROM safe_transfers
            WHERE (status != 'cancelled' OR status IS NULL)
              AND (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
        """, (target_date, target_date))

    row = dict(cursor.fetchone() or {})
    conn.close()

    dep_lbp = float(row.get('deposit_lbp') or 0.0)
    wth_lbp = float(row.get('withdraw_lbp') or 0.0)
    net_lbp = dep_lbp - wth_lbp

    dep_usd = float(row.get('deposit_usd') or 0.0)
    wth_usd = float(row.get('withdraw_usd') or 0.0)
    net_usd = dep_usd - wth_usd

    return {
        'day_total_lbp': dep_lbp,
        'day_total_usd': dep_usd,
        'deposit_lbp': dep_lbp,
        'deposit_usd': dep_usd,
        'withdraw_lbp': wth_lbp,
        'withdraw_usd': wth_usd,
        'net_lbp': net_lbp,
        'net_usd': net_usd,
        'transfers_count': int(row.get('transfers_count') or 0)
    }


def delete_safe_transfer(transfer_id):
    """حذف عملية خزنة."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM safe_transfers WHERE id = ?", (transfer_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0


def get_safe_weekly_summary():
    """ملخص الخزنة للأيام الـ 7 الأخيرة."""
    from datetime import datetime, timedelta
    days = []
    today = datetime.now()
    conn = get_db()
    cursor = conn.cursor()
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        cursor.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_lbp END), 0) as deposit_lbp,
                COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_lbp ELSE 0 END), 0) as withdraw_lbp,
                COUNT(id) as count
            FROM safe_transfers
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
        """, (d, d))
        row = dict(cursor.fetchone() or {})
        row['date'] = d
        row['total_lbp'] = float(row.get('deposit_lbp') or 0) - float(row.get('withdraw_lbp') or 0)
        days.append(row)
    conn.close()
    return days

def get_drawer_cash_status():
    """
    حساب وضع الكاش الفعلي في درج الكاشير بصورة تراكمية:
    الصيغة الصحيحة: كاش الدرج = (كل مبيعات الكاش + كل سدادات الديون) - (كل المصاريف + كل ما رُحِّل للخزنة)
    """
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    today_bdate = get_business_date()

    conn = get_db()
    cursor = conn.cursor()

    # 1. إجمالي مبيعات الكاش عبر كل التاريخ
    cursor.execute("""
        SELECT COALESCE(SUM(total_lbp), 0)
        FROM cafe_orders
        WHERE payment_method = 'cash' AND (status != 'cancelled' AND (status != 'open' OR is_tab = 0))
    """)
    all_cash_sales_lbp = float(cursor.fetchone()[0] or 0.0)

    # 2. مبيعات كاش اليوم
    cursor.execute("""
        SELECT COALESCE(SUM(total_lbp), 0)
        FROM cafe_orders
        WHERE payment_method = 'cash' AND (status != 'cancelled' AND (status != 'open' OR is_tab = 0))
          AND DATE(datetime(created_at, '-5 hours')) = DATE(?)
    """, (today_bdate,))
    today_cash_sales_lbp = float(cursor.fetchone()[0] or 0.0)

    # 3. مبيعات كاش الأمس والفترات السابقة
    past_cash_sales_lbp = max(0.0, all_cash_sales_lbp - today_cash_sales_lbp)

    # 4. إجمالي سدادات الديون المستلمة عبر كل التاريخ
    cursor.execute("SELECT COALESCE(SUM(amount_lbp), 0) FROM debt_payments")
    all_debt_rep_lbp = float(cursor.fetchone()[0] or 0.0)

    # 5. إجمالي المصاريف المسددة من الدرج عبر كل التاريخ (المصاريف من الخزنة لا تخصم من الدرج)
    cursor.execute("SELECT COALESCE(SUM(amount_lbp), 0) FROM expenses WHERE (source != 'safe' OR source IS NULL) AND (status != 'cancelled' OR status IS NULL)")
    all_expenses_lbp = float(cursor.fetchone()[0] or 0.0)

    # 6. إجمالي ما رُحِّل للخزنة الخاصة من الدرج (خصماً من الدرج)
    # ملاحظة جوهرية: مسحوبات الخزنة الشخصية للمدير لا تُعاد للدرج إلا إذا حُدد صراحة أنها تمويل للدرج (target='drawer')
    cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN operation_type = 'deposit' AND (source != 'external' OR source IS NULL) THEN amount_lbp ELSE 0 END), 0) as deposits_from_drawer,
            COALESCE(SUM(CASE WHEN operation_type = 'withdraw' AND target = 'drawer' THEN amount_lbp ELSE 0 END), 0) as returned_to_drawer
        FROM safe_transfers
        WHERE (status != 'cancelled' OR status IS NULL)
    """)
    safe_row = cursor.fetchone()
    total_safe_deposits_lbp = float(safe_row[0] or 0.0)
    total_returned_to_drawer_lbp = float(safe_row[1] or 0.0)
    # الكاش الصافي الذي خرج من الدرج باتجاه الخزنة
    net_to_safe_lbp = max(0.0, total_safe_deposits_lbp - total_returned_to_drawer_lbp)

    # 7. إجمالي مسحوبات أرباح المالك المسحوبة مباشرة من الدرج (سحب نهاية الشهر / مسحوبات شخصية)
    try:
        cursor.execute("""
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM owner_drawings
            WHERE (source = 'drawer' OR source IS NULL) AND (status != 'cancelled' OR status IS NULL)
        """)
        all_owner_drawings_from_drawer_lbp = float(cursor.fetchone()[0] or 0.0)
    except Exception:
        all_owner_drawings_from_drawer_lbp = 0.0

    # 8. إجمالي العهد وفكة البداية المودعة في الدرج
    try:
        cursor.execute("""
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM financial_ledger
            WHERE destination = 'drawer' AND entry_type IN ('shift_opening_float', 'drawer_float', 'drawer_topup')
              AND (status = 'active' OR status IS NULL)
        """)
        all_floats_to_drawer_lbp = float(cursor.fetchone()[0] or 0.0)
    except Exception:
        all_floats_to_drawer_lbp = 0.0

    # ⚖️ المعادلة المحاسبية الصارمة لكاش الدرج الفعلي اللحظي:
    # كاش الدرج = (كل مبيعات الكاش + سدادات الديون المستلمة + فكة البداية) - (مصاريف الدرج + ما رُحِّل للخزنة + مسحوبات أرباح المالك من الدرج)
    total_cash_in = all_cash_sales_lbp + all_debt_rep_lbp + all_floats_to_drawer_lbp
    total_cash_out = all_expenses_lbp + net_to_safe_lbp + all_owner_drawings_from_drawer_lbp
    calculated_cash_drawer_lbp = max(0.0, total_cash_in - total_cash_out)
    calculated_cash_drawer_usd = round(calculated_cash_drawer_lbp / rate, 2) if rate > 0 else 0.0

    # مزامنة رصيد الحساب المالي الدفتري (Account 1010) تلقائياً ليكون مطابقاً 100% للواقع
    try:
        cursor.execute("UPDATE accounts SET balance_lbp = ?, balance_usd = ? WHERE code = '1010'",
                       (calculated_cash_drawer_lbp, calculated_cash_drawer_usd))
        conn.commit()
    except Exception:
        pass

    # احتساب تفصيل مبيعات كاش اليوم بين الألعاب/الكمبيوتر والمشروبات/الكافيه
    cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN (i.item_type IN ('gaming', 'computer') OR i.item_name LIKE '%GAMING%' OR i.item_name LIKE '%ألعاب%' OR i.item_name LIKE '%العاب%' OR i.item_name LIKE '%كمبيوتر%' OR i.item_name LIKE '%بلايستيشن%') 
                              THEN (i.subtotal_lbp * (CASE WHEN o.subtotal_lbp > 0 THEN o.total_lbp / o.subtotal_lbp ELSE 1.0 END)) 
                              ELSE 0 END), 0) as today_gaming_cash_lbp,
            COALESCE(SUM(CASE WHEN (i.item_type NOT IN ('gaming', 'computer') AND (i.item_name NOT LIKE '%GAMING%' AND i.item_name NOT LIKE '%ألعاب%' AND i.item_name NOT LIKE '%العاب%' AND i.item_name NOT LIKE '%كمبيوتر%' AND i.item_name NOT LIKE '%بلايستيشن%')) 
                              THEN (i.subtotal_lbp * (CASE WHEN o.subtotal_lbp > 0 THEN o.total_lbp / o.subtotal_lbp ELSE 1.0 END)) 
                              ELSE 0 END), 0) as today_cafe_cash_lbp
        FROM cafe_order_items i
        JOIN cafe_orders o ON i.order_id = o.id
        WHERE o.payment_method = 'cash' AND (o.status != 'cancelled' AND (o.status != 'open' OR o.is_tab = 0))
          AND DATE(datetime(o.created_at, '-5 hours')) = DATE(?)
    """, (today_bdate,))
    breakdown_row = cursor.fetchone()
    today_gaming_cash_lbp = float(breakdown_row[0] or 0.0) if breakdown_row else 0.0
    today_cafe_cash_lbp = float(breakdown_row[1] or 0.0) if breakdown_row else 0.0

    conn.close()

    total_untransferred_lbp = calculated_cash_drawer_lbp
    total_untransferred_usd = calculated_cash_drawer_usd

    # نسبة الألعاب والمشروبات المتبقية في الدرج بانتظار الترحيل للخزنة
    if total_untransferred_lbp <= 0:
        untransferred_pc_lbp = 0.0
        untransferred_cafe_lbp = 0.0
        is_gaming_transferred = True
        is_cafe_transferred = True
    else:
        tot_today_cash = today_gaming_cash_lbp + today_cafe_cash_lbp
        if tot_today_cash > 0:
            untransferred_pc_lbp = min(today_gaming_cash_lbp, round(total_untransferred_lbp * (today_gaming_cash_lbp / tot_today_cash), 0))
            untransferred_cafe_lbp = max(0.0, total_untransferred_lbp - untransferred_pc_lbp)
        else:
            untransferred_pc_lbp = 0.0
            untransferred_cafe_lbp = total_untransferred_lbp
        is_gaming_transferred = (untransferred_pc_lbp <= 0)
        is_cafe_transferred = (untransferred_cafe_lbp <= 0)

    # الكاش السابق (قبل اليوم) غير المرحّل للخزنة
    if all_cash_sales_lbp > 0:
        past_ratio = past_cash_sales_lbp / all_cash_sales_lbp
    else:
        past_ratio = 0.0
    past_untransferred_lbp = round(total_untransferred_lbp * past_ratio, 0)
    past_untransferred_usd = round(past_untransferred_lbp / rate, 2) if rate > 0 else 0.0

    return {
        'all_cash_sales_lbp': all_cash_sales_lbp,
        'today_cash_sales_lbp': today_cash_sales_lbp,
        'today_gaming_cash_lbp': today_gaming_cash_lbp,
        'today_cafe_cash_lbp': today_cafe_cash_lbp,
        'untransferred_pc_lbp': untransferred_pc_lbp,
        'untransferred_cafe_lbp': untransferred_cafe_lbp,
        'is_gaming_transferred': is_gaming_transferred,
        'is_cafe_transferred': is_cafe_transferred,
        'past_cash_sales_lbp': past_cash_sales_lbp,
        'past_untransferred_lbp': past_untransferred_lbp,
        'past_untransferred_usd': past_untransferred_usd,
        'total_untransferred_lbp': total_untransferred_lbp,
        'total_untransferred_usd': total_untransferred_usd,
        'all_transferred_to_safe_lbp': net_to_safe_lbp,
        'all_debt_rep_lbp': all_debt_rep_lbp,
        'all_expenses_lbp': all_expenses_lbp,
        'all_owner_drawings_lbp': all_owner_drawings_from_drawer_lbp,
        'all_floats_lbp': all_floats_to_drawer_lbp,
        'exact_drawer_account_lbp': calculated_cash_drawer_lbp,
        'exact_drawer_account_usd': calculated_cash_drawer_usd
    }


def record_owner_drawing(
    amount_lbp: float = 0.0,
    amount_usd: float = 0.0,
    source: str = 'drawer',
    drawing_type: str = 'monthly_profit',
    month_period: str = '',
    drawn_by: str = 'المدير',
    notes: str = ''
) -> dict:
    """
    سحب أرباح المالك أو مسحوبات شخصية من الدرج أو الخزنة (نهاية الشهر أو دوري):
    - يخصم فوراً من كاش الدرج (إذا كان المصدر الدرج) أو الخزنة (إذا كان المصدر الخزنة).
    - يوثق في جدول owner_drawings مع توثيق اسم الساحب والفترة والملاحظات.
    - يسجل قيداً محاسبياً مزدوجاً: من ح/ مسحوبات المالك وتوزيع الأرباح (3030) إلى ح/ الصندوق (1010 أو 1020).
    - يسجل في سجل الحركة المالية المركزي (financial_ledger).
    """
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    amount_lbp = float(amount_lbp or 0.0)
    amount_usd = float(amount_usd or 0.0)

    if amount_usd > 0 and amount_lbp <= 0:
        amount_lbp = round(amount_usd * rate, 0)
    elif amount_lbp > 0 and amount_usd <= 0:
        amount_usd = round(amount_lbp / rate, 2)

    if amount_lbp <= 0 and amount_usd <= 0:
        raise ValueError("الرجاء إدخال مبلغ صحيح لمسحوبات الأرباح.")

    source = 'safe' if str(source).lower() == 'safe' else 'drawer'
    month_period = (month_period or get_business_date()[:7]).strip()
    drawn_by = (drawn_by or 'المدير').strip()
    notes = (notes or 'سحب أرباح المالك (نهاية الشهر)').strip()

    # فحص كفاية الكاش قبل السحب
    if source == 'drawer':
        drawer_stat = get_drawer_cash_status()
        avail_lbp = float(drawer_stat.get('total_untransferred_lbp') or 0.0)
        if amount_lbp > (avail_lbp + 1000.0):
            raise ValueError(f"المبلغ المطلوب سحبه ({amount_lbp:,.0f} ل.ل) أكبر من الكاش الفعلي المتوفر بالدرج ({avail_lbp:,.0f} ل.ل).")
    else:
        safe_stat = get_safe_balance()
        avail_lbp = float(safe_stat.get('total_lbp') or 0.0)
        if amount_lbp > (avail_lbp + 1000.0):
            raise ValueError(f"المبلغ المطلوب سحبه ({amount_lbp:,.0f} ل.ل) أكبر من رصيد الخزنة الخاصة الحالي ({avail_lbp:,.0f} ل.ل).")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO owner_drawings (amount_lbp, amount_usd, source, drawing_type, month_period, drawn_by, notes, exchange_rate, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
    """, (amount_lbp, amount_usd, source, drawing_type, month_period, drawn_by, notes, rate))
    drawing_id = cursor.lastrowid
    conn.commit()
    conn.close()

    acc_credit = '1010' if source == 'drawer' else '1020'
    src_label = 'درج الكاشير' if source == 'drawer' else 'الخزنة الخاصة'

    # تسجيل القيد المزدوج في دفتر اليومية
    try:
        record_double_entry_journal(
            description=f"مسحوبات أرباح المالك ({month_period}): {notes} - خصماً من {src_label}",
            lines=[
                {'account_code': '3030', 'debit_lbp': amount_lbp, 'credit_lbp': 0.0, 'debit_usd': amount_usd, 'credit_usd': 0.0, 'memo': f'سحب أرباح {month_period}'},
                {'account_code': acc_credit, 'debit_lbp': 0.0, 'credit_lbp': amount_lbp, 'debit_usd': 0.0, 'credit_usd': amount_usd, 'memo': f'صادر من {src_label}'}
            ],
            reference_type='owner_drawings',
            reference_id=drawing_id,
            user_name=drawn_by
        )
    except Exception as e:
        logger.warning(f"Error recording double entry for owner drawing: {e}")

    # تسجيل في سجل الحركة المالية المركزي
    try:
        record_financial_ledger_entry(
            entry_type='owner_withdrawal',
            source=source,
            destination='owner',
            amount_lbp=amount_lbp,
            amount_usd=amount_usd,
            reference_table='owner_drawings',
            reference_id=drawing_id,
            user_name=drawn_by,
            notes=f"مسحوبات أرباح المالك ({month_period}): {notes}",
            exchange_rate=rate,
            business_date=get_business_date()
        )
    except Exception as e:
        logger.warning(f"Error recording financial ledger for owner drawing: {e}")

    # جلب الوضع الجديد الفوري بعد الخصم
    updated_drawer = get_drawer_cash_status()
    updated_safe = get_safe_balance()

    return {
        'success': True,
        'drawing_id': drawing_id,
        'amount_lbp': amount_lbp,
        'amount_usd': amount_usd,
        'source': source,
        'month_period': month_period,
        'drawer_remaining_lbp': updated_drawer.get('total_untransferred_lbp', 0.0),
        'safe_balance_lbp': updated_safe.get('total_lbp', 0.0),
        'message': f"تم خصم سحب الأرباح بقيمة {amount_lbp:,.0f} ل.ل بنجاح من {src_label}"
    }


def get_owner_drawings(start_date=None, end_date=None, month_period=None, source=None):
    """جلب سجل مسحوبات أرباح المالك مع الفلاتر الزمنية."""
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM owner_drawings WHERE (status != 'cancelled' OR status IS NULL)"
    params = []
    if month_period:
        query += " AND month_period = ?"
        params.append(month_period)
    if start_date and end_date:
        query += " AND DATE(datetime(created_at, '-5 hours')) >= DATE(?) AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)"
        params.extend([start_date, end_date])
    elif start_date:
        query += " AND DATE(datetime(created_at, '-5 hours')) = DATE(?)"
        params.append(start_date)
    if source:
        query += " AND source = ?"
        params.append(source)
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def cancel_owner_drawing(drawing_id: int, cancelled_by: str = 'المدير', reason: str = 'إلغاء مسحوبات المالك بواسطة الإدارة') -> bool:
    """إلغاء عملية سحب أرباح المالك وعكس القيد المحاسبي لإعادة الرصيد إلى الدرج أو الخزنة."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM owner_drawings WHERE id = ?", (drawing_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError("سجل مسحوبات المالك غير موجود.")
    drawing = dict(row)
    if drawing.get('status') == 'cancelled':
        conn.close()
        return True

    now_str = get_local_now()
    cursor.execute("""
        UPDATE owner_drawings 
        SET status = 'cancelled', cancelled_by = ?, cancelled_at = ?, cancel_reason = ?
        WHERE id = ?
    """, (cancelled_by, now_str, reason, drawing_id))
    conn.commit()
    conn.close()

    source = drawing.get('source') or 'drawer'
    amount_lbp = float(drawing.get('amount_lbp') or 0.0)
    amount_usd = float(drawing.get('amount_usd') or 0.0)
    acc_target = '1010' if source == 'drawer' else '1020'
    src_label = 'درج الكاشير' if source == 'drawer' else 'الخزنة الخاصة'

    # عكس القيد في اليومية
    try:
        record_double_entry_journal(
            description=f"عكس وإلغاء مسحوبات المالك رقم #{drawing_id}: {reason} - إعادة إلى {src_label}",
            lines=[
                {'account_code': acc_target, 'debit_lbp': amount_lbp, 'credit_lbp': 0.0, 'debit_usd': amount_usd, 'credit_usd': 0.0, 'memo': f'إلغاء مسحوبات وإعادة إلى {src_label}'},
                {'account_code': '3030', 'debit_lbp': 0.0, 'credit_lbp': amount_lbp, 'debit_usd': 0.0, 'credit_usd': amount_usd, 'memo': f'عكس مسحوبات أرباح المالك #{drawing_id}'}
            ],
            reference_type='cancel_owner_drawing',
            reference_id=drawing_id,
            user_name=cancelled_by
        )
    except Exception as e:
        logger.warning(f"Error recording reversal journal for owner drawing #{drawing_id}: {e}")

    # عكس القيد في السجل المالي
    try:
        record_financial_ledger_entry(
            entry_type='owner_withdrawal_cancelled',
            source='owner',
            destination=source,
            amount_lbp=amount_lbp,
            amount_usd=amount_usd,
            reference_table='owner_drawings',
            reference_id=drawing_id,
            user_name=cancelled_by,
            notes=f"إلغاء مسحوبات أرباح المالك #{drawing_id}: {reason}",
            business_date=get_business_date()
        )
    except Exception as e:
        logger.warning(f"Error recording financial ledger for cancelled owner drawing: {e}")

    # تحديث الكاش الفعلي
    get_drawer_cash_status()
    get_safe_balance()
    return True


# =========================================================================
# SPECIAL SAFE DAILY TRANSFER & COMPREHENSIVE REPORTS ENGINE
# =========================================================================

def check_daily_safe_transfer_status(target_date=None):
    """
    يفحص ما إذا كان كاش اليوم أو تاريخ محدد قد تم ترحيله إلى الخزنة الخاصة بالفعل أم لا،
    ويحسب صافي الكاش المتاح للترحيل (المبيعات النقدية - المصاريف النقدية - مسحوبات المالك من الدرج).
    """
    target_date = target_date or get_business_date()
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    conn = get_db()
    cursor = conn.cursor()

    # 1. فحص هل يوجد ترحيل سابق مسجل لهذا التاريخ في الخزنة
    cursor.execute("""
        SELECT * FROM safe_transfers
        WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?) OR note LIKE ?)
          AND operation_type = 'deposit'
          AND (status != 'cancelled' OR status IS NULL)
        ORDER BY id DESC
    """, (target_date, target_date, f"%{target_date}%"))
    existing_transfers = [dict(r) for r in cursor.fetchall()]

    # 2. احتساب إجمالي مبيعات اليوم النقدية فقط (الكاش الفعلي الداخل للدرج: كافيه + ألعاب)
    cursor.execute("""
        SELECT 
            COALESCE(SUM(total_lbp), 0) as cash_sales_lbp,
            COALESCE(SUM(total_usd), 0) as cash_sales_usd,
            COUNT(id) as orders_count
        FROM cafe_orders
        WHERE payment_method = 'cash'
          AND (status != 'cancelled' AND (status != 'open' OR is_tab = 0))
          AND (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
    """, (target_date, target_date))
    sales_row = dict(cursor.fetchone() or {})
    total_sales_lbp = float(sales_row.get('cash_sales_lbp') or 0.0)
    total_sales_usd = float(sales_row.get('cash_sales_usd') or 0.0)
    orders_count = int(sales_row.get('orders_count') or 0)

    # 2b. سدادات الديون المستلمة اليوم (تضاف للكاش الفعلي في الدرج)
    cursor.execute("""
        SELECT COALESCE(SUM(amount_lbp), 0) as debt_rep_lbp
        FROM debt_payments
        WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
    """, (target_date, target_date))
    debt_rep_row = dict(cursor.fetchone() or {})
    today_debt_collected_lbp = float(debt_rep_row.get('debt_rep_lbp') or 0.0)
    total_sales_lbp += today_debt_collected_lbp
    total_sales_usd = round(total_sales_lbp / rate, 2) if rate > 0 else 0.0

    # 3. احتساب مصاريف اليوم المدفوعة من الدرج (لا نحتسب مصاريف الخزنة هنا لأنها خرجت من الخزنة مسبقاً)
    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN source != 'safe' OR source IS NULL THEN amount_lbp ELSE 0 END), 0) as expenses_lbp,
            COALESCE(SUM(CASE WHEN source != 'safe' OR source IS NULL THEN amount_usd ELSE 0 END), 0) as expenses_usd,
            COUNT(id) as expenses_count
        FROM expenses
        WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
          AND (status != 'cancelled' OR status IS NULL)
    """, (target_date, target_date))
    exp_row = dict(cursor.fetchone() or {})
    total_expenses_lbp = float(exp_row.get('expenses_lbp') or 0.0)
    total_expenses_usd = float(exp_row.get('expenses_usd') or 0.0)

    # 3b. مسحوبات أرباح المالك من الدرج لهذا اليوم (تخصم من الكاش المتاح للترحيل)
    cursor.execute("""
        SELECT COALESCE(SUM(amount_lbp), 0)
        FROM owner_drawings
        WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
          AND (source = 'drawer' OR source IS NULL)
          AND (status != 'cancelled' OR status IS NULL)
    """, (target_date, target_date))
    owner_draw_day_lbp = float(cursor.fetchone()[0] or 0.0)

    # 4. مجموع ما تم ترحيله بالفعل لهذا التاريخ من الدرج إلى الخزنة
    already_transferred_lbp = sum(float(t.get('amount_lbp') or 0.0) for t in existing_transfers if t.get('source') != 'external')
    already_transferred_usd = sum(float(t.get('amount_usd') or 0.0) for t in existing_transfers if t.get('source') != 'external')

    conn.close()

    # صافي الكاش المتبقي للترحيل
    net_day_cash_lbp = max(0.0, total_sales_lbp - total_expenses_lbp - owner_draw_day_lbp)
    net_day_cash_usd = round(net_day_cash_lbp / rate, 2) if rate > 0 else 0.0

    rem_to_transfer_lbp = max(0.0, net_day_cash_lbp - already_transferred_lbp)
    rem_to_transfer_usd = round(rem_to_transfer_lbp / rate, 2) if rate > 0 else 0.0

    is_fully_transferred = (already_transferred_lbp >= net_day_cash_lbp and net_day_cash_lbp > 0) or (len(existing_transfers) > 0 and rem_to_transfer_lbp <= 0)

    # المتبقي الفعلي في كاش الدرج لهذا اليوم بعد خصم ما تم ترحيله للخزنة
    drawer_remaining_lbp = rem_to_transfer_lbp

    return {
        'target_date': target_date,
        'already_transferred': len(existing_transfers) > 0,
        'is_fully_transferred': is_fully_transferred,
        'existing_transfers': existing_transfers,
        'already_transferred_lbp': already_transferred_lbp,
        'already_transferred_usd': already_transferred_usd,
        'total_sales_lbp': total_sales_lbp,
        'total_sales_usd': total_sales_usd,
        'orders_count': orders_count,
        'total_expenses_lbp': total_expenses_lbp,
        'total_expenses_usd': total_expenses_usd,
        'net_day_cash_lbp': net_day_cash_lbp,
        'net_day_cash_usd': net_day_cash_usd,
        'drawer_remaining_lbp': drawer_remaining_lbp,
        'drawer_remaining_usd': rem_to_transfer_usd,
        'recommended_transfer_lbp': rem_to_transfer_lbp,
        'recommended_transfer_usd': rem_to_transfer_usd,
        'rate': rate
    }

def transfer_daily_net_to_safe(target_date=None, transferred_by='المدير', custom_amount_lbp=None, custom_amount_usd=None, note=None):
    """
    ترحيل صافي مبيعات يوم محدد ونقلها مباشرة للخزنة الخاصة.
    يدعم تمرير مبالغ مخصصة أو استخدام صافي اليوم أو كاش الدرج المتوفر.
    """
    target_date = target_date or get_business_date()
    status = check_daily_safe_transfer_status(target_date=target_date)
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    # حماية من الترحيل المكرر إذا كان كاش اليوم قد تم ترحيله بالكامل ولم يُطلب مبلغ مخصص
    has_custom = (custom_amount_lbp is not None and float(custom_amount_lbp) > 0) or (custom_amount_usd is not None and float(custom_amount_usd) > 0)
    if status['is_fully_transferred'] and not has_custom:
        raise ValueError(f"تم ترحيل كامل كاش يوم {target_date} مسبقاً إلى الخزنة الخاصة (رصيد الكاش المتبقي لهذا اليوم: 0 ل.ل).")

    # 1. تحديد المبلغ بالليرة
    amount_lbp = 0.0
    if custom_amount_lbp is not None and float(custom_amount_lbp) > 0:
        amount_lbp = float(custom_amount_lbp)
    elif status['recommended_transfer_lbp'] > 0:
        amount_lbp = float(status['recommended_transfer_lbp'])
    else:
        # فحص هل يوجد كاش غير مرحّل في الدرج عموماً
        drawer = get_drawer_cash_status()
        if drawer.get('total_untransferred_lbp', 0.0) > 0:
            amount_lbp = float(drawer['total_untransferred_lbp'])

    # 2. معالجة المبلغ بالدولار
    if custom_amount_usd is not None and float(custom_amount_usd) > 0:
        amount_usd = float(custom_amount_usd)
        if amount_lbp <= 0:
            amount_lbp = round(amount_usd * rate, 0)
    else:
        amount_usd = round(amount_lbp / rate, 2) if rate > 0 else 0.0

    if amount_lbp <= 0 and amount_usd <= 0:
        raise ValueError("لا يوجد رصيد نقدي متاح للترحيل (المبلغ 0 ل.ل). يرجى إدخال المبلغ المراد نقله يدوياً.")

    transfer_note = note.strip() if note and note.strip() else f"ترحيل صافي مبيعات يوم {target_date}"

    transfer_id = add_safe_transfer(
        amount_lbp=amount_lbp,
        note=transfer_note,
        transferred_by=transferred_by,
        rate=rate,
        amount_usd=amount_usd,
        operation_type='deposit'
    )

    return {
        'success': True,
        'transfer_id': transfer_id,
        'target_date': target_date,
        'amount_lbp': amount_lbp,
        'amount_usd': amount_usd,
        'note': transfer_note
    }

def transfer_drawer_total_to_safe(transferred_by='المدير', note=None):
    """
    ترحيل كامل الرصيد النقدي المتراكم في درج الكاشير إلى الخزنة الخاصة (صندوق المالك).
    """
    drawer = get_drawer_cash_status()
    total_lbp = float(drawer.get('total_untransferred_lbp') or 0.0)
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    total_usd = float(drawer.get('total_untransferred_usd') or 0.0)
    if total_usd <= 0 and total_lbp > 0:
        total_usd = round(total_lbp / rate, 2) if rate > 0 else 0.0

    if total_lbp <= 0 and total_usd <= 0:
        raise ValueError("درج الكاشير فارغ حالياً ولا توجد مبالغ نقدية غير مرحّلة.")

    actual_note = note.strip() if note and note.strip() else "ترحيل كامل كاش الدرج المتراكم إلى الخزنة الخاصة"

    transfer_id = add_safe_transfer(
        amount_lbp=total_lbp,
        amount_usd=total_usd,
        note=actual_note,
        transferred_by=transferred_by,
        rate=rate,
        operation_type='deposit'
    )

    return {
        'success': True,
        'transfer_id': transfer_id,
        'amount_lbp': total_lbp,
        'amount_usd': total_usd,
        'note': actual_note
    }

def transfer_and_zero_all_to_safe(transferred_by='المدير', note=None):
    """
    ترحيل وتصفير شامل لجميع الأموال ونقلها 100% إلى الخزنة الخاصة:
    - ينقل كامل كاش الدرج المتراكم (المبيعات، الألعاب، سدادات الديون، وفكة البداية).
    - يصفّر كافة الأرصدة المعلقة خارج الخزنة لتصبح 0.0 ل.ل فوراً.
    - يسجل قيداً محاسبياً مزدوجاً وسجل حركة مركزية لحماية التدقيق.
    - يوثق إقفال وردية/تسوية الصندوق (shift_closings) بتطابق كامل.
    """
    drawer = get_drawer_cash_status()
    total_lbp = float(drawer.get('total_untransferred_lbp') or 0.0)
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    total_usd = float(drawer.get('total_untransferred_usd') or 0.0)
    if total_usd <= 0 and total_lbp > 0:
        total_usd = round(total_lbp / rate, 2) if rate > 0 else 0.0

    actual_note = note.strip() if note and note.strip() else "ترحيل وتصفير شامل لجميع الأموال ونقلها إلى الخزنة الخاصة"

    if total_lbp <= 0:
        new_safe = get_safe_balance()
        return {
            'success': False,
            'amount_lbp': 0.0,
            'amount_usd': 0.0,
            'safe_balance_lbp': new_safe.get('total_lbp', 0.0),
            'safe_balance_usd': new_safe.get('total_usd', 0.0),
            'drawer_remaining_lbp': 0.0,
            'drawer_remaining_usd': 0.0,
            'untransferred_cafe_lbp': 0.0,
            'untransferred_pc_lbp': 0.0,
            'message': 'لا توجد أموال أو كاش معلق في الصندوق للترحيل حالياً (الرصيد مصفّر بالفعل 0 ل.ل).'
        }

    transfer_id = add_safe_transfer(
        amount_lbp=total_lbp,
        amount_usd=total_usd,
        note=actual_note,
        transferred_by=transferred_by,
        rate=rate,
        operation_type='deposit',
        source='drawer',
        target='safe'
    )

    # توثيق مطابقة وتسوية الوردية/الصندوق لتكون مصفّرة تماماً
    today_bdate = get_business_date()
    try:
        record_shift_closing(
            business_date=today_bdate,
            employee_id=1,
            employee_name=transferred_by,
            cash_sales_lbp=drawer.get('all_cash_sales_lbp', 0.0),
            debt_collected_lbp=drawer.get('all_debt_rep_lbp', 0.0),
            expenses_lbp=drawer.get('all_expenses_lbp', 0.0),
            safe_transfers_lbp=total_lbp,
            expected_cash_lbp=0.0,
            actual_cash_lbp=0.0,
            difference_lbp=0.0,
            difference_note="تصفير وترحيل شامل لجميع الأموال إلى الخزنة الخاصة"
        )
    except Exception as e:
        logger.warning(f"Shift closing auto-record notice: {e}")

    new_safe = get_safe_balance()
    new_drawer = get_drawer_cash_status()

    return {
        'success': True,
        'transfer_id': transfer_id,
        'amount_lbp': total_lbp,
        'amount_usd': total_usd,
        'safe_balance_lbp': new_safe.get('total_lbp', 0.0),
        'safe_balance_usd': new_safe.get('total_usd', 0.0),
        'drawer_remaining_lbp': 0.0,
        'drawer_remaining_usd': 0.0,
        'untransferred_cafe_lbp': 0.0,
        'untransferred_pc_lbp': 0.0,
        'message': f"✓ تم ترحيل وتصفير جميع الأموال بنجاح! المبلغ المنقول: {total_lbp:,.0f} ل.ل (${total_usd:,.2f})، وجميع عدادات الكاش أصبحت 0 بالتمام."
    }

def get_hourly_sales_distribution(target_date=None):
    """جلب توزيع المبيعات على ساعات اليوم لمعرفة ساعات الذروة."""
    target_date = target_date or get_business_date()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            strftime('%H', created_at) as hour,
            COUNT(id) as orders_count,
            COALESCE(SUM(total_lbp), 0) as total_lbp,
            COALESCE(SUM(total_usd), 0) as total_usd
        FROM cafe_orders
        WHERE (status = 'paid' OR status IS NULL OR status = '')
          AND (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
        GROUP BY hour
        ORDER BY hour ASC
    """, (target_date, target_date))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_category_sales_distribution(target_date=None):
    """جلب نسبة مبيعات كل قسم وتصنيف (مشروبات ساخنة، باردة، مأكولات، ألعاب...)."""
    target_date = target_date or get_business_date()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            COALESCE(c.name, 'أخرى / بدون قسم') as category_name,
            COALESCE(c.icon, '📦') as category_icon,
            COUNT(DISTINCT o.id) as orders_count,
            SUM(i.quantity) as total_qty,
            COALESCE(SUM(i.subtotal_lbp), 0) as total_lbp,
            COALESCE(SUM(i.subtotal_usd), 0) as total_usd
        FROM cafe_order_items i
        JOIN cafe_orders o ON i.order_id = o.id
        LEFT JOIN cafe_items ci ON i.item_id = ci.id
        LEFT JOIN cafe_categories c ON ci.category_id = c.id
        WHERE (o.status = 'paid' OR o.status IS NULL OR o.status = '')
          AND (DATE(datetime(o.created_at, '-5 hours')) = DATE(?) OR DATE(o.created_at) = DATE(?))
        GROUP BY category_name
        ORDER BY total_lbp DESC
    """, (target_date, target_date))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    grand_total_lbp = sum(float(r['total_lbp'] or 0) for r in rows)
    for r in rows:
        r['pct'] = round((float(r['total_lbp'] or 0) / grand_total_lbp * 100), 1) if grand_total_lbp > 0 else 0.0

    return rows


# =========================================================================
# 🏢 ERP MODULE: SUPPLIERS & PURCHASES (إدارة الموردين وفواتير الشراء)
# =========================================================================

def get_suppliers(search_query=None):
    """جلب قائمة الموردين مع أرصدتهم الحالية."""
    conn = get_db()
    cursor = conn.cursor()
    if search_query:
        q = f"%{search_query.strip()}%"
        cursor.execute("SELECT * FROM suppliers WHERE name LIKE ? OR phone LIKE ? ORDER BY name ASC", (q, q))
    else:
        cursor.execute("SELECT * FROM suppliers ORDER BY name ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def add_supplier(name, phone='', company='', balance_usd=0.0, balance_lbp=0.0, notes=''):
    """إضافة مورد جديد أو تحديث بياناته."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM suppliers WHERE name = ?", (name.strip(),))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("""
            UPDATE suppliers 
            SET phone = CASE WHEN ? != '' THEN ? ELSE phone END,
                company = CASE WHEN ? != '' THEN ? ELSE company END,
                notes = CASE WHEN ? != '' THEN ? ELSE notes END,
                is_active = 1
            WHERE id = ?
        """, (phone.strip(), phone.strip(), company.strip(), company.strip(), notes.strip(), notes.strip(), existing['id']))
        sid = existing['id']
    else:
        cursor.execute("""
            INSERT INTO suppliers (name, phone, company, balance_usd, balance_lbp, notes, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (name.strip(), phone.strip(), company.strip(), float(balance_usd or 0), float(balance_lbp or 0), notes.strip()))
        sid = cursor.lastrowid
    conn.commit()
    conn.close()
    return sid

def get_supplier(supplier_id):
    """جلب بيانات مورد محدد بواسطة المعرف."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def record_purchase_invoice(supplier_id, items, paid_usd=0.0, paid_lbp=0.0, payment_source='safe', notes='', created_by='المدير'):
    """
    تسجيل فاتورة شراء بضاعة / مواد خام:
    - تحديث كميات وتكلفة المخزون
    - تسجيل حركة خروج كاش في الـ Financial Ledger
    - تحديث رصيد المورد
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. جلب اسم المورد
    cursor.execute("SELECT name FROM suppliers WHERE id = ?", (supplier_id,))
    s_row = cursor.fetchone()
    supplier_name = s_row['name'] if s_row else 'مورد عام'

    inv_num = f"PUR-{int(time.time())}"
    total_usd = sum(float(it.get('qty') or it.get('quantity', 1)) * float(it.get('cost_unit_usd') or it.get('cost_usd', 0)) for it in items)
    total_lbp = sum(float(it.get('qty') or it.get('quantity', 1)) * float(it.get('cost_unit_lbp') or it.get('cost_lbp', 0)) for it in items)
    paid_u = float(paid_usd or 0)
    paid_l = float(paid_lbp or 0)

    now_str = get_local_now()
    cursor.execute("""
        INSERT INTO purchase_invoices (
            invoice_number, supplier_id, supplier_name, total_usd, total_lbp,
            paid_usd, paid_lbp, payment_source, status, notes, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)
    """, (inv_num, supplier_id, supplier_name, total_usd, total_lbp, paid_u, paid_l, payment_source, notes, created_by, now_str))
    invoice_id = cursor.lastrowid

    # 2. إضافة العناصر وتحديث المخزون
    for it in items:
        inv_id = it.get('inventory_id')
        cafe_item_id = it.get('item_id') or it.get('cafe_item_id')
        name = it.get('item_name') or it.get('name', '')
        qty = float(it.get('qty') or it.get('quantity', 1))
        cost_u = float(it.get('cost_unit_usd') or it.get('cost_usd', 0))
        cost_l = float(it.get('cost_unit_lbp') or it.get('cost_lbp', 0))
        t_u = qty * cost_u
        t_l = qty * cost_l

        cursor.execute("""
            INSERT INTO purchase_invoice_items (
                invoice_id, inventory_id, item_name, qty, unit, cost_unit_usd, cost_unit_lbp, total_usd, total_lbp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (invoice_id, inv_id or cafe_item_id, name, qty, it.get('unit', 'قطعة'), cost_u, cost_l, t_u, t_l))

        # Update raw inventory if inv_id is set
        if inv_id:
            cursor.execute("""
                UPDATE inventory 
                SET stock_qty = stock_qty + ?, 
                    cost_per_unit = CASE WHEN ? > 0 THEN ? ELSE cost_per_unit END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (qty, cost_l, cost_l, inv_id))

            try:
                cursor.execute("SELECT stock_qty FROM inventory WHERE id = ?", (inv_id,))
                cur_st = cursor.fetchone()
                after_qty = float(cur_st['stock_qty']) if cur_st else qty
                before_qty = after_qty - qty
                cursor.execute("""
                    INSERT INTO stock_movements (
                        movement_type, item_type, item_id, item_name, quantity,
                        qty_before, qty_after, unit_cost_lbp, unit_cost_usd,
                        total_cost_lbp, total_cost_usd, reference_type, reference_id,
                        user_name, notes
                    ) VALUES ('PURCHASE_IN', 'inventory', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'purchase_invoices', ?, ?, ?)
                """, (inv_id, name, qty, before_qty, after_qty, cost_l, cost_u, t_l, t_u, invoice_id, created_by, f"فاتورة شراء #{inv_num}"))
            except Exception:
                pass

        # Update cafe_items finished goods stock if cafe_item_id is set
        if cafe_item_id:
            cursor.execute("""
                UPDATE cafe_items 
                SET stock_qty = stock_qty + ?, 
                    cost_price_lbp = CASE WHEN ? > 0 THEN ? ELSE cost_price_lbp END,
                    cost_price_usd = CASE WHEN ? > 0 THEN ? ELSE cost_price_usd END
                WHERE id = ?
            """, (qty, cost_l, cost_l, cost_u, cost_u, cafe_item_id))

            try:
                cursor.execute("SELECT stock_qty, name FROM cafe_items WHERE id = ?", (cafe_item_id,))
                cur_st = cursor.fetchone()
                after_qty = float(cur_st['stock_qty']) if cur_st else qty
                c_name = cur_st['name'] if cur_st else name
                before_qty = after_qty - qty
                cursor.execute("""
                    INSERT INTO stock_movements (
                        movement_type, item_type, item_id, item_name, quantity,
                        qty_before, qty_after, unit_cost_lbp, unit_cost_usd,
                        total_cost_lbp, total_cost_usd, reference_type, reference_id,
                        user_name, notes
                    ) VALUES ('PURCHASE_IN', 'cafe_item', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'purchase_invoices', ?, ?, ?)
                """, (cafe_item_id, c_name, qty, before_qty, after_qty, cost_l, cost_u, t_l, t_u, invoice_id, created_by, f"فاتورة شراء #{inv_num}"))
            except Exception:
                pass

    # 3. تحديث مديونية المورد
    rem_usd = total_usd - paid_u
    rem_lbp = total_lbp - paid_l
    cursor.execute("""
        UPDATE suppliers 
        SET balance_usd = balance_usd + ?,
            balance_lbp = balance_lbp + ?
        WHERE id = ?
    """, (rem_usd, rem_lbp, supplier_id))

    conn.commit()
    conn.close()

    # 4. تسجيل القيد المحاسبي المزدوج والسجل المالي المركزي
    try:
        # قيد إثبات المشتريات: مدين مخزون المواد (1040) / دائن ذمة المورد (2010)
        if total_lbp > 0 or total_usd > 0:
            record_double_entry_journal(
                description=f"فاتورة مشتريات مواد خام #{inv_num} - {supplier_name}",
                lines=[
                    {'account_code': '1040', 'debit_lbp': total_lbp, 'credit_lbp': 0.0, 'debit_usd': total_usd, 'credit_usd': 0.0, 'memo': f"مشتريات مخزون #{inv_num}"},
                    {'account_code': '2010', 'debit_lbp': 0.0, 'credit_lbp': total_lbp, 'debit_usd': 0.0, 'credit_usd': total_usd, 'memo': f"استحقاق للمورد {supplier_name}"}
                ],
                reference_type='purchase_invoices',
                reference_id=invoice_id,
                user_name=created_by
            )

        # قيد سداد الدفعة النقدية إن وجدت
        if paid_u > 0 or paid_l > 0:
            record_financial_ledger_entry(
                entry_type='PURCHASE_PAYMENT',
                source=payment_source,  # 'safe' أو 'drawer'
                destination='supplier',
                amount_lbp=paid_l,
                amount_usd=paid_u,
                reference_table='purchase_invoices',
                reference_id=invoice_id,
                user_name=created_by,
                notes=f"دفعة شراء بضاعة #{inv_num} - {supplier_name}"
            )

            # مدين ذمة المورد (2010) / دائن الخزنة أو الدرج (1020 أو 1010)
            credit_code = '1020' if payment_source == 'safe' else '1010'
            record_double_entry_journal(
                description=f"سداد دفعة للمورد {supplier_name} عن فاتورة #{inv_num}",
                lines=[
                    {'account_code': '2010', 'debit_lbp': paid_l, 'credit_lbp': 0.0, 'debit_usd': paid_u, 'credit_usd': 0.0, 'memo': f"دفعة للمورد {supplier_name}"},
                    {'account_code': credit_code, 'debit_lbp': 0.0, 'credit_lbp': paid_l, 'debit_usd': 0.0, 'credit_usd': paid_u, 'memo': f"صادر من {payment_source}"}
                ],
                reference_type='purchase_invoices',
                reference_id=invoice_id,
                user_name=created_by
            )
    except Exception:
        pass

    return invoice_id


def record_supplier_payment(supplier_id, amount_usd=0.0, amount_lbp=0.0, payment_source='safe', notes='', created_by='المدير'):
    """سداد دفعة نقدية لحساب مورد من الخزنة أو الصندوق."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, balance_usd, balance_lbp FROM suppliers WHERE id = ?", (supplier_id,))
    supp = cursor.fetchone()
    if not supp:
        conn.close()
        return False, "المورد غير موجود"

    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    paid_u = float(amount_usd or 0.0)
    paid_l = float(amount_lbp or 0.0)
    if paid_u == 0 and paid_l > 0 and rate > 0:
        paid_u = round(paid_l / rate, 2)
    elif paid_l == 0 and paid_u > 0 and rate > 0:
        paid_l = round(paid_u * rate)

    if paid_u <= 0 and paid_l <= 0:
        conn.close()
        return False, "يجب تحديد مبلغ أكبر من صفر"

    now_str = get_local_now()
    try:
        cursor.execute("""
            INSERT INTO supplier_payments (
                supplier_id, amount_usd, amount_lbp, payment_method, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (supplier_id, paid_u, paid_l, payment_source, notes, created_by, now_str))
    except Exception:
        pass

    # Update supplier balance
    cursor.execute("""
        UPDATE suppliers 
        SET balance_usd = balance_usd - ?, balance_lbp = balance_lbp - ?
        WHERE id = ?
    """, (paid_u, paid_l, supplier_id))

    # If paid from safe, log safe transfer out
    if payment_source == 'safe':
        try:
            cursor.execute("""
                INSERT INTO safe_transfers (amount_lbp, amount_usd, transfer_type, reason, created_by, created_at)
                VALUES (?, ?, 'out', ?, ?, ?)
            """, (paid_l, paid_u, f"دفعة للمورد {supp['name']} - {notes}".strip(), created_by, now_str))
        except Exception:
            pass

    conn.commit()
    conn.close()

    # Log in Financial Ledger and Double-Entry Journal
    try:
        record_financial_ledger_entry(
            entry_type='PURCHASE_PAYMENT',
            source=payment_source,  # 'safe' أو 'drawer'
            destination='supplier',
            amount_lbp=paid_l,
            amount_usd=paid_u,
            reference_table='supplier_payments',
            reference_id=supplier_id,
            user_name=created_by,
            notes=f"سداد دفعة للمورد {supp['name']} ({notes})",
            exchange_rate=rate,
            business_date=get_business_date()
        )
    except Exception:
        pass

    try:
        credit_code = '1020' if payment_source == 'safe' else '1010'
        record_double_entry_journal(
            description=f"سداد دفعة للمورد {supp['name']} ({notes})",
            lines=[
                {'account_code': '2010', 'debit_lbp': paid_l, 'credit_lbp': 0.0, 'debit_usd': paid_u, 'credit_usd': 0.0, 'memo': f"دفعة للمورد {supp['name']}"},
                {'account_code': credit_code, 'debit_lbp': 0.0, 'credit_lbp': paid_l, 'debit_usd': 0.0, 'credit_usd': paid_u, 'memo': f"صادر من {payment_source}"}
            ],
            reference_type='supplier_payments',
            reference_id=supplier_id,
            user_name=created_by
        )
    except Exception:
        pass

    return True, f"تم تسجيل سداد {paid_u}$ ({int(paid_l):,} ل.ل) للمورد {supp['name']} بنجاح"



# =========================================================================
# 🍽️ ERP MODULE: DINING TABLES (إدارة الطاولات والصالات)
# =========================================================================

def get_dining_tables():
    """جلب جميع طاولات الكافيه مع حالتها وحساب الطلب الحالي إن وجد."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT dt.*, o.order_number, o.total_lbp as current_order_total_lbp, o.total_usd as current_order_total_usd
        FROM dining_tables dt
        LEFT JOIN cafe_orders o ON dt.current_order_id = o.id AND (o.status = 'unpaid' OR o.status = 'open')
        ORDER BY dt.table_number ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def add_dining_table(table_number, table_name='', section='الصالة الرئيسية', seats=4):
    """إضافة طاولة جديدة للكافيه."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO dining_tables (table_number, table_name, section, seats, status)
        VALUES (?, ?, ?, ?, 'available')
    """, (table_number.strip(), table_name.strip(), section.strip(), int(seats or 4)))
    tid = cursor.lastrowid
    conn.commit()
    conn.close()
    return tid


# =========================================================================
# 📊 ERP MODULE: ADVANCED P&L FINANCIAL REPORT (الأرباح والخسائر والتدفق المالي)
# =========================================================================

def get_comprehensive_financial_statement(start_date=None, end_date=None):
    """
    بيان الدخل والأرباح والخسائر الشامل (P&L Income Statement):
    - إجمالي الإيرادات (مبيعات كافيه + ألعاب GAMING)
    - تكلفة البضاعة المباعة (COGS)
    - إجمالي الربح التشغيلي
    - المصاريف العامة والنثريات
    - صافي الربح الحقيقي المحاسبي
    - التدفق النقدي بالخزنة والدرج
    """
    bdate = get_business_date()
    s_date = start_date or bdate
    e_date = end_date or bdate
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    conn = get_db()
    cursor = conn.cursor()

    # 1. إيرادات الكافيه
    cursor.execute("""
        SELECT 
            COALESCE(SUM(total_lbp), 0) as sales_lbp,
            COALESCE(SUM(total_usd), 0) as sales_usd,
            COALESCE(SUM(total_cost_lbp), 0) as cost_lbp,
            COALESCE(SUM(total_cost_usd), 0) as cost_usd,
            COUNT(id) as orders_count
        FROM cafe_orders
        WHERE (status = 'paid' OR status IS NULL OR status = '')
          AND DATE(datetime(created_at, '-5 hours')) >= DATE(?)
          AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)
    """, (s_date, e_date))
    cafe_data = dict(cursor.fetchone() or {})

    # 2. إيرادات ألعاب GAMING و PC (100% ربح)
    cursor.execute("""
        SELECT 
            COALESCE(SUM(price_lbp), 0) as pc_lbp,
            COALESCE(SUM(price_usd), 0) as pc_usd,
            COUNT(id) as clicks_count
        FROM pc_usage_logs
        WHERE DATE(datetime(created_at, '-5 hours')) >= DATE(?)
          AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)
    """, (s_date, e_date))
    pc_data = dict(cursor.fetchone() or {})

    # 3. المصاريف التشغيلية النشطة
    cursor.execute("""
        SELECT 
            COALESCE(SUM(amount_lbp), 0) as exp_lbp,
            COALESCE(SUM(amount_usd), 0) as exp_usd,
            COUNT(id) as count
        FROM expenses
        WHERE status != 'cancelled'
          AND DATE(datetime(created_at, '-5 hours')) >= DATE(?)
          AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)
    """, (s_date, e_date))
    exp_data = dict(cursor.fetchone() or {})

    # 4. خسائر هدر وتلف القهوة (Coffee Waste Loss)
    cursor.execute("""
        SELECT 
            COALESCE(SUM(loss_cost_lbp), 0) as waste_loss_lbp,
            COALESCE(SUM(loss_cost_usd), 0) as waste_loss_usd,
            COALESCE(SUM(qty), 0) as waste_cups_count
        FROM coffee_waste_logs
        WHERE DATE(datetime(created_at, '-5 hours')) >= DATE(?)
          AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)
    """, (s_date, e_date))
    waste_data = dict(cursor.fetchone() or {})
    waste_loss_lbp = float(waste_data.get('waste_loss_lbp', 0))
    waste_loss_usd = float(waste_data.get('waste_loss_usd', 0))
    waste_cups = int(waste_data.get('waste_cups_count', 0))

    # 5. المشتريات خلال الفترة
    cursor.execute("""
        SELECT 
            COALESCE(SUM(total_lbp), 0) as pur_lbp,
            COALESCE(SUM(total_usd), 0) as pur_usd,
            COALESCE(SUM(paid_lbp), 0) as pur_paid_lbp,
            COALESCE(SUM(paid_usd), 0) as pur_paid_usd
        FROM purchase_invoices
        WHERE status != 'cancelled'
          AND DATE(datetime(created_at, '-5 hours')) >= DATE(?)
          AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)
    """, (s_date, e_date))
    pur_data = dict(cursor.fetchone() or {})

    conn.close()

    total_revenue_lbp = float(cafe_data.get('sales_lbp', 0)) + float(pc_data.get('pc_lbp', 0))
    total_cost_lbp = float(cafe_data.get('cost_lbp', 0))
    gross_profit_lbp = total_revenue_lbp - total_cost_lbp
    total_expenses_lbp = float(exp_data.get('exp_lbp', 0))
    # خصم خسائر التلف والهدر من صافي الربح الحقيقي
    net_profit_lbp = gross_profit_lbp - total_expenses_lbp - waste_loss_lbp

    total_revenue_usd = round(total_revenue_lbp / rate, 2) if rate > 0 else 0.0
    net_profit_usd = round(net_profit_lbp / rate, 2) if rate > 0 else 0.0

    return {
        'start_date': s_date,
        'end_date': e_date,
        'exchange_rate': rate,
        'cafe_sales_lbp': float(cafe_data.get('sales_lbp', 0)),
        'cafe_sales_usd': float(cafe_data.get('sales_usd', 0)),
        'pc_sales_lbp': float(pc_data.get('pc_lbp', 0)),
        'pc_sales_usd': float(pc_data.get('pc_usd', 0)),
        'total_revenue_lbp': total_revenue_lbp,
        'total_revenue_usd': total_revenue_usd,
        'cost_of_goods_lbp': total_cost_lbp,
        'gross_profit_lbp': gross_profit_lbp,
        'expenses_lbp': total_expenses_lbp,
        'expenses_usd': float(exp_data.get('exp_usd', 0)),
        'net_profit_lbp': net_profit_lbp,
        'net_profit_usd': net_profit_usd,
        'purchases_lbp': float(pur_data.get('pur_lbp', 0)),
        'purchases_usd': float(pur_data.get('pur_usd', 0)),
        'coffee_waste_loss_lbp': waste_loss_lbp,
        'coffee_waste_loss_usd': waste_loss_usd,
        'coffee_waste_cups': waste_cups,
        'orders_count': cafe_data.get('orders_count', 0),
        'pc_clicks': pc_data.get('clicks_count', 0)
    }


# =========================================================================
# 🏛️ DOUBLE-ENTRY ACCOUNTING & CHART OF ACCOUNTS (النواة المحاسبية المزدوجة)
# =========================================================================

def get_chart_of_accounts():
    """جلب شجرة الحسابات المحاسبية كاملة مع أرصدتها وحالتها وفق القواعد المحاسبية الدقيقة (Normal Balance)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.*,
            CASE 
                WHEN LOWER(a.account_type) IN ('asset', 'expense') THEN
                    COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.debit_lbp - jel.credit_lbp ELSE 0 END), 0)
                ELSE
                    COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.credit_lbp - jel.debit_lbp ELSE 0 END), 0)
            END as calculated_balance_lbp,
            CASE 
                WHEN LOWER(a.account_type) IN ('asset', 'expense') THEN
                    COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.debit_usd - jel.credit_usd ELSE 0 END), 0)
                ELSE
                    COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.credit_usd - jel.debit_usd ELSE 0 END), 0)
            END as calculated_balance_usd,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.debit_lbp ELSE 0 END), 0) as total_debit_lbp,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.credit_lbp ELSE 0 END), 0) as total_credit_lbp,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.debit_usd ELSE 0 END), 0) as total_debit_usd,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.credit_usd ELSE 0 END), 0) as total_credit_usd
        FROM accounts a
        LEFT JOIN journal_entry_lines jel ON a.code = jel.account_code
        LEFT JOIN journal_entries je ON jel.journal_entry_id = je.id
        GROUP BY a.id
        ORDER BY a.code ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def record_double_entry_journal(description: str, lines: list, reference_type: str = None,
                                reference_id: int = None, user_name: str = 'النظام',
                                entry_date: str = None, db_conn = None) -> tuple:
    """
    إنشاء قيد محاسبي مزدوج (Double-Entry Journal Entry):
    يضمن التوازن الرياضي التام: مجموع المدين (Debit) = مجموع الدائن (Credit).
    lines: قائمة قواميس تحتوي على:
    [
        {'account_code': '1010', 'debit_lbp': 100000, 'credit_lbp': 0, 'debit_usd': 1.12, 'credit_usd': 0, 'memo': 'قبض نقدي'},
        {'account_code': '4010', 'debit_lbp': 0, 'credit_lbp': 100000, 'debit_usd': 0, 'credit_usd': 1.12, 'memo': 'إيراد مبيعات'}
    ]
    """
    if not lines or len(lines) < 2:
        return False, "القيد المحاسبي المزدوج يتطلب طرفين على الأقل (مدين ودائن)"

    # التحقق من توازن القيد
    total_debit_lbp = sum(float(l.get('debit_lbp') or 0.0) for l in lines)
    total_credit_lbp = sum(float(l.get('credit_lbp') or 0.0) for l in lines)
    total_debit_usd = sum(float(l.get('debit_usd') or 0.0) for l in lines)
    total_credit_usd = sum(float(l.get('credit_usd') or 0.0) for l in lines)

    # السماح بفروقات تقريبية طفيفة جداً (أقل من 1 ليرة أو 0.01 دولار)
    if abs(total_debit_lbp - total_credit_lbp) > 1.0:
        return False, f"القيد غير متوازن بالليرة: مدين={total_debit_lbp:,.0f}، دائن={total_credit_lbp:,.0f}"

    date_str = entry_date or get_business_date()
    import time
    entry_number = f"JE-{datetime.now().strftime('%Y%m%d')}-{int(time.time() * 1000) % 100000}"

    is_external_conn = (db_conn is not None)
    conn = db_conn if is_external_conn else get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO journal_entries (
                entry_number, entry_date, description, reference_type, reference_id,
                total_amount_lbp, total_amount_usd, user_name, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'posted')
        """, (
            entry_number, date_str, description.strip(), reference_type, reference_id,
            total_debit_lbp, total_debit_usd, user_name
        ))
        journal_id = cursor.lastrowid

        for l in lines:
            code = l.get('account_code')
            cursor.execute("SELECT name_ar, name, account_type FROM accounts WHERE code = ?", (code,))
            acc_row = cursor.fetchone()
            acc_name = acc_row['name_ar'] if acc_row else (l.get('account_name') or code)
            acc_type = (acc_row['account_type'] if acc_row else 'asset').lower()

            cursor.execute("""
                INSERT INTO journal_entry_lines (
                    journal_entry_id, account_code, account_name,
                    debit_lbp, credit_lbp, debit_usd, credit_usd, memo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                journal_id, code, acc_name,
                float(l.get('debit_lbp') or 0.0), float(l.get('credit_lbp') or 0.0),
                float(l.get('debit_usd') or 0.0), float(l.get('credit_usd') or 0.0),
                (l.get('memo') or '').strip()
            ))

            # تحديث رصيد الحساب المباشر وفق الطبيعة المحاسبية (Normal Balance)
            deb_l = float(l.get('debit_lbp') or 0.0)
            cr_l = float(l.get('credit_lbp') or 0.0)
            deb_u = float(l.get('debit_usd') or 0.0)
            cr_u = float(l.get('credit_usd') or 0.0)

            if acc_type in ('asset', 'expense'):
                net_change_lbp = deb_l - cr_l
                net_change_usd = deb_u - cr_u
            else:
                net_change_lbp = cr_l - deb_l
                net_change_usd = cr_u - deb_u

            cursor.execute("""
                UPDATE accounts
                SET balance_lbp = balance_lbp + ?,
                    balance_usd = balance_usd + ?
                WHERE code = ?
            """, (net_change_lbp, net_change_usd, code))

        if not is_external_conn:
            conn.commit()
            conn.close()
        return True, entry_number
    except Exception as e:
        if not is_external_conn and conn:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
        if is_external_conn:
            raise
        return False, str(e)


def recalculate_all_account_balances():
    """
    إعادة احتساب وتزامن كافة أرصدة شجرة الحسابات (Accounts) بدقة متناهية من واقع قيود اليومية المعتمدة (Posted).
    تضمن أن الرصيد يتبع الطبيعة المحاسبية (Normal Balance):
    - الأصول والمصروفات: مدين - دائن
    - الخصوم وحقوق الملكية والإيرادات: دائن - مدين
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, code, account_type FROM accounts")
    accs = cursor.fetchall()
    for acc in accs:
        code = acc['code']
        acc_type = (acc['account_type'] or 'asset').lower()
        cursor.execute("""
            SELECT 
                COALESCE(SUM(jel.debit_lbp), 0) as deb_lbp,
                COALESCE(SUM(jel.credit_lbp), 0) as cr_lbp,
                COALESCE(SUM(jel.debit_usd), 0) as deb_usd,
                COALESCE(SUM(jel.credit_usd), 0) as cr_usd
            FROM journal_entry_lines jel
            JOIN journal_entries je ON jel.journal_entry_id = je.id
            WHERE jel.account_code = ? AND je.status = 'posted'
        """, (code,))
        totals = cursor.fetchone()
        deb_l = float(totals['deb_lbp'] or 0.0)
        cr_l = float(totals['cr_lbp'] or 0.0)
        deb_u = float(totals['deb_usd'] or 0.0)
        cr_u = float(totals['cr_usd'] or 0.0)

        if acc_type in ('asset', 'expense'):
            bal_lbp = deb_l - cr_l
            bal_usd = deb_u - cr_u
        else:
            bal_lbp = cr_l - deb_l
            bal_usd = cr_u - deb_u

        cursor.execute("""
            UPDATE accounts 
            SET balance_lbp = ?, balance_usd = ?
            WHERE code = ?
        """, (bal_lbp, bal_usd, code))
    conn.commit()
    conn.close()
    return True


def get_journal_entries(limit=100, start_date=None, end_date=None):
    """جلب القيود المحاسبية المزدوجة مع بنود القيد (Lines) وتفاصيل المدين والدائن."""
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM journal_entries WHERE 1=1"
    params = []
    if start_date:
        query += " AND DATE(entry_date) >= DATE(?)"
        params.append(start_date)
    if end_date:
        query += " AND DATE(entry_date) <= DATE(?)"
        params.append(end_date)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(query, params)
    entries = [dict(r) for r in cursor.fetchall()]

    for e in entries:
        cursor.execute("SELECT * FROM journal_entry_lines WHERE journal_entry_id = ? ORDER BY id ASC", (e['id'],))
        e['lines'] = [dict(l) for l in cursor.fetchall()]

    conn.close()
    return entries


def record_shift_opening_float(employee_id: int, employee_name: str, amount_lbp: float,
                               amount_usd: float = 0.0, source: str = 'safe', notes: str = '') -> tuple:
    """
    تسجيل العهدة الافتتاحية للصندوق (فكة بداية الدوام) بقيد محاسبي مزدوج وسجل مالي رسمي:
    - مدين: صندوق الكاشير (1010)
    - دائن: الخزنة الخاصة (1020) إذا وردت من الخزنة، أو رأس المال التأسيسي (3010)
    """
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    amount_lbp = float(amount_lbp or 0.0)
    if amount_lbp <= 0 and amount_usd > 0:
        amount_lbp = round(amount_usd * rate, 0)
    elif amount_usd <= 0 and amount_lbp > 0:
        amount_usd = round(amount_lbp / rate, 2) if rate > 0 else 0.0

    if amount_lbp <= 0:
        return False, "مبلغ العهدة يجب أن يكون أكبر من صفر"

    credit_acc = '1020' if source == 'safe' else '3010'
    credit_name = 'الخزنة الخاصة' if source == 'safe' else 'رأس المال / العهدة'
    memo = f"عهدة افتتاحية لصندوق الكاشير ({employee_name}) من {credit_name}"
    if notes:
        memo += f" - {notes}"

    ok, res = record_double_entry_journal(
        description=memo,
        lines=[
            {'account_code': '1010', 'debit_lbp': amount_lbp, 'credit_lbp': 0.0, 'debit_usd': amount_usd, 'credit_usd': 0.0, 'memo': 'وارد لصندوق الكاشير'},
            {'account_code': credit_acc, 'debit_lbp': 0.0, 'credit_lbp': amount_lbp, 'debit_usd': 0.0, 'credit_usd': amount_usd, 'memo': f'صادر من {credit_name}'}
        ],
        reference_type='opening_float',
        reference_id=employee_id,
        user_name=employee_name
    )
    if ok:
        try:
            record_financial_ledger_entry(
                entry_type='shift_opening_float',
                source=source,
                destination='drawer',
                amount_lbp=amount_lbp,
                amount_usd=amount_usd,
                reference_table='accounts',
                reference_id=1010,
                user_id=employee_id,
                user_name=employee_name,
                notes=memo,
                exchange_rate=rate,
                business_date=get_business_date()
            )
        except Exception:
            pass
    return ok, res


# =========================================================================
# 📊 FINANCIAL STATEMENTS ENGINE (القوائم المالية الختامية وإقفال السنة)
# =========================================================================

def get_trial_balance(as_of_date: str = None) -> dict:
    """
    توليد ميزان المراجعة المحاسبي (Trial Balance):
    يتحقق من التساوي الرياضي الصارم: مجموع الأرصدة المدينة = مجموع الأرصدة الدائنة (100%).
    """
    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT a.code, a.name_ar, a.name, a.account_type,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.debit_lbp ELSE 0 END), 0) as total_debit_lbp,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.credit_lbp ELSE 0 END), 0) as total_credit_lbp,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.debit_usd ELSE 0 END), 0) as total_debit_usd,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.credit_usd ELSE 0 END), 0) as total_credit_usd
        FROM accounts a
        LEFT JOIN journal_entry_lines jel ON a.code = jel.account_code
        LEFT JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE 1=1
    """
    params = []
    if as_of_date:
        query += " AND (je.entry_date IS NULL OR DATE(je.entry_date) <= DATE(?))"
        params.append(as_of_date)
    query += " GROUP BY a.id ORDER BY a.code ASC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    total_debit_lbp = 0.0
    total_credit_lbp = 0.0
    total_debit_usd = 0.0
    total_credit_usd = 0.0

    for r in rows:
        deb_l = float(r['total_debit_lbp'] or 0.0)
        cr_l = float(r['total_credit_lbp'] or 0.0)
        deb_u = float(r['total_debit_usd'] or 0.0)
        cr_u = float(r['total_credit_usd'] or 0.0)

        # حساب الرصيد الصافي المدين أو الدائن
        net_lbp = deb_l - cr_l
        net_usd = deb_u - cr_u
        if net_lbp > 0:
            r['balance_debit_lbp'] = net_lbp
            r['balance_credit_lbp'] = 0.0
        else:
            r['balance_debit_lbp'] = 0.0
            r['balance_credit_lbp'] = abs(net_lbp)

        if net_usd > 0:
            r['balance_debit_usd'] = net_usd
            r['balance_credit_usd'] = 0.0
        else:
            r['balance_debit_usd'] = 0.0
            r['balance_credit_usd'] = abs(net_usd)

        total_debit_lbp += deb_l
        total_credit_lbp += cr_l
        total_debit_usd += deb_u
        total_credit_usd += cr_u

    diff_lbp = round(total_debit_lbp - total_credit_lbp, 2)
    diff_usd = round(total_debit_usd - total_credit_usd, 2)

    return {
        'accounts': rows,
        'total_debit_lbp': total_debit_lbp,
        'total_credit_lbp': total_credit_lbp,
        'total_debit_usd': total_debit_usd,
        'total_credit_usd': total_credit_usd,
        'is_balanced': abs(diff_lbp) <= 1.0,
        'difference_lbp': diff_lbp,
        'difference_usd': diff_usd,
        'as_of_date': as_of_date or get_business_date()
    }


def get_income_statement(start_date: str = None, end_date: str = None) -> dict:
    """
    قائمة الدخل والأرباح والخسائر (Income Statement / Profit & Loss):
    - الإيرادات التشغيلية (مبيعات كافيه، ألعاب، إيرادات أخرى، فائض الصندوق)
    - الخصومات والضيافة
    - تكلفة البضاعة المباعة (COGS)
    - مجمل الربح (Gross Profit)
    - المصروفات التشغيلية والرواتب والتالف وعجز الصندوق
    - صافي الربح للفترة (Net Operating Profit)
    """
    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT a.code, a.name_ar, a.name, a.account_type,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.debit_lbp ELSE 0 END), 0) as total_debit_lbp,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.credit_lbp ELSE 0 END), 0) as total_credit_lbp,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.debit_usd ELSE 0 END), 0) as total_debit_usd,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.credit_usd ELSE 0 END), 0) as total_credit_usd
        FROM accounts a
        LEFT JOIN journal_entry_lines jel ON a.code = jel.account_code
        LEFT JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE a.account_type IN ('revenue', 'expense')
    """
    params = []
    if start_date:
        query += " AND (je.entry_date IS NULL OR DATE(je.entry_date) >= DATE(?))"
        params.append(start_date)
    if end_date:
        query += " AND (je.entry_date IS NULL OR DATE(je.entry_date) <= DATE(?))"
        params.append(end_date)
    query += " GROUP BY a.id ORDER BY a.code ASC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    revenues = []
    expenses = []
    total_revenue_lbp = 0.0
    total_revenue_usd = 0.0
    total_expense_lbp = 0.0
    total_expense_usd = 0.0
    discounts_lbp = 0.0
    discounts_usd = 0.0
    cogs_lbp = 0.0
    cogs_usd = 0.0

    for r in rows:
        deb_l = float(r['total_debit_lbp'] or 0.0)
        cr_l = float(r['total_credit_lbp'] or 0.0)
        deb_u = float(r['total_debit_usd'] or 0.0)
        cr_u = float(r['total_credit_usd'] or 0.0)
        acc_type = r['account_type']
        code = r['code']

        if acc_type == 'revenue':
            net_l = cr_l - deb_l
            net_u = cr_u - deb_u
            r['net_amount_lbp'] = net_l
            r['net_amount_usd'] = net_u
            revenues.append(r)
            total_revenue_lbp += net_l
            total_revenue_usd += net_u
        elif acc_type == 'expense':
            net_l = deb_l - cr_l
            net_u = deb_u - cr_u
            r['net_amount_lbp'] = net_l
            r['net_amount_usd'] = net_u
            if code == '4100':  # خصومات المبيعات (حساب مقابل للإيراد)
                discounts_lbp += net_l
                discounts_usd += net_u
            elif code == '5010':  # تكلفة البضاعة المباعة
                cogs_lbp += net_l
                cogs_usd += net_u
            else:
                expenses.append(r)
                total_expense_lbp += net_l
                total_expense_usd += net_u

    net_revenue_lbp = total_revenue_lbp - discounts_lbp
    net_revenue_usd = total_revenue_usd - discounts_usd
    gross_profit_lbp = net_revenue_lbp - cogs_lbp
    gross_profit_usd = net_revenue_usd - cogs_usd
    net_profit_lbp = gross_profit_lbp - total_expense_lbp
    net_profit_usd = gross_profit_usd - total_expense_usd

    return {
        'revenues': revenues,
        'total_revenue_lbp': total_revenue_lbp,
        'total_revenue_usd': total_revenue_usd,
        'discounts_lbp': discounts_lbp,
        'discounts_usd': discounts_usd,
        'net_revenue_lbp': net_revenue_lbp,
        'net_revenue_usd': net_revenue_usd,
        'cogs_lbp': cogs_lbp,
        'cogs_usd': cogs_usd,
        'gross_profit_lbp': gross_profit_lbp,
        'gross_profit_usd': gross_profit_usd,
        'operating_expenses': expenses,
        'total_expense_lbp': total_expense_lbp,
        'total_expense_usd': total_expense_usd,
        'net_profit_lbp': net_profit_lbp,
        'net_profit_usd': net_profit_usd,
        'start_date': start_date,
        'end_date': end_date
    }


def get_balance_sheet(as_of_date: str = None) -> dict:
    """
    الميزانية العمومية والمركز المالي (Balance Sheet):
    تتحقق من المعادلة المحاسبية الذهبية:
    الأصول (Assets) = الخصوم (Liabilities) + حقوق الملكية (Equity) + صافي ربح الفترة الحالية.
    """
    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT a.code, a.name_ar, a.name, a.account_type,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.debit_lbp ELSE 0 END), 0) as total_debit_lbp,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.credit_lbp ELSE 0 END), 0) as total_credit_lbp,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.debit_usd ELSE 0 END), 0) as total_debit_usd,
            COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jel.credit_usd ELSE 0 END), 0) as total_credit_usd
        FROM accounts a
        LEFT JOIN journal_entry_lines jel ON a.code = jel.account_code
        LEFT JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE a.account_type IN ('asset', 'liability', 'equity')
    """
    params = []
    if as_of_date:
        query += " AND (je.entry_date IS NULL OR DATE(je.entry_date) <= DATE(?))"
        params.append(as_of_date)
    query += " GROUP BY a.id ORDER BY a.code ASC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    assets = []
    liabilities = []
    equity = []
    total_assets_lbp = 0.0
    total_assets_usd = 0.0
    total_liabilities_lbp = 0.0
    total_liabilities_usd = 0.0
    total_equity_lbp = 0.0
    total_equity_usd = 0.0

    for r in rows:
        deb_l = float(r['total_debit_lbp'] or 0.0)
        cr_l = float(r['total_credit_lbp'] or 0.0)
        deb_u = float(r['total_debit_usd'] or 0.0)
        cr_u = float(r['total_credit_usd'] or 0.0)
        acc_type = r['account_type']

        if acc_type == 'asset':
            net_l = deb_l - cr_l
            net_u = deb_u - cr_u
            r['balance_lbp'] = net_l
            r['balance_usd'] = net_u
            assets.append(r)
            total_assets_lbp += net_l
            total_assets_usd += net_u
        elif acc_type == 'liability':
            net_l = cr_l - deb_l
            net_u = cr_u - deb_u
            r['balance_lbp'] = net_l
            r['balance_usd'] = net_u
            liabilities.append(r)
            total_liabilities_lbp += net_l
            total_liabilities_usd += net_u
        elif acc_type == 'equity':
            net_l = cr_l - deb_l
            net_u = cr_u - deb_u
            r['balance_lbp'] = net_l
            r['balance_usd'] = net_u
            equity.append(r)
            total_equity_lbp += net_l
            total_equity_usd += net_u

    # احتساب صافي أرباح الفترة الحالية غير المقفلة بعد
    pnl = get_income_statement(start_date=None, end_date=as_of_date)
    current_net_income_lbp = pnl['net_profit_lbp']
    current_net_income_usd = pnl['net_profit_usd']

    total_equity_and_reserves_lbp = total_equity_lbp + current_net_income_lbp
    total_equity_and_reserves_usd = total_equity_usd + current_net_income_usd

    total_liab_equity_lbp = total_liabilities_lbp + total_equity_and_reserves_lbp
    total_liab_equity_usd = total_liabilities_usd + total_equity_and_reserves_usd

    diff_lbp = round(total_assets_lbp - total_liab_equity_lbp, 2)
    diff_usd = round(total_assets_usd - total_liab_equity_usd, 2)

    return {
        'assets': assets,
        'total_assets_lbp': total_assets_lbp,
        'total_assets_usd': total_assets_usd,
        'liabilities': liabilities,
        'total_liabilities_lbp': total_liabilities_lbp,
        'total_liabilities_usd': total_liabilities_usd,
        'equity': equity,
        'total_equity_lbp': total_equity_lbp,
        'total_equity_usd': total_equity_usd,
        'current_net_income_lbp': current_net_income_lbp,
        'current_net_income_usd': current_net_income_usd,
        'total_equity_and_reserves_lbp': total_equity_and_reserves_lbp,
        'total_equity_and_reserves_usd': total_equity_and_reserves_usd,
        'total_liabilities_and_equity_lbp': total_liab_equity_lbp,
        'total_liabilities_and_equity_usd': total_liab_equity_usd,
        'is_balanced': abs(diff_lbp) <= 1.0,
        'difference_lbp': diff_lbp,
        'difference_usd': diff_usd,
        'as_of_date': as_of_date or get_business_date()
    }


def close_fiscal_year(fiscal_year: int, closed_by: str = 'المدير', notes: str = '') -> tuple:
    """
    إقفال السنة المالية رسمياً وتصفير الحسابات المؤقتة وترحيل صافي الربح إلى الأرباح المدورة:
    - حساب كافة إيرادات ومصروفات السنة المحددة
    - إنشاء قيد إقفال سنوي رسمي (Year-End Closing Journal Entry)
    - تصفير حسابات 4xxx و 5xxx وترحيل الفارق دائن لحساب 3020 (الأرباح المبقاة والمدورة)
    - تسجيل الإقفال في سجل fiscal_year_closings
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM fiscal_year_closings WHERE fiscal_year = ?", (fiscal_year,))
    if cursor.fetchone():
        conn.close()
        return False, f"السنة المالية {fiscal_year} مقفلة بالفعل ولا يمكن إقفالها مرتين"

    start_date = f"{fiscal_year}-01-01"
    end_date = f"{fiscal_year}-12-31"

    # جلب أرصدة حسابات الإيرادات والمصروفات للسنة
    cursor.execute("""
        SELECT a.code, a.name_ar, a.account_type,
            COALESCE(SUM(jel.debit_lbp), 0) as deb_lbp,
            COALESCE(SUM(jel.credit_lbp), 0) as cr_lbp,
            COALESCE(SUM(jel.debit_usd), 0) as deb_usd,
            COALESCE(SUM(jel.credit_usd), 0) as cr_usd
        FROM accounts a
        JOIN journal_entry_lines jel ON a.code = jel.account_code
        JOIN journal_entries je ON jel.journal_entry_id = je.id
        WHERE a.account_type IN ('revenue', 'expense')
          AND je.status = 'posted'
          AND DATE(je.entry_date) >= DATE(?) AND DATE(je.entry_date) <= DATE(?)
        GROUP BY a.code
    """, (start_date, end_date))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        return False, f"لا توجد حركات مالية مسجلة في السنة {fiscal_year} لإقفالها"

    closing_lines = []
    tot_rev_lbp = 0.0
    tot_rev_usd = 0.0
    tot_exp_lbp = 0.0
    tot_exp_usd = 0.0

    for r in rows:
        code = r['code']
        acc_type = r['account_type']
        deb_l, cr_l = float(r['deb_lbp'] or 0.0), float(r['cr_lbp'] or 0.0)
        deb_u, cr_u = float(r['deb_usd'] or 0.0), float(r['cr_usd'] or 0.0)

        if acc_type == 'revenue':
            net_l = cr_l - deb_l
            net_u = cr_u - deb_u
            if abs(net_l) > 0 or abs(net_u) > 0:
                tot_rev_lbp += net_l
                tot_rev_usd += net_u
                # لتصفير الإيراد: نجعله مدين (Debit)
                closing_lines.append({
                    'account_code': code,
                    'debit_lbp': net_l, 'credit_lbp': 0.0,
                    'debit_usd': net_u, 'credit_usd': 0.0,
                    'memo': f"إقفال حساب إيراد {r['name_ar']} للسنة {fiscal_year}"
                })
        elif acc_type == 'expense':
            net_l = deb_l - cr_l
            net_u = deb_u - cr_u
            if abs(net_l) > 0 or abs(net_u) > 0:
                tot_exp_lbp += net_l
                tot_exp_usd += net_u
                # لتصفير المصروف: نجعله دائن (Credit)
                closing_lines.append({
                    'account_code': code,
                    'debit_lbp': 0.0, 'credit_lbp': net_l,
                    'debit_usd': 0.0, 'credit_usd': net_u,
                    'memo': f"إقفال حساب مصروف {r['name_ar']} للسنة {fiscal_year}"
                })

    net_profit_lbp = tot_rev_lbp - tot_exp_lbp
    net_profit_usd = tot_rev_usd - tot_exp_usd

    # ترحيل صافي الربح إلى الأرباح المبقاة والمدورة (3020)
    if net_profit_lbp >= 0:
        closing_lines.append({
            'account_code': '3020',
            'debit_lbp': 0.0, 'credit_lbp': net_profit_lbp,
            'debit_usd': 0.0, 'credit_usd': net_profit_usd,
            'memo': f"صافي ربح السنة المالية {fiscal_year} المرحل للأرباح المدورة"
        })
    else:
        closing_lines.append({
            'account_code': '3020',
            'debit_lbp': abs(net_profit_lbp), 'credit_lbp': 0.0,
            'debit_usd': abs(net_profit_usd), 'credit_usd': 0.0,
            'memo': f"صافي خسارة السنة المالية {fiscal_year} المحملة على الأرباح المدورة"
        })

    # تسجيل القيد الختامي المزدوج
    ok, je_res = record_double_entry_journal(
        description=f"قيد إقفال السنة المالية {fiscal_year} الشامل وتدوير الأرباح",
        lines=closing_lines,
        reference_type='fiscal_closing',
        reference_id=fiscal_year,
        user_name=closed_by,
        entry_date=end_date
    )
    if not ok:
        return False, f"فشل تسجيل قيد الإقفال السنوي: {je_res}"

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO fiscal_year_closings (
            fiscal_year, closing_date, total_revenues_lbp, total_expenses_lbp, net_profit_lbp,
            total_revenues_usd, total_expenses_usd, net_profit_usd, closed_by, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        fiscal_year, get_local_now(), tot_rev_lbp, tot_exp_lbp, net_profit_lbp,
        tot_rev_usd, tot_exp_usd, net_profit_usd, closed_by, notes or 'إقفال سنوي دوري معتمد'
    ))
    conn.commit()
    conn.close()

    # تحديث وتزامن شجرة الحسابات فوراً
    recalculate_all_account_balances()

    return True, {
        'fiscal_year': fiscal_year,
        'total_revenues_lbp': tot_rev_lbp,
        'total_expenses_lbp': tot_exp_lbp,
        'net_profit_lbp': net_profit_lbp,
        'entry_number': je_res
    }


def get_fiscal_closings() -> list:
    """جلب سجل إقفالات السنوات المالية المسجلة."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM fiscal_year_closings ORDER BY fiscal_year DESC")
        rows = [dict(r) for r in cursor.fetchall()]
    except Exception:
        rows = []
    conn.close()
    return rows


# =========================================================================
# 📦 STOCK MOVEMENTS & RECIPES ENGINE (حركات المخزون والمواد وتكلفة الوجبات)
# =========================================================================

def record_stock_movement(movement_type: str, item_id: int, item_name: str,
                          quantity: float, qty_before: float, qty_after: float,
                          unit_cost_lbp: float = 0.0, unit_cost_usd: float = 0.0,
                          reference_type: str = None, reference_id: int = None,
                          user_name: str = 'النظام', notes: str = '',
                          item_type: str = 'inventory') -> int:
    """تسجيل حركة مخزون دقيقة وموثقة في سجل stock_movements."""
    conn = get_db()
    cursor = conn.cursor()
    total_cost_lbp = float(quantity) * float(unit_cost_lbp)
    total_cost_usd = float(quantity) * float(unit_cost_usd)

    cursor.execute("""
        INSERT INTO stock_movements (
            movement_type, item_type, item_id, item_name, quantity,
            qty_before, qty_after, unit_cost_lbp, unit_cost_usd,
            total_cost_lbp, total_cost_usd, reference_type, reference_id,
            user_name, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        movement_type, item_type, item_id, item_name, float(quantity),
        float(qty_before), float(qty_after), float(unit_cost_lbp), float(unit_cost_usd),
        total_cost_lbp, total_cost_usd, reference_type, reference_id,
        user_name, notes.strip()
    ))
    sm_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return sm_id


def get_stock_movements(limit=100, movement_type=None):
    """جلب سجل حركات المخزون التفصيلية مع أسماء المستخدمين والأسباب."""
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM stock_movements WHERE 1=1"
    params = []
    if movement_type:
        query += " AND movement_type = ?"
        params.append(movement_type)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_recipes_for_item(cafe_item_id: int):
    """جلب مكونات ومعادلة تصنيع صنف معين."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*, i.name as raw_material_name, i.stock_qty, i.cost_per_unit, i.unit as raw_unit
        FROM recipes r
        JOIN inventory i ON r.inventory_id = i.id
        WHERE r.cafe_item_id = ?
    """, (cafe_item_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def calculate_item_cogs(cafe_item_id: int) -> dict:
    """
    حساب تكلفة إنتاج صنف الكافيه (COGS) بدقة بناءً على مكونات الـ recipes وتكلفة المواد في المخزون:
    إذا لم يكن للصنف وصفة، تعتمد التكلفة المسجلة في cafe_items مباشرة.
    """
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    recipes = get_recipes_for_item(cafe_item_id)
    if recipes:
        total_cost_lbp = sum(float(r.get('required_qty', 0)) * float(r.get('cost_per_unit', 0)) for r in recipes)
        total_cost_usd = round(total_cost_lbp / rate, 2) if rate > 0 else 0.0
        return {'cost_lbp': total_cost_lbp, 'cost_usd': total_cost_usd, 'is_recipe': True}

    # فحص التكلفة المباشرة للصنف
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT cost_price_lbp, cost_price_usd FROM cafe_items WHERE id = ?", (cafe_item_id,))
    row = cursor.fetchone()
    conn.close()
    cost_lbp = float(row['cost_price_lbp'] or 0.0) if row else 0.0
    cost_usd = float(row['cost_price_usd'] or 0.0) if row else (round(cost_lbp / rate, 2) if rate > 0 else 0.0)
    return {'cost_lbp': cost_lbp, 'cost_usd': cost_usd, 'is_recipe': False}

# Alias for backwards compatibility
get_inventory_items = get_inventory_stock


def import_inventory_from_csv(file_stream):
    """
    Import and bulk upsert products and inventory items from CSV.
    Supports Arabic Excel CSV (UTF-8, UTF-8-sig, cp1256).
    Flexible columns: name, category, price_lbp, price_usd, wholesale_price_lbp, cost_price_lbp, stock_qty, low_stock_limit.
    """
    import csv
    import io

    # Read bytes and try decoding
    raw_bytes = file_stream.read()
    text = None
    for enc in ('utf-8-sig', 'utf-8', 'windows-1256', 'cp1252', 'latin-1'):
        try:
            text = raw_bytes.decode(enc)
            break
        except Exception:
            continue

    if not text:
        return False, "تعذر قراءة ترميز الملف. يرجى التأكد من حفظ الملف بصيغة UTF-8 CSV"

    stream = io.StringIO(text)
    sample = text[:2048]
    delimiter = ';' if sample.count(';') > sample.count(',') else (',' if sample.count(',') >= sample.count('\t') else '\t')
    reader = csv.reader(stream, delimiter=delimiter)

    rows = list(reader)
    if not rows or len(rows) < 2:
        return False, "الملف فارغ أو لا يحتوي على صفوف بيانات كافية"

    header = [h.strip().lower() for h in rows[0]]
    
    def find_idx(keywords):
        for idx, col in enumerate(header):
            for kw in keywords:
                if kw in col:
                    return idx
        return -1

    idx_name = find_idx(['اسم', 'name', 'صنف', 'item'])
    idx_cat = find_idx(['تصنيف', 'قسم', 'category', 'cat'])
    idx_price_lbp = find_idx(['سعر البيع (ل.ل)', 'سعر البيع', 'price_lbp', 'سعر', 'price'])
    idx_price_usd = find_idx(['سعر البيع ($)', 'سعر البيع بالدولار', 'price_usd', 'usd'])
    idx_wholesale_lbp = find_idx(['جملة', 'wholesale', 'سعر الجملة'])
    idx_cost_lbp = find_idx(['تكلفة', 'تلكفة', 'cost', 'سعر التكلفة'])
    idx_qty = find_idx(['كمية', 'رصيد', 'مخزون', 'stock', 'qty'])
    idx_limit = find_idx(['حد الطلب', 'حد', 'تنبيه', 'limit'])

    if idx_name == -1:
        return False, "لم يتم العثور على عمود (اسم الصنف) في ملف الـ CSV"

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM cafe_categories")
    cat_map = {r['name'].strip().lower(): r['id'] for r in cursor.fetchall()}
    if not cat_map:
        cursor.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES ('مشروبات عامة', '☕', 1)")
        cat_map['مشروبات عامة'] = cursor.lastrowid

    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    imported_count = 0
    updated_count = 0

    for row_idx, r in enumerate(rows[1:], 2):
        if not r or len(r) <= idx_name:
            continue
        item_name = r[idx_name].strip()
        if not item_name:
            continue

        cat_name = r[idx_cat].strip() if idx_cat != -1 and len(r) > idx_cat and r[idx_cat].strip() else 'عام'
        cat_key = cat_name.lower()
        if cat_key not in cat_map:
            cursor.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES (?, '☕', 99)", (cat_name,))
            cat_id = cursor.lastrowid
            cat_map[cat_key] = cat_id
        else:
            cat_id = cat_map[cat_key]

        def parse_num(val_str):
            if not val_str:
                return 0.0
            clean = val_str.replace('ل.ل', '').replace('$', '').replace(',', '').replace(' ', '').strip()
            try:
                return float(clean)
            except Exception:
                return 0.0

        price_lbp = parse_num(r[idx_price_lbp]) if idx_price_lbp != -1 and len(r) > idx_price_lbp else 0.0
        price_usd = parse_num(r[idx_price_usd]) if idx_price_usd != -1 and len(r) > idx_price_usd else 0.0
        if price_lbp == 0 and price_usd > 0 and rate > 0:
            price_lbp = round(price_usd * rate, 0)
        elif price_usd == 0 and price_lbp > 0 and rate > 0:
            price_usd = round(price_lbp / rate, 2)

        wholesale_lbp = parse_num(r[idx_wholesale_lbp]) if idx_wholesale_lbp != -1 and len(r) > idx_wholesale_lbp else 0.0
        wholesale_usd = round(wholesale_lbp / rate, 2) if wholesale_lbp > 0 and rate > 0 else 0.0

        cost_lbp = parse_num(r[idx_cost_lbp]) if idx_cost_lbp != -1 and len(r) > idx_cost_lbp else 0.0
        cost_usd = round(cost_lbp / rate, 2) if cost_lbp > 0 and rate > 0 else 0.0

        stock_qty = parse_num(r[idx_qty]) if idx_qty != -1 and len(r) > idx_qty else 0.0
        low_limit = parse_num(r[idx_limit]) if idx_limit != -1 and len(r) > idx_limit else 5.0
        if low_limit <= 0:
            low_limit = 5.0

        is_coffee = is_coffee_item(item_name, cat_name)
        item_track_stock = 0 if is_coffee else 1
        item_stock_qty = 0.0 if is_coffee else stock_qty

        cursor.execute("SELECT id FROM cafe_items WHERE LOWER(name) = LOWER(?)", (item_name,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE cafe_items 
                SET category_id = ?, price_lbp = ?, price_usd = ?, 
                    wholesale_price_lbp = ?, wholesale_price_usd = ?,
                    cost_price_lbp = ?, cost_price_usd = ?,
                    stock_qty = CASE WHEN ? > 0 THEN ? ELSE stock_qty END,
                    low_stock_limit = ?, track_stock = ?, is_active = 1
                WHERE id = ?
            """, (cat_id, price_lbp, price_usd, wholesale_lbp, wholesale_usd, cost_lbp, cost_usd, item_stock_qty, item_stock_qty, low_limit, item_track_stock, existing['id']))
            updated_count += 1
        else:
            cursor.execute("""
                INSERT INTO cafe_items (
                    category_id, name, price_lbp, price_usd, icon, item_type, sort_order, 
                    is_active, stock_qty, track_stock, low_stock_limit, 
                    wholesale_price_lbp, wholesale_price_usd, cost_price_lbp, cost_price_usd
                ) VALUES (?, ?, ?, ?, '☕', 'cafe', 99, 1, ?, ?, ?, ?, ?, ?, ?)
            """, (cat_id, item_name, price_lbp, price_usd, item_stock_qty, item_track_stock, low_limit, wholesale_lbp, wholesale_usd, cost_lbp, cost_usd))
            imported_count += 1

    conn.commit()
    conn.close()
    return True, f"تمت معالجة ملف المنتجات بنجاح! تم استيراد ({imported_count}) صنف جديد، وتحديث بيانات ({updated_count}) صنف متوفر."


# ==============================================================================
# ☕ COFFEE BEANS & CUP YIELD TRACKING SYSTEM (نظام حبوب البن وتتبع إنتاجية الفناجين)
# ==============================================================================

# Note: COFFEE_KEYWORDS, normalize_arabic_coffee_text, and is_coffee_item are defined above with explicit cafe_items.is_coffee_bean_linked checks

def generate_coffee_batch_code(cursor):
    """
    توليد كود فريد للكيلو ومقاوم للتكرار 100%: BAG-YYYYMMDD-XX
    يفحص جميع الأكياس لليوم الحالي ويأخذ أعلى تسلسل + 1 مع التحقق الحتمي من عدم وجود أي تضارب.
    """
    from datetime import datetime
    today_str = datetime.now().strftime('%Y%m%d')
    cursor.execute("SELECT batch_code FROM coffee_bag_batches WHERE batch_code LIKE ?", (f"BAG-{today_str}-%",))
    rows = cursor.fetchall()
    max_seq = 0
    for r in rows:
        code = r['batch_code'] if isinstance(r, dict) or hasattr(r, 'keys') else r[0]
        try:
            parts = str(code).split('-')
            if len(parts) >= 3:
                num = int(parts[2])
                if num > max_seq:
                    max_seq = num
        except Exception:
            pass

    seq = max_seq + 1
    candidate = f"BAG-{today_str}-{seq:02d}"
    cursor.execute("SELECT 1 FROM coffee_bag_batches WHERE batch_code = ?", (candidate,))
    while cursor.fetchone():
        seq += 1
        candidate = f"BAG-{today_str}-{seq:02d}"
        cursor.execute("SELECT 1 FROM coffee_bag_batches WHERE batch_code = ?", (candidate,))

    return candidate

def get_coffee_beans_stock():
    """الحصول على رصيد حبوب القهوة (البن) المتوفر بالمحل بالكيلو وسعره بالدولار واللبناني وفق سعر الصرف."""
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, stock_qty, cost_per_unit FROM inventory WHERE name LIKE '%بن%' OR name LIKE '%قهوة%' LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        st_kg = round(float(row['stock_qty'] or 0.0), 2)
        c_lbp = float(row['cost_per_unit'] or 0.0)
        # حماية محاسبية: تصحيح سعر الكيلو إذا تم إدخال إجمالي ثمن الكمية (أكبر من 5 مليون لـ 2 كيلو فما فوق)
        if c_lbp > 5000000.0 and st_kg >= 2.0:
            c_lbp = round(c_lbp / st_kg, 2)
            try:
                conn_fix = get_db()
                conn_fix.execute("UPDATE inventory SET cost_per_unit = ? WHERE id = ?", (c_lbp, row['id']))
                conn_fix.commit()
                conn_fix.close()
            except Exception:
                pass

        c_usd = round(c_lbp / rate, 2) if rate > 0 else 0.0
        tot_lbp = round(st_kg * c_lbp, 2)
        tot_usd = round(st_kg * c_usd, 2)
        return {
            'item_id': row['id'],
            'name': row['name'],
            'stock_kg': st_kg,
            'cost_per_kg': c_lbp,
            'cost_per_kg_lbp': c_lbp,
            'cost_per_kg_usd': c_usd,
            'total_cost_lbp': tot_lbp,
            'total_cost_usd': tot_usd,
            'exchange_rate': rate
        }
    return {
        'item_id': None,
        'name': 'حبوب بن قهوة',
        'stock_kg': 0.0,
        'cost_per_kg': 0.0,
        'cost_per_kg_lbp': 0.0,
        'cost_per_kg_usd': 0.0,
        'total_cost_lbp': 0.0,
        'total_cost_usd': 0.0,
        'exchange_rate': rate
    }

def update_coffee_beans_stock(stock_kg: float, cost_per_kg_lbp: float = None, cost_per_kg_usd: float = None, total_cost_lbp: float = None, total_cost_usd: float = None):
    """
    تعديل أو زيادة رصيد حبوب القهوة بالكيلو وسعر شراء الكيلو الموحد بالدولار واللبناني:
    - يحدد كم كيلو متوفر بالمخزن (مثلاً 10 كيلو)
    - يحدد السعر الموحد للكيلو (سعر الشراء المعتمد لكل الكيلوات)
    - يحول تلقائياً بين الدولار واللبناني وفق سعر الصرف الموجود بالبرنامج
    """
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    stock_kg = max(0.0, float(stock_kg or 0.0))
    cost_lbp = float(cost_per_kg_lbp or 0.0)
    cost_usd = float(cost_per_kg_usd or 0.0)
    tot_lbp = float(total_cost_lbp or 0.0)
    tot_usd = float(total_cost_usd or 0.0)

    # احتساب سعر الكيلو الموحد من إجمالي التكلفة أو العملة المقابلة
    if tot_usd > 0 and stock_kg > 0:
        cost_usd = round(tot_usd / stock_kg, 2)
        cost_lbp = round(cost_usd * rate, 2)
    elif tot_lbp > 0 and stock_kg > 0 and cost_lbp <= 0 and cost_usd <= 0:
        cost_lbp = round(tot_lbp / stock_kg, 2)
        cost_usd = round(cost_lbp / rate, 2) if rate > 0 else 0.0
    elif cost_usd > 0 and cost_lbp <= 0:
        cost_lbp = round(cost_usd * rate, 2)
    elif cost_lbp > 0 and cost_usd <= 0:
        if cost_lbp > 5000000.0 and stock_kg >= 2.0:
            cost_lbp = round(cost_lbp / stock_kg, 2)
        cost_usd = round(cost_lbp / rate, 2) if rate > 0 else 0.0
    elif cost_lbp > 5000000.0 and stock_kg >= 2.0:
        cost_lbp = round(cost_lbp / stock_kg, 2)
        cost_usd = round(cost_lbp / rate, 2) if rate > 0 else 0.0
        
    conn = get_db()
    cursor = conn.cursor()
    try:
        now_str = get_local_now()
        cursor.execute("SELECT id FROM inventory WHERE name LIKE '%بن%' OR name LIKE '%قهوة%' LIMIT 1")
        row = cursor.fetchone()
        if row:
            if cost_lbp > 0:
                cursor.execute("UPDATE inventory SET stock_qty = ?, cost_per_unit = ?, updated_at = ? WHERE id = ?", (stock_kg, cost_lbp, now_str, row['id']))
            else:
                cursor.execute("UPDATE inventory SET stock_qty = ?, updated_at = ? WHERE id = ?", (stock_kg, now_str, row['id']))
        else:
            cursor.execute("""
                INSERT INTO inventory (name, category, unit, stock_qty, cost_per_unit, low_stock_limit, notes, created_at, updated_at)
                VALUES ('حبوب بن قهوة', 'مواد خام', 'كيلو (KG)', ?, ?, 2.0, 'مخزون حبوب القهوة بالكيلو', ?, ?)
            """, (stock_kg, cost_lbp, now_str, now_str))
        conn.commit()
        conn.close()
        return True, f"تم تحديث رصيد البن إلى {stock_kg} كغ بالسعر الموحد ({cost_lbp:,.0f} ل.ل ≈ ${cost_usd:,.2f} للكيلو) بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)

def get_last_closed_coffee_batch():
    """
    جلب آخر كيلو قهوة تم إغلاقه مع عدد الفناجين التي أنتجها فعلياً.
    يبحث عن آخر دفعة طبيعية مكتملة (أنتجت 30 فنجان فما فوق) لتجنب التأثر بالكيلوات التجريبية.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM coffee_bag_batches 
        WHERE status = 'closed' AND total_cups >= 30
        ORDER BY id DESC LIMIT 1
    """)
    row = cursor.fetchone()
    if not row:
        cursor.execute("""
            SELECT * FROM coffee_bag_batches 
            WHERE status = 'closed' AND (total_cups > 0 OR cups_sold > 0 OR cups_damaged > 0)
            ORDER BY id DESC LIMIT 1
        """)
        row = cursor.fetchone()
    conn.close()
    if row:
        d = dict(row)
        sold = int(d.get('cups_sold') or 0)
        damaged = int(d.get('cups_damaged') or 0)
        tot = int(d.get('total_cups') or (sold + damaged))
        d['actual_total_cups'] = tot
        return d
    return None

def get_active_coffee_batch():
    """
    جلب الكيلو المفتوح حالياً للتشغيل مع حسابات الفنجان والربح والخسارة بالتفصيل:
    - تكلفة الفنجان المستخرجة من الكيلو
    - سعر بيع الفنجان وربحه الصافي وهامش الربح
    - خسارة الفناجين التالفة المحسوبة فوراً
    - نقطة التعادل والأرباح المتوقعة
    محمي بالكامل ضد Database Locked ومع ضمان إغلاق الاتصال try...finally
    """
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM coffee_bag_batches WHERE status = 'active' ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        sold = int(d.get('cups_sold') or 0)
        damaged = int(d.get('cups_damaged') or 0)
        tot = sold + damaged
        c_lbp = float(d.get('cost_per_kg_lbp') or 0.0)
        c_usd = float(d.get('cost_per_kg_usd') or 0.0)

        # 1. المعيار الواقعي لإنتاجية الكيلو
        expected_yield = float(d.get('expected_cups_yield') or d.get('prev_batch_cups') or 0.0)
        prev_code = d.get('prev_batch_code')
        prev_batch_id = d.get('prev_batch_id')

        # إذا كان المعيار غير واقعي (أقل من 30 فنجان أو غير موجود)، نعتمد آخر كيلو مكتمل طبيعي
        if expected_yield < 30.0 or expected_yield > 150.0:
            cursor.execute("""
                SELECT id, batch_code, total_cups, cups_sold, cups_damaged 
                FROM coffee_bag_batches 
                WHERE status = 'closed' AND total_cups >= 30
                ORDER BY id DESC LIMIT 1
            """)
            prev_row = cursor.fetchone()
            if prev_row:
                p_tot = int(prev_row['total_cups'] or (int(prev_row['cups_sold'] or 0) + int(prev_row['cups_damaged'] or 0)))
                expected_yield = float(p_tot) if p_tot >= 30 else 46.0
                prev_code = prev_row['batch_code']
                prev_batch_id = prev_row['id']
            else:
                expected_yield = 46.0
                prev_code = 'معيار قياسي'
                prev_batch_id = None

            try:
                cursor.execute("""
                    UPDATE coffee_bag_batches 
                    SET prev_batch_id = ?, prev_batch_code = ?, prev_batch_cups = ?, expected_cups_yield = ?,
                        initial_cup_cost_lbp = ?, initial_cup_cost_usd = ?
                    WHERE id = ?
                """, (prev_batch_id, prev_code, int(expected_yield), expected_yield,
                      round(c_lbp / expected_yield, 2), round(c_usd / expected_yield, 4), d['id']))
                conn.commit()
            except Exception:
                pass

        # 2. متوسط سعر بيع فنجان القهوة من قائمة المنيو
        cursor.execute("""
            SELECT AVG(price_lbp) as avg_p, AVG(price_usd) as avg_u 
            FROM cafe_items 
            WHERE (is_coffee_bean_linked = 1 OR (is_coffee_bean_linked IS NULL AND name LIKE '%قهوة%')) AND name NOT LIKE '%دوبل%'
        """)
        cp_row = cursor.fetchone()
        avg_cup_price_lbp = float(cp_row['avg_p'] or 70000.0) if cp_row and cp_row['avg_p'] else 70000.0
        avg_cup_price_usd = float(cp_row['avg_u'] or 0.78) if cp_row and cp_row['avg_u'] else 0.78

        d['prev_batch_id'] = prev_batch_id
        d['prev_batch_code'] = prev_code
        d['prev_batch_cups'] = int(expected_yield)
        d['expected_cups_yield'] = expected_yield

        # تكلفة الفنجان المستخرجة من الكيلو
        unit_cup_cost_lbp = round(c_lbp / expected_yield, 2) if expected_yield > 0 else 25293.0
        unit_cup_cost_usd = round(c_usd / expected_yield, 4) if expected_yield > 0 else 0.28
        grams_per_cup = round(1000.0 / expected_yield, 1) if expected_yield > 0 else 21.7
        progress_pct = min(100, int((tot / expected_yield) * 100)) if expected_yield > 0 else 0

        d['initial_cup_cost_lbp'] = unit_cup_cost_lbp
        d['initial_cup_cost_usd'] = unit_cup_cost_usd
        d['benchmark_cup_cost_lbp'] = unit_cup_cost_lbp
        d['benchmark_cup_cost_usd'] = unit_cup_cost_usd
        d['current_cost_per_cup_lbp'] = unit_cup_cost_lbp
        d['current_cost_per_cup_usd'] = unit_cup_cost_usd
        d['grams_per_cup'] = grams_per_cup
        d['progress_pct'] = progress_pct

        # خسارة التلف المحسوبة بدقة فوراً
        loss_dmg_lbp = round(damaged * unit_cup_cost_lbp, 2)
        loss_dmg_usd = round(damaged * unit_cup_cost_usd, 4)
        d['loss_from_damage_lbp'] = loss_dmg_lbp
        d['loss_from_damage_usd'] = loss_dmg_usd
        d['total_cups_now'] = tot

        # ربح الفنجان الصافي وهامش الربح
        d['avg_cup_price_lbp'] = avg_cup_price_lbp
        d['avg_cup_price_usd'] = avg_cup_price_usd
        profit_cup_lbp = max(0.0, round(avg_cup_price_lbp - unit_cup_cost_lbp, 2))
        profit_cup_usd = max(0.0, round(avg_cup_price_usd - unit_cup_cost_usd, 4))
        d['profit_per_cup_lbp'] = profit_cup_lbp
        d['profit_per_cup_usd'] = profit_cup_usd
        d['cup_margin_pct'] = round((profit_cup_lbp / avg_cup_price_lbp * 100), 1) if avg_cup_price_lbp > 0 else 64.0

        # نقطة التعادل والأرباح المتوقعة
        d['breakeven_cups'] = int(c_lbp / avg_cup_price_lbp) + (1 if c_lbp % avg_cup_price_lbp > 0 else 0) if avg_cup_price_lbp > 0 else 17
        d['expected_revenue_lbp'] = round(expected_yield * avg_cup_price_lbp, 2)
        d['expected_revenue_usd'] = round(expected_yield * avg_cup_price_usd, 2)
        d['expected_net_profit_lbp'] = round(d['expected_revenue_lbp'] - c_lbp, 2)
        d['expected_net_profit_usd'] = round(d['expected_revenue_usd'] - c_usd, 2)

        return d
    except Exception as e:
        logger.error(f"Error in get_active_coffee_batch: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def open_coffee_bag(cost_kg_lbp=None, cost_kg_usd=None, employee_name='كاشير', notes='', auto_close_previous=True):
    """
    تسجيل فتح كيلو قهوة جديد للاستعمال (1000 جرام):
    - يخصم 1 كيلو من رصيد حبوب القهوة بالمخزن
    - يغلق الكيلو السابق تلقائياً ويوثق إنتاجيته
    - يعتمد معياراً واقعياً (أقرب كيلو طبيعي >= 30 فنجان أو 46 فنجان)
    - يولد كود دفعة فريد يمنع أي تكرار
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, batch_code FROM coffee_bag_batches WHERE status = 'active' ORDER BY id DESC LIMIT 1")
        existing = cursor.fetchone()
        closed_info = None
        if existing:
            if auto_close_previous:
                conn.close()
                ok_close, closed_info = close_coffee_bag(batch_id=existing['id'], employee_name=employee_name, notes="تم إنهاء الكيلو لفتح كيلو جديد")
                conn = get_db()
                cursor = conn.cursor()
            else:
                conn.close()
                return False, f"يوجد بالفعل كيلو مفتوح حالياً برقم ({existing['batch_code']}). يرجى إغلاقه أولاً قبل فتح كيلو جديد."

        settings = get_settings()
        rate = float(settings.get('exchange_rate') or 89500.0)

        # ── أولوية 1: السعر الموحد للكيلو المعتمد من المخزون ──
        cursor.execute("SELECT id, name, stock_qty, cost_per_unit FROM inventory WHERE name LIKE '%بن%' OR name LIKE '%قهوة%' LIMIT 1")
        inv_item = cursor.fetchone()
        inv_cost_lbp = float(inv_item['cost_per_unit'] or 0.0) if inv_item else 0.0
        if inv_cost_lbp > 5000000.0 and inv_item and float(inv_item['stock_qty'] or 0.0) >= 2.0:
            inv_cost_lbp = round(inv_cost_lbp / float(inv_item['stock_qty']), 2)

        c_lbp = float(cost_kg_lbp or 0.0)
        c_usd = float(cost_kg_usd or 0.0)
        if c_lbp > 5000000.0:
            c_lbp = 1163500.0

        if c_lbp <= 0 and c_usd <= 0 and inv_cost_lbp > 0:
            c_lbp = inv_cost_lbp
            c_usd = round(c_lbp / rate, 2) if rate > 0 else 0.0
        elif c_lbp <= 0 and c_usd > 0:
            c_lbp = c_usd * rate
        elif c_lbp > 0 and c_usd <= 0:
            c_usd = c_lbp / rate if rate > 0 else 0.0
        elif c_lbp <= 0 and c_usd <= 0:
            cursor.execute("SELECT cost_per_kg_lbp, cost_per_kg_usd FROM coffee_bag_batches WHERE cost_per_kg_lbp > 0 ORDER BY id DESC LIMIT 1")
            last_b = cursor.fetchone()
            if last_b and float(last_b['cost_per_kg_lbp'] or 0) > 0:
                c_lbp = float(last_b['cost_per_kg_lbp'])
                c_usd = float(last_b['cost_per_kg_usd'])
            else:
                c_usd = 13.0
                c_lbp = c_usd * rate

        # ── 2. تحديد المعيار الواقعي لإنتاجية الكيلو ──
        if closed_info and int(closed_info.get('total_cups') or 0) >= 30:
            prev_b_id = closed_info.get('batch_id')
            prev_b_code = closed_info.get('batch_code')
            prev_cups = int(closed_info.get('total_cups') or 46)
            expected_yield = float(prev_cups)
        else:
            cursor.execute("""
                SELECT id, batch_code, total_cups, cups_sold, cups_damaged, cost_per_cup_lbp, cost_per_cup_usd
                FROM coffee_bag_batches
                WHERE status = 'closed' AND total_cups >= 30
                ORDER BY id DESC LIMIT 1
            """)
            prev_row = cursor.fetchone()
            if prev_row:
                prev_b_id = prev_row['id']
                prev_b_code = prev_row['batch_code']
                prev_cups = int(prev_row['total_cups'])
                expected_yield = float(prev_cups)
            else:
                prev_b_id = None
                prev_b_code = 'معيار قياسي'
                prev_cups = 46
                expected_yield = 46.0

        init_cup_cost_lbp = round(c_lbp / expected_yield, 2)
        init_cup_cost_usd = round(c_usd / expected_yield, 4)

        batch_code = generate_coffee_batch_code(cursor)
        now_str = get_local_now()
        emp = str(employee_name or 'كاشير').strip()

        cursor.execute("""
            INSERT INTO coffee_bag_batches (
                batch_code, bag_weight_grams, cost_per_kg_lbp, cost_per_kg_usd,
                opened_at, opened_by, status, cups_sold, cups_damaged, total_cups,
                cost_per_cup_lbp, cost_per_cup_usd, total_revenue_lbp, total_revenue_usd,
                net_profit_lbp, net_profit_usd, prev_batch_id, prev_batch_code,
                prev_batch_cups, expected_cups_yield, initial_cup_cost_lbp, initial_cup_cost_usd, notes
            ) VALUES (?, 1000.0, ?, ?, ?, ?, 'active', 0, 0, 0, 0.0, 0.0, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (batch_code, c_lbp, c_usd, now_str, emp, -c_lbp, -c_usd,
              prev_b_id, prev_b_code, prev_cups, expected_yield, init_cup_cost_lbp, init_cup_cost_usd, notes.strip()))
        batch_id = cursor.lastrowid

        # Deduct 1 kg from inventory
        if inv_item:
            cur_st = float(inv_item['stock_qty'] or 0.0)
            new_st = max(0.0, cur_st - 1.0)
            cursor.execute("UPDATE inventory SET stock_qty = ?, updated_at = ? WHERE id = ?", (new_st, now_str, inv_item['id']))
        else:
            cursor.execute("""
                INSERT INTO inventory (name, category, unit, stock_qty, cost_per_unit, low_stock_limit, notes, created_at, updated_at)
                VALUES ('حبوب بن قهوة', 'مواد خام', 'كيلو (KG)', 0.0, ?, 2.0, 'مخزون حبوب القهوة بالكيلو', ?, ?)
            """, (c_lbp, now_str, now_str))

        conn.commit()
        return True, {
            'batch_id': batch_id,
            'batch_code': batch_code,
            'cost_kg_lbp': c_lbp,
            'cost_kg_usd': c_usd,
            'prev_batch_code': prev_b_code,
            'prev_batch_cups': prev_cups,
            'expected_cups_yield': expected_yield,
            'initial_cup_cost_lbp': init_cup_cost_lbp,
            'initial_cup_cost_usd': init_cup_cost_usd,
            'closed_previous': closed_info
        }
    except Exception as e:
        logger.error(f"Error in open_coffee_bag: {e}")
        return False, str(e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def record_coffee_cups_sold(qty: int, revenue_lbp: float = 0.0, revenue_usd: float = 0.0, item_name: str = 'قهوة'):
    """تحديث فوري لعداد فناجين القهوة المبيعة للكيلو المفتوح حالياً."""
    active_batch = get_active_coffee_batch()
    if not active_batch:
        return False, "لا يوجد كيلو قهوة مفتوح حالياً"

    conn = get_db()
    cursor = conn.cursor()
    try:
        qty = max(1, int(qty or 1))
        new_sold = int(active_batch.get('cups_sold') or 0) + qty
        new_rev_lbp = float(active_batch.get('total_revenue_lbp') or 0.0) + float(revenue_lbp or 0.0)
        new_rev_usd = float(active_batch.get('total_revenue_usd') or 0.0) + float(revenue_usd or 0.0)
        damaged = int(active_batch.get('cups_damaged') or 0)
        total_cups = new_sold + damaged

        cost_kg_lbp = float(active_batch.get('cost_per_kg_lbp') or 0.0)
        cost_kg_usd = float(active_batch.get('cost_per_kg_usd') or 0.0)

        net_prof_lbp = new_rev_lbp - cost_kg_lbp
        net_prof_usd = new_rev_usd - cost_kg_usd

        cursor.execute("""
            UPDATE coffee_bag_batches
            SET cups_sold = ?,
                total_cups = ?,
                total_revenue_lbp = ?,
                total_revenue_usd = ?,
                net_profit_lbp = ?,
                net_profit_usd = ?
            WHERE id = ?
        """, (new_sold, total_cups, new_rev_lbp, new_rev_usd, net_prof_lbp, net_prof_usd, active_batch['id']))
        conn.commit()
        return True, "تم تسجيل بيع الفناجين بنجاح"
    except Exception as e:
        logger.error(f"Error in record_coffee_cups_sold: {e}")
        return False, str(e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def record_coffee_waste(qty: int = 1, reason: str = 'تلف أثناء التحضير', employee_name: str = 'كاشير', notes: str = ''):
    """
    تسجيل فنجان تالف (تلف):
    - يخصم الفنجان من إنتاجية الكيلو كعدد مسحوب
    - يحسب سعر تلف الفنجان والخسارة الفعلية المباشرة بناءً على معيار الكيلو
    - يسجل خسارة تلف مواد خام في سجل الهدر coffee_waste_logs
    - يحدّث إجمالي الفناجين التالفة وقيمة الخسارة على الكيلو coffee_bag_batches
    """
    active_batch = get_active_coffee_batch()
    if not active_batch:
        return False, "لا يوجد كيلو قهوة مفتوح حالياً لتسجيل التالف عليه. يرجى فتح كيلو أولاً."

    conn = get_db()
    cursor = conn.cursor()
    try:
        qty = max(1, int(qty or 1))
        cost_kg_lbp = float(active_batch.get('cost_per_kg_lbp') or 0.0)
        cost_kg_usd = float(active_batch.get('cost_per_kg_usd') or 0.0)

        # ── حساب سعر تلف الفنجان بناءً على معيار الكيلو ──
        unit_cost_lbp = float(active_batch.get('benchmark_cup_cost_lbp') or active_batch.get('initial_cup_cost_lbp') or 0.0)
        unit_cost_usd = float(active_batch.get('benchmark_cup_cost_usd') or active_batch.get('initial_cup_cost_usd') or 0.0)

        # ضمان ألا تكون التكلفة صفراً أو رقماً غير واقعي
        if unit_cost_lbp <= 5000.0 or unit_cost_lbp > 60000.0:
            exp_cups = float(active_batch.get('expected_cups_yield') or 46.0)
            if exp_cups < 30: exp_cups = 46.0
            unit_cost_lbp = round(cost_kg_lbp / exp_cups, 2) if cost_kg_lbp > 0 else 25293.0
            unit_cost_usd = round(cost_kg_usd / exp_cups, 4) if cost_kg_usd > 0 else 0.28

        loss_lbp = round(unit_cost_lbp * qty, 2)
        loss_usd = round(unit_cost_usd * qty, 4)

        now_str = get_local_now()
        emp = str(employee_name or 'كاشير').strip()

        cursor.execute("""
            INSERT INTO coffee_waste_logs (
                batch_id, item_name, qty, unit_cost_lbp, unit_cost_usd,
                loss_cost_lbp, loss_cost_usd, reason, employee_name, notes, created_at
            ) VALUES (?, 'فنجان قهوة (تلف)', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (active_batch['id'], qty, unit_cost_lbp, unit_cost_usd, loss_lbp, loss_usd, reason, emp, notes, now_str))
        waste_id = cursor.lastrowid

        new_damaged = int(active_batch.get('cups_damaged') or 0) + qty
        sold = int(active_batch.get('cups_sold') or 0)
        total_cups = sold + new_damaged

        rev_lbp = float(active_batch.get('total_revenue_lbp') or 0.0)
        rev_usd = float(active_batch.get('total_revenue_usd') or 0.0)
        net_prof_lbp = rev_lbp - cost_kg_lbp
        net_prof_usd = rev_usd - cost_kg_usd

        cursor.execute("""
            UPDATE coffee_bag_batches
            SET cups_damaged = ?,
                total_cups = ?,
                net_profit_lbp = ?,
                net_profit_usd = ?
            WHERE id = ?
        """, (new_damaged, total_cups, net_prof_lbp, net_prof_usd, active_batch['id']))
        conn.commit()

        return True, {
            'waste_id': waste_id,
            'qty': qty,
            'unit_cost_lbp': unit_cost_lbp,
            'unit_cost_usd': unit_cost_usd,
            'loss_lbp': loss_lbp,
            'loss_usd': loss_usd,
            'new_damaged_total': new_damaged,
            'batch_code': active_batch['batch_code'],
            'prev_batch_code': active_batch.get('prev_batch_code')
        }
    except Exception as e:
        logger.error(f"Error in record_coffee_waste: {e}")
        return False, str(e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def close_coffee_bag(batch_id=None, employee_name='كاشير', notes=''):
    """
    إنهاء وإغلاق الكيلو:
    - حساب عدد الفناجين الكلي التي أنتجها الكيلو
    - حساب رسمال وتكلفة الفنجان الواحد الدقيق
    - حساب صافي أرباح الكيلو ونسبة الهدر
    - أرشفة الكيلو في السجل ليصبح معياراً للكيلو القادم تلقائياً
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        if batch_id:
            cursor.execute("SELECT * FROM coffee_bag_batches WHERE id = ?", (batch_id,))
        else:
            cursor.execute("SELECT * FROM coffee_bag_batches WHERE status = 'active' ORDER BY id DESC LIMIT 1")
        batch = cursor.fetchone()
        if not batch:
            conn.close()
            return False, "لم يتم العثور على كيلو مفتوح لإنهائه"

        b_id = batch['id']
        sold = int(batch['cups_sold'] or 0)
        damaged = int(batch['cups_damaged'] or 0)
        total_cups = sold + damaged

        cost_kg_lbp = float(batch['cost_per_kg_lbp'] or 0.0)
        cost_kg_usd = float(batch['cost_per_kg_usd'] or 0.0)

        cost_cup_lbp = round(cost_kg_lbp / max(1, total_cups), 2) if total_cups > 0 else 0.0
        cost_cup_usd = round(cost_kg_usd / max(1, total_cups), 4) if total_cups > 0 else 0.0

        rev_lbp = float(batch['total_revenue_lbp'] or 0.0)
        rev_usd = float(batch['total_revenue_usd'] or 0.0)
        net_prof_lbp = rev_lbp - cost_kg_lbp
        net_prof_usd = rev_usd - cost_kg_usd
        loss_damaged_lbp = round(damaged * cost_cup_lbp, 2)
        loss_damaged_usd = round(damaged * cost_cup_usd, 4)

        now_str = get_local_now()
        emp = str(employee_name or 'كاشير').strip()
        combined_notes = (str(batch['notes'] or '') + " | " + str(notes or '')).strip(' |')

        cursor.execute("""
            UPDATE coffee_bag_batches
            SET status = 'closed',
                closed_at = ?,
                closed_by = ?,
                total_cups = ?,
                cost_per_cup_lbp = ?,
                cost_per_cup_usd = ?,
                net_profit_lbp = ?,
                net_profit_usd = ?,
                notes = ?
            WHERE id = ?
        """, (now_str, emp, total_cups, cost_cup_lbp, cost_cup_usd, net_prof_lbp, net_prof_usd, combined_notes, b_id))

        conn.commit()
        return True, {
            'batch_id': b_id,
            'batch_code': batch['batch_code'],
            'total_cups': total_cups,
            'cups_sold': sold,
            'cups_damaged': damaged,
            'cost_per_cup_lbp': cost_cup_lbp,
            'cost_per_cup_usd': cost_cup_usd,
            'cost_per_kg_lbp': cost_kg_lbp,
            'cost_per_kg_usd': cost_kg_usd,
            'total_revenue_lbp': rev_lbp,
            'total_revenue_usd': rev_usd,
            'net_profit_lbp': net_prof_lbp,
            'net_profit_usd': net_prof_usd,
            'loss_damaged_lbp': loss_damaged_lbp,
            'loss_damaged_usd': loss_damaged_usd
        }
    except Exception as e:
        logger.error(f"Error in close_coffee_bag: {e}")
        return False, str(e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def get_coffee_dashboard_summary():
    """كشف إحصائي وتحليلي شامل لنظام القهوة والبن مع تقييم واضح لنتائج كل كيلو."""
    conn = get_db()
    cursor = conn.cursor()

    active_batch = get_active_coffee_batch()
    prev_batch = get_last_closed_coffee_batch()

    if active_batch and active_batch.get('expected_cups_yield'):
        benchmark_cups = int(active_batch['expected_cups_yield'])
        benchmark_code = active_batch.get('prev_batch_code')
    elif prev_batch and prev_batch.get('actual_total_cups'):
        benchmark_cups = int(prev_batch['actual_total_cups'])
        benchmark_code = prev_batch.get('batch_code')
    else:
        cursor.execute("SELECT AVG(total_cups) as avg_c FROM coffee_bag_batches WHERE total_cups >= 30")
        avg_row = cursor.fetchone()
        benchmark_cups = int(avg_row['avg_c']) if avg_row and avg_row['avg_c'] else 46
        benchmark_code = 'المتوسط العام'

    stock_info = get_coffee_beans_stock()
    stock_info['expected_cups'] = int(stock_info.get('stock_kg', 0.0) * benchmark_cups) if benchmark_cups > 0 else 0

    cursor.execute("SELECT * FROM coffee_bag_batches WHERE status = 'closed' ORDER BY id DESC LIMIT 50")
    closed_batches = [dict(r) for r in cursor.fetchall()]

    for b in closed_batches:
        tot = int(b.get('total_cups') or 0)
        dmg = int(b.get('cups_damaged') or 0)
        sold = int(b.get('cups_sold') or 0)
        c_kg = float(b.get('cost_per_kg_lbp') or 0.0)
        rev = float(b.get('total_revenue_lbp') or 0.0)
        c_cup = float(b.get('cost_per_cup_lbp') or 0.0)
        if c_cup <= 0 and tot > 0:
            c_cup = round(c_kg / tot, 2)
        b['cost_per_cup_lbp'] = c_cup
        b['loss_from_damage_lbp'] = round(dmg * c_cup, 2)
        b['grams_per_cup'] = round(1000.0 / max(1, tot), 1) if tot > 0 else 0.0

        avg_sale_price = round(rev / max(1, sold), 0) if sold > 0 else 70000.0
        b['cup_profit_lbp'] = max(0.0, avg_sale_price - c_cup)

        net_p = float(b.get('net_profit_lbp') or (rev - c_kg))
        b['net_profit_lbp'] = net_p
        margin = round((net_p / rev * 100), 1) if rev > 0 and net_p > 0 else 0.0
        b['margin_pct'] = margin

        if tot >= 30:
            if net_p > 0:
                b['rating_badge'] = f"+{net_p:,.0f} ل.ل (ربح {margin}%)"
                b['rating_title'] = f"✅ كيلو رابح (+{net_p:,.0f} ل.ل)"
                b['rating_desc'] = f"أنتج {tot} فنجان ({sold} مباع + {dmg} تلف)"
                b['rating_color'] = 'emerald'
            else:
                b['rating_badge'] = f"{net_p:,.0f} ل.ل"
                b['rating_title'] = f"⚠️ إنتاجية منخفضة ({tot} فنجان)"
                b['rating_desc'] = f"عجز بقيمة {net_p:,.0f} ل.ل"
                b['rating_color'] = 'amber'
        else:
            b['rating_badge'] = f"أُغلق مبكراً ({tot} فنجان)"
            b['rating_title'] = f"ℹ️ أُغلق مبكراً ({tot} فناجين فقط)"
            b['rating_desc'] = f"تم إغلاقه قبل استهلاك الكيلو بالكامل"
            b['rating_color'] = 'indigo'

    cursor.execute("""
        SELECT w.*, b.batch_code
        FROM coffee_waste_logs w
        LEFT JOIN coffee_bag_batches b ON w.batch_id = b.id
        ORDER BY w.id DESC LIMIT 50
    """)
    waste_logs = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT
            COUNT(id) as total_bags_count,
            COALESCE(SUM(cups_sold), 0) as all_cups_sold,
            COALESCE(SUM(cups_damaged), 0) as all_cups_damaged,
            COALESCE(SUM(total_cups), 0) as all_cups_produced,
            COALESCE(SUM(total_revenue_lbp), 0) as all_revenue_lbp,
            COALESCE(SUM(cost_per_kg_lbp), 0) as all_cost_lbp,
            COALESCE(AVG(CASE WHEN total_cups >= 30 THEN total_cups ELSE NULL END), 46.0) as avg_cups_per_kg
        FROM coffee_bag_batches
    """)
    stats_row = dict(cursor.fetchone() or {})
    conn.close()

    return {
        'active_batch': active_batch,
        'prev_batch': prev_batch,
        'benchmark_cups': benchmark_cups,
        'benchmark_code': benchmark_code,
        'stock_info': stock_info,
        'closed_batches': closed_batches,
        'waste_logs': waste_logs,
        'stats': stats_row
    }

def get_coffee_period_stats(start_date=None, end_date=None):
    """
    جلب إحصائيات القهوة والتوالف والإنتاجية لأي فترة أو تاريخ محدد للتقارير الشاملة.
    يعطي صورة رقمية واضحة عن:
    - الفناجين المبيعة وإيراداتها
    - الفناجين التالفة وقيمة خسارتها المالية
    - تكلفة الفنجان الواحد ومتوسط ربحه
    - صافي ربح قسم القهوة بالكامل
    """
    bdate = get_business_date()
    s_date = start_date or bdate
    e_date = end_date or bdate
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    conn = get_db()
    cursor = conn.cursor()

    # 1. مبيعات القهوة من الفواتير
    cursor.execute("""
        SELECT 
            COALESCE(SUM(i.quantity), 0) as cups_sold,
            COALESCE(SUM(i.subtotal_lbp), 0) as revenue_lbp,
            COALESCE(SUM(i.subtotal_usd), 0) as revenue_usd
        FROM cafe_order_items i
        JOIN cafe_orders o ON i.order_id = o.id
        LEFT JOIN cafe_items ci ON i.item_id = ci.id
        WHERE (o.status = 'paid' OR o.status IS NULL OR o.status = '')
          AND (ci.is_coffee_bean_linked = 1 OR (ci.is_coffee_bean_linked IS NULL AND (i.item_name LIKE '%قهوة%' OR i.item_name LIKE '%اسبريسو%') AND i.item_name NOT LIKE '%كابتشينو%' AND i.item_name NOT LIKE '%نسكافيه%'))
          AND DATE(datetime(o.created_at, '-5 hours')) >= DATE(?)
          AND DATE(datetime(o.created_at, '-5 hours')) <= DATE(?)
    """, (s_date, e_date))
    sales_row = cursor.fetchone()
    cups_sold = int(sales_row['cups_sold'] or 0)
    rev_lbp = float(sales_row['revenue_lbp'] or 0.0)
    rev_usd = float(sales_row['revenue_usd'] or 0.0)

    # 2. الفناجين التالفة وسجل التلف
    cursor.execute("""
        SELECT 
            COALESCE(SUM(qty), 0) as cups_damaged,
            COALESCE(SUM(loss_cost_lbp), 0) as waste_loss_lbp,
            COALESCE(SUM(loss_cost_usd), 0) as waste_loss_usd,
            COUNT(id) as waste_count
        FROM coffee_waste_logs
        WHERE DATE(datetime(created_at, '-5 hours')) >= DATE(?)
          AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)
    """, (s_date, e_date))
    waste_row = cursor.fetchone()
    cups_damaged = int(waste_row['cups_damaged'] or 0)
    waste_loss_lbp = float(waste_row['waste_loss_lbp'] or 0.0)
    waste_loss_usd = float(waste_row['waste_loss_usd'] or 0.0)

    # 3. سجل عمليات التلف بالتفصيل
    cursor.execute("""
        SELECT w.*, b.batch_code
        FROM coffee_waste_logs w
        LEFT JOIN coffee_bag_batches b ON w.batch_id = b.id
        WHERE DATE(datetime(w.created_at, '-5 hours')) >= DATE(?)
          AND DATE(datetime(w.created_at, '-5 hours')) <= DATE(?)
        ORDER BY w.id DESC LIMIT 50
    """, (s_date, e_date))
    waste_logs = [dict(r) for r in cursor.fetchall()]

    # 4. معيار تكلفة الفنجان
    cursor.execute("""
        SELECT cost_per_cup_lbp, cost_per_cup_usd, total_cups
        FROM coffee_bag_batches
        WHERE status = 'closed' AND total_cups >= 30
        ORDER BY id DESC LIMIT 1
    """)
    bench_row = cursor.fetchone()
    if bench_row and float(bench_row['cost_per_cup_lbp'] or 0) > 0:
        cup_cost_lbp = float(bench_row['cost_per_cup_lbp'])
        cup_cost_usd = float(bench_row['cost_per_cup_usd'])
        avg_yield = float(bench_row['total_cups'])
    else:
        cup_cost_lbp = 25293.0
        cup_cost_usd = 0.28
        avg_yield = 46.0

    conn.close()

    total_cups_handled = cups_sold + cups_damaged
    total_cost_sold_lbp = round(cups_sold * cup_cost_lbp, 2)
    total_cost_sold_usd = round(cups_sold * cup_cost_usd, 4)

    # صافي ربح القهوة للفترة = الإيرادات - تكلفة الفناجين المباعة - خسارة التلف
    net_coffee_profit_lbp = round(rev_lbp - total_cost_sold_lbp - waste_loss_lbp, 2)
    net_coffee_profit_usd = round(net_coffee_profit_lbp / rate, 2) if rate > 0 else 0.0

    avg_selling_price = round(rev_lbp / max(1, cups_sold), 0) if cups_sold > 0 else 70000.0
    profit_per_cup = max(0.0, avg_selling_price - cup_cost_lbp)
    profit_margin_pct = round((profit_per_cup / avg_selling_price * 100), 1) if avg_selling_price > 0 else 64.0

    waste_rate_pct = round((cups_damaged / max(1, total_cups_handled) * 100), 1) if total_cups_handled > 0 else 0.0

    return {
        'cups_sold': cups_sold,
        'sold_cups': cups_sold,
        'cups_damaged': cups_damaged,
        'damaged_cups': cups_damaged,
        'total_cups': total_cups_handled,
        'total_cups_output': total_cups_handled,
        'revenue_lbp': rev_lbp,
        'coffee_revenue_lbp': rev_lbp,
        'revenue_usd': rev_usd,
        'coffee_revenue_usd': rev_usd,
        'waste_loss_lbp': waste_loss_lbp,
        'damage_loss_lbp': waste_loss_lbp,
        'waste_loss_usd': waste_loss_usd,
        'damage_loss_usd': waste_loss_usd,
        'waste_rate_pct': waste_rate_pct,
        'cup_cost_lbp': cup_cost_lbp,
        'benchmark_cost_per_cup_lbp': cup_cost_lbp,
        'cup_cost_usd': cup_cost_usd,
        'avg_selling_price_lbp': avg_selling_price,
        'avg_cup_price_lbp': avg_selling_price,
        'profit_per_cup_lbp': profit_per_cup,
        'profit_margin_pct': profit_margin_pct,
        'cup_profit_margin_pct': profit_margin_pct,
        'avg_yield_per_kg': avg_yield,
        'net_coffee_profit_lbp': net_coffee_profit_lbp,
        'net_coffee_profit_usd': net_coffee_profit_usd,
        'waste_logs': waste_logs
    }


# ============================================================================
# 🤖 AI SMART ASSISTANT & AUDITOR (نظام الذكاء الاصطناعي لكشف الأخطاء ومساعدة الكاشير)
# ============================================================================

def ai_audit_system(target_date=None):
    """
    مساعد و خبير تدقيق مالي ذكي بالكامل:
    - يفحص كل العمليات النقدية، فوارق الصندوق، فواتير المبيعات، ومراقبة المخزون.
    - يكتشف أي تلاعب، نسيان، نقص حاد في المخزون، أو عمليات غير منطقية.
    - يقدم نصائح استباقية للمدير والموظف لرفع المبيعات وتقليل الهدر.
    """
    if not target_date:
        target_date = get_business_date()

    issues = []
    insights = []
    tips = []

    conn = get_db()
    cursor = conn.cursor()

    # 1. فحص المخزون المنخفض والمنتهي
    try:
        cursor.execute("""
            SELECT id, name, stock_qty, low_stock_limit 
            FROM cafe_items 
            WHERE is_active = 1 AND track_stock = 1
            ORDER BY stock_qty ASC
        """)
        items = cursor.fetchall()
        out_of_stock = []
        low_stock = []
        for it in items:
            q = float(it['stock_qty'] or 0.0)
            lim = float(it['low_stock_limit'] or 5.0)
            if q <= 0:
                out_of_stock.append(it['name'])
            elif q <= lim:
                low_stock.append(f"{it['name']} (باقي {int(q)})")

        if out_of_stock:
            issues.append({
                'type': 'critical',
                'title': '🚨 أصناف نفدت بالكامل من المخزون',
                'desc': f"الأصناف التالية رصيدها 0 ويجب توريدها فوراً: {', '.join(out_of_stock[:5])}" + (f" و {len(out_of_stock)-5} أصناف أخرى" if len(out_of_stock)>5 else "")
            })
        if low_stock:
            issues.append({
                'type': 'warning',
                'title': '⚠️ أصناف تقترب من النفاد',
                'desc': f"وصلت للحد الأدنى: {', '.join(low_stock[:5])}"
            })
    except Exception:
        pass

    # 2. فحص فوارق الصندوق والتسليم اليومي
    try:
        drawer = get_drawer_cash_status(target_date)
        untransferred = float(drawer.get('total_untransferred_lbp') or 0.0)
        if untransferred > 5000000:
            insights.append({
                'type': 'info',
                'title': '💼 تراكم نقدية في درج الكاشير',
                'desc': f"يوجد في الدرج نقدية متراكمة بقيمة {untransferred:,.0f} ل.ل. الذكاء الاصطناعي ينصح بترحيل دفعة إلى الخزنة لتأمين السيولة."
            })
    except Exception:
        pass

    # 3. فحص عجز أو فروقات تسليم الوردية للموظفين
    try:
        cursor.execute("""
            SELECT employee_name, difference_lbp, actual_cash_lbp, expected_cash_lbp, difference_note, created_at
            FROM shift_closings
            WHERE (DATE(business_date) = ? OR DATE(created_at) = ?)
            ORDER BY id DESC LIMIT 10
        """, (target_date, target_date))
        shift_rows = cursor.fetchall()
        for s in shift_rows:
            diff = float(s['difference_lbp'] or 0.0)
            emp = s['employee_name'] or 'كاشير'
            if diff < -50000:
                issues.append({
                    'type': 'critical',
                    'title': f"🚨 عجز نقدي في تسليم وردية {emp}",
                    'desc': f"سجل الصندوق نقصاً بقيمة {abs(diff):,.0f} ل.ل (المتوقع: {float(s['expected_cash_lbp']):,.0f} ل.ل | الفعلي: {float(s['actual_cash_lbp']):,.0f} ل.ل). السبب: {s['difference_note'] or 'غير مسجل'}"
                })
            elif diff > 50000:
                issues.append({
                    'type': 'warning',
                    'title': f"⚠️ فائض نقدي في وردية {emp}",
                    'desc': f"سجل الصندوق زيادة بقيمة +{diff:,.0f} ل.ل في الدرج. يوصى بمراجعة الفواتير غير المسجلة."
                })
            elif abs(diff) < 1000:
                insights.append({
                    'type': 'success',
                    'title': f"✓ مطابقة مثالية 100% لوردية {emp}",
                    'desc': "تم تسليم الصندوق ومطابقة الكاش بدون أي عجز أو فلس واحد مفقود."
                })
    except Exception:
        pass

    # 4. كشف تلاعب أو حذوفات في الفواتير (Void / Cancel Anomalies)
    try:
        cursor.execute("""
            SELECT actor, action, table_name, reason, created_at
            FROM audit_log
            WHERE (DATE(created_at) = ? OR DATE(created_at, '-5 hours') = ?)
              AND (action LIKE '%DELETE%' OR action LIKE '%VOID%' OR action LIKE '%CANCEL%')
            ORDER BY id DESC LIMIT 5
        """, (target_date, target_date))
        void_rows = cursor.fetchall()
        if void_rows:
            issues.append({
                'type': 'warning',
                'title': f"🔍 عمليات حذف أو تعديل مسجلة ({len(void_rows)} عملية)",
                'desc': f"قام الموظفون بعمليات إلغاء/حذف اليوم: آخرها بواسطة {void_rows[0]['actor']} (السبب: {void_rows[0]['reason'] or 'بدون سبب'})"
            })
    except Exception:
        pass

    # 5. فحص الخصومات المرتفعة
    try:
        cursor.execute("""
            SELECT id, order_number, total_lbp, discount_lbp, employee_name, discount_reason
            FROM cafe_orders
            WHERE (DATE(created_at) = ? OR DATE(datetime(created_at, '-5 hours')) = ?) AND discount_lbp > 0
            ORDER BY discount_lbp DESC LIMIT 5
        """, (target_date, target_date))
        discounted = cursor.fetchall()
        for d in discounted:
            tot = float(d['total_lbp'] or 0.0)
            disc = float(d['discount_lbp'] or 0.0)
            if tot + disc > 0 and (disc / (tot + disc)) >= 0.30:
                issues.append({
                    'type': 'warning',
                    'title': f"🏷️ حسم مرتفع بالفاتورة #{d['order_number']}",
                    'desc': f"تم تطبيق حسم {disc:,.0f} ل.ل بنسبة تفوق 30% بواسطة {d['employee_name']} (السبب: {d['discount_reason'] or 'غير محدد'})"
                })
    except Exception:
        pass

    # 6. تحليل أداء القهوة وهدر فناجين البن المفتوح
    try:
        coffee_stats = get_coffee_period_stats(start_date=target_date, end_date=target_date)
        waste_cups = int(coffee_stats.get('total_waste_cups') or 0)
        yield_per_kg = float(coffee_stats.get('avg_yield_per_kg') or 0.0)
        if waste_cups > 3:
            issues.append({
                'type': 'warning',
                'title': f"☕ هدر غير اعتيادي بالقهوة ({waste_cups} فنجان تالف)",
                'desc': f"تم تسجيل تلف {waste_cups} فناجين بن اليوم بخسارة {float(coffee_stats.get('total_waste_loss_lbp') or 0):,.0f} ل.ل. ينصح بفحص ماكينة الإسبريسو أو تدريب الباريستا."
            })
        if yield_per_kg > 0:
            if yield_per_kg < 50:
                issues.append({
                    'type': 'warning',
                    'title': f"📉 إنتاجية كيلو البن منخفضة ({yield_per_kg:.1f} فنجان/كغ)",
                    'desc': "المعدل القياسي هو 60-75 فنجان لكل كغ. الباريستا يستخدم غرامات زائدة لكل فنجان."
                })
            else:
                insights.append({
                    'type': 'success',
                    'title': f"☕ إنتاجية ممتازة للقهوة ({yield_per_kg:.1f} فنجان/كغ)",
                    'desc': "استهلاك البن مثالي ومطابق للمعايير الاحترافية لتقليل التكلفة."
                })
    except Exception:
        pass

    # 7. التنبؤ بساعات الذروة (Peak Hours Offline Forecast)
    try:
        hourly = get_hourly_sales_distribution(target_date)
        busy_hours = sorted([h for h in hourly if h.get('orders_count', 0) > 0], key=lambda x: x.get('orders_count', 0), reverse=True)
        if busy_hours:
            top_h = busy_hours[0]
            insights.append({
                'type': 'info',
                'title': f"⏰ ذروة النشاط اليوم: الساعة {top_h['hour']}:00",
                'desc': f"سجلت هذه الساعة أعلى ضغط زبائن بـ {top_h['orders_count']} فاتورة ومبيعات {top_h['total_lbp']:,.0f} ل.ل. الذكاء الاصطناعي ينصح بتواجد باريستا إضافي في هذا التوقيت."
            })
    except Exception:
        pass

    # 8. الأصناف الأكثر ربحية والأكثر مبيعاً (Top Performers)
    try:
        cursor.execute("""
            SELECT i.item_name, SUM(i.quantity) as total_qty, SUM(i.total_price_lbp) as total_rev
            FROM cafe_order_items i
            JOIN cafe_orders o ON i.order_id = o.id
            WHERE (DATE(o.created_at) = ? OR DATE(datetime(o.created_at, '-5 hours')) = ?)
            GROUP BY i.item_name
            ORDER BY total_qty DESC LIMIT 3
        """, (target_date, target_date))
        top_items = cursor.fetchall()
        if top_items:
            names = [f"⭐ {r['item_name']} ({int(r['total_qty'])} مبيعاً)" for r in top_items]
            insights.append({
                'type': 'success',
                'title': '🏆 الأصناف الذهبية الأكثر طلباً اليوم',
                'desc': ' ، '.join(names)
            })
    except Exception:
        pass

    # 9. تحليل حركة المبيعات وتوجيهات الذكاء الاصطناعي المالية
    try:
        summary = get_daily_summary(target_date)
        tot_rev = float(summary['grand_totals']['revenue_lbp'] or 0.0)
        net_prof = float(summary['grand_totals']['net_profit_lbp'] or 0.0)
        orders_count = int(summary['orders']['count'] or 0)

        if orders_count > 0:
            avg_basket = tot_rev / orders_count
            insights.append({
                'type': 'success',
                'title': '📊 متوسط سلة الزبون (Average Basket)',
                'desc': f"متوسط إنفاق الزبون اليوم هو {avg_basket:,.0f} ل.ل عبر {orders_count} فاتورة."
            })

        if net_prof > 0 and tot_rev > 0:
            margin = (net_prof / tot_rev) * 100
            insights.append({
                'type': 'success',
                'title': f'📈 هامش صافي الربح الحقيقي: {margin:.1f}%',
                'desc': f"صافي ربح اليوم يعادل {net_prof:,.0f} ل.ل بعد خصم كافة التكاليف والمصاريف."
            })
        elif net_prof < 0:
            issues.append({
                'type': 'critical',
                'title': '📉 تنبيه: خسارة تشغيلية لليوم',
                'desc': f"المصاريف وتكلفة المواد تجاوزت إيرادات اليوم بعجز قدره {abs(net_prof):,.0f} ل.ل."
            })
    except Exception:
        pass

    tips.append("💡 الذكاء الاصطناعي: النظام يعمل أوفلاين 100% ويقوم بالتحليل الإحصائي دون الحاجة لأي اتصال بالإنترنت.")
    tips.append("💡 المخزون الذكي: كل عملية بيع تخصم مكوناتها فورياً من المستودع مع تنبيهات تلقائية عند الاقتراب من النفاد.")
    tips.append("💡 حماية الصندوق: عند تسليم الوردية، يقارن الذكاء الاصطناعي الكاش الفعلي مع القيود المحاسبية لمنع أي تلاعب.")
    tips.append("💡 نصيحة تسويقية: الأصناف الأكثر مبيعاً يمكن دمجها في عروض Combo لزيادة متوسط الفاتورة بنسبة 20%.")

    conn.close()

    health_score = 100
    for iss in issues:
        if iss['type'] == 'critical':
            health_score -= 20
        elif iss['type'] == 'warning':
            health_score -= 10
    health_score = max(20, min(100, health_score))

    return {
        'status': 'optimal' if health_score >= 85 else ('needs_attention' if health_score >= 60 else 'critical'),
        'health_score': health_score,
        'issues': issues,
        'insights': insights,
        'tips': tips,
        'audited_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }


# ============================================================================
# ✈️ TELEGRAM BOT DISPATCHER (إرسال التقارير والإشعارات اللحظية عبر التيليجرام)
# ============================================================================

def send_telegram_message(message_text, bot_token=None, chat_id=None):
    """
    إرسال رسالة نصية أو تقرير ذكي عبر Telegram Bot API مباشرة.
    """
    import urllib.request, urllib.parse, json

    if not bot_token or not chat_id:
        settings = get_settings()
        bot_token = bot_token or settings.get('telegram_bot_token', '').strip()
        chat_id = chat_id or settings.get('telegram_chat_id', '').strip()

    if not bot_token or not chat_id:
        return False, "بيانات بوت التيليجرام غير مكتملة (Bot Token أو Chat ID مفقود)"

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': str(chat_id).strip(),
        'text': message_text,
        'parse_mode': 'HTML'
    }

    try:
        data_encoded = urllib.parse.urlencode(payload).encode('utf-8')
        req = urllib.request.Request(api_url, data=data_encoded, headers={'User-Agent': 'StarGateCafeBot/5.8'})
        with urllib.request.urlopen(req, timeout=8) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            if res_json.get('ok'):
                return True, "تم إرسال الرسالة إلى التيليجرام بنجاح 🚀"
            else:
                return False, f"خطأ من تيليجرام: {res_json.get('description')}"
    except Exception as e:
        return False, f"تعذر الاتصال بخادم تيليجرام: {str(e)}"


def send_daily_closing_telegram_report(target_date=None):
    """
    إنشاء وإرسال ملخص تقرير الإغلاق المالي الذكي لليوم إلى حساب تيليجرام المحدد.
    """
    if not target_date:
        target_date = get_business_date()

    settings = get_settings()
    if not settings.get('telegram_enabled'):
        return False, "إشعارات التيليجرام غير مفعلة في الإعدادات"

    summary = get_daily_summary(target_date)
    company = settings.get('company_name', 'STARGATE CAFE')
    rate = float(settings.get('exchange_rate') or 89500.0)

    rev_lbp = summary['grand_totals']['revenue_lbp']
    rev_usd = summary['grand_totals']['revenue_usd']
    exp_lbp = summary['expenses']['total_lbp']
    profit_lbp = summary['grand_totals']['net_profit_lbp']
    profit_usd = summary['grand_totals']['net_profit_usd']
    orders_cnt = summary['orders']['count']
    gaming_rev = summary['gaming']['total_lbp']
    drawer = get_drawer_cash_status(target_date)
    untransferred = drawer.get('total_untransferred_lbp', 0.0)

    msg = f"<b>☕ تقرير الإغلاق المالي الذكي - {company}</b>\n"
    msg += f"📅 <b>التاريخ:</b> <code>{target_date}</code>\n"
    msg += f"💵 <b>سعر الصرف المعتمد:</b> <code>1$ = {rate:,.0f} ل.ل</code>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📦 <b>عدد الفواتير:</b> <b>{orders_cnt}</b> فاتورة\n"
    msg += f"💰 <b>إجمالي الإيرادات:</b> <b>{rev_lbp:,.0f} ل.ل</b> (<i>{rev_usd:,.2f}$</i>)\n"
    msg += f"🎮 <b>إيراد GAMING والكمبيوتر:</b> <b>{gaming_rev:,.0f} ل.ل</b>\n"
    msg += f"💸 <b>إجمالي المصاريف:</b> <b>{exp_lbp:,.0f} ل.ل</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"💎 <b>صافي الربح الحقيقي:</b> <b>{profit_lbp:,.0f} ل.ل</b> (<i>{profit_usd:,.2f}$</i>)\n"
    msg += f"🏦 <b>نقدية الصندوق (الدرج):</b> <b>{untransferred:,.0f} ل.ل</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🤖 <i>تم الإرسال تلقائياً بواسطة نظام الذكاء الاصطناعي STARGATE AI PRO</i>"

    return send_telegram_message(msg)


def send_shift_closing_telegram_report(emp_name, actual_cash_lbp, expected_cash_lbp, diff_lbp, diff_note="", safe_deposit_lbp=0.0, drawer_remaining_lbp=0.0, target_date=None):
    """
    إرسال تقرير إغلاق الوردية الخاص بالموظف فورياً إلى تيليجرام المدير.
    """
    if not target_date:
        target_date = get_business_date()

    settings = get_settings()
    if not settings.get('telegram_enabled'):
        return False, "إشعارات التيليجرام غير مفعلة في الإعدادات"

    company = settings.get('company_name', 'STARGATE CAFE')
    diff_status = "مطابق 100% ✓"
    if diff_lbp > 0:
        diff_status = f"زيادة في الصندوق (+{diff_lbp:,.0f} ل.ل) ⚠️"
    elif diff_lbp < 0:
        diff_status = f"عجز في الصندوق (-{abs(diff_lbp):,.0f} ل.ل) 🚨"

    msg = f"<b>🔔 محضر تسليم الصندوق وإغلاق الوردية - {company}</b>\n"
    msg += f"👤 <b>الموظف / الكاشير:</b> <b>{emp_name}</b>\n"
    msg += f"📅 <b>التاريخ:</b> <code>{target_date}</code>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🏧 <b>رصيد النظام المتوقع:</b> <code>{expected_cash_lbp:,.0f} ل.ل</code>\n"
    msg += f"💵 <b>الكاش الفعلي المعدود:</b> <b>{actual_cash_lbp:,.0f} ل.ل</b>\n"
    msg += f"⚖️ <b>حالة المطابقة:</b> <b>{diff_status}</b>\n"
    if diff_note:
        msg += f"📝 <b>ملاحظة الفارق:</b> <i>{diff_note}</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    if safe_deposit_lbp > 0:
        msg += f"🏦 <b>المُرحل إلى الخزنة الخاصة:</b> <b>{safe_deposit_lbp:,.0f} ل.ل</b>\n"
        msg += f"🪙 <b>المتبقي بالدرج كعهدة:</b> <b>{drawer_remaining_lbp:,.0f} ل.ل</b>\n"
    else:
        msg += f"💼 <b>كامل الكاش باقٍ بالدرج كعهدة للموظف التالي:</b> <b>{drawer_remaining_lbp:,.0f} ل.ل</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🤖 <i>تم إرسال المحضر تلقائياً من شاشة كاشير الموظف (STARGATE CAFE)</i>"

    return send_telegram_message(msg)


# =========================================================================
# 🛡️ COMPREHENSIVE ACTIVITY & AUDIT ARCHIVE ENGINE (سجل الرقابة الإداري الشامل)
# =========================================================================

def get_audit_logs(limit=250, action=None, actor=None, date_from=None, date_to=None):
    """
    سجل الرقابة والتدقيق الإداري الشامل لكافة المعاملات والعمليات على النظام
    """
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []
    if action and action != 'all':
        query += " AND action = ?"
        params.append(action)
    if actor and actor != 'all':
        query += " AND actor LIKE ?"
        params.append(f"%{actor}%")
    if date_from:
        query += " AND DATE(datetime(created_at, '-5 hours')) >= DATE(?)"
        params.append(date_from)
    if date_to:
        query += " AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)"
        params.append(date_to)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    cursor.execute(query, params)
    raw = [dict(r) for r in cursor.fetchall()]
    conn.close()

    action_map = {
        'CREATE_ORDER': {'label': 'فاتورة جديدة', 'color': 'emerald', 'icon': '🧾'},
        'CANCEL_ORDER': {'label': 'إلغاء فاتورة', 'color': 'rose', 'icon': '❌'},
        'SAFE_TRANSFER': {'label': 'ترحيل للخزنة', 'color': 'amber', 'icon': '🏦'},
        'SAFE_TRANSFER_ALL': {'label': 'تصفير وترحيل الدرج', 'color': 'teal', 'icon': '🚀'},
        'SAFE_WITHDRAW': {'label': 'سحب من الخزنة', 'color': 'purple', 'icon': '💸'},
        'DRAWER_KICK_MANUAL': {'label': 'فتح درج الكاشير', 'color': 'sky', 'icon': '💵'},
        'APPLY_DISCOUNT': {'label': 'حسم على فاتورة', 'color': 'orange', 'icon': '🏷️'},
        'EXPENSE_ADD': {'label': 'تسجيل مصروف', 'color': 'red', 'icon': '📤'},
        'DEBT_PAYMENT': {'label': 'سداد دين', 'color': 'blue', 'icon': '📥'},
        'DELETE_PC_LOG': {'label': 'حذف جلسة كمبيوتر', 'color': 'rose', 'icon': '🗑️'},
        'RESET_OPERATIONAL_DATA': {'label': 'تصفير البيانات', 'color': 'rose', 'icon': '⚠️'}
    }

    logs = []
    for r in raw:
        act = r.get('action') or 'ACTION'
        meta = action_map.get(act, {'label': act, 'color': 'slate', 'icon': '📋'})
        r['action_label'] = meta['label']
        r['action_color'] = meta['color']
        r['action_icon'] = meta['icon']
        logs.append(r)
    return logs


# ─────────────────────────────────────────────────────────────
# 15. Stocktaking & Periodic Physical Inventory (الجرد الدوري الفعلي)
# ─────────────────────────────────────────────────────────────

def create_stocktaking_session(notes='', employee_id=None, employee_name='المدير'):
    """إنشاء دورة جرد جديدة وتثبيت الأرصدة الدفترية النظرية لجميع المواد الحالية."""
    conn = get_db()
    cursor = conn.cursor()
    import datetime
    now = datetime.datetime.now()
    session_code = f"STK-{now.strftime('%Y%m%d-%H%M%S')}"

    cursor.execute("""
        INSERT INTO stocktaking_sessions (
            session_code, status, notes, conducted_by_id, conducted_by_name, started_at
        ) VALUES (?, 'draft', ?, ?, ?, ?)
    """, (session_code, notes, employee_id, employee_name, now.strftime('%Y-%m-%d %H:%M:%S')))
    session_id = cursor.lastrowid

    # التقاط الأرصدة الدفترية للأصناف التي تخضع لتتبع المخزون
    cursor.execute("""
        SELECT id, name, unit, stock_qty, cost_price_lbp 
        FROM cafe_items 
        WHERE (track_stock = 1 OR track_stock IS NULL) AND is_active = 1
        ORDER BY name ASC
    """)
    cafe_items = cursor.fetchall()
    for item in cafe_items:
        t_qty = float(item['stock_qty'] or 0.0)
        c_lbp = float(item['cost_price_lbp'] or 0.0)
        unit = item['unit'] or 'قطعة'
        cursor.execute("""
            INSERT INTO stocktaking_items (
                session_id, item_type, item_id, item_name, unit, theoretical_qty,
                actual_counted_qty, difference_qty, unit_cost_lbp, variance_cost_lbp, adjusted
            ) VALUES (?, 'cafe_item', ?, ?, ?, ?, ?, 0.0, ?, 0.0, 0)
        """, (session_id, item['id'], item['name'], unit, t_qty, t_qty, c_lbp))

    # التقاط المواد الخام في المستودع
    cursor.execute("""
        SELECT id, name, unit, stock_qty, cost_per_unit 
        FROM inventory 
        ORDER BY name ASC
    """)
    raw_items = cursor.fetchall()
    for raw in raw_items:
        t_qty = float(raw['stock_qty'] or 0.0)
        c_lbp = float(raw['cost_per_unit'] or 0.0)
        unit = raw['unit'] or 'g'
        cursor.execute("""
            INSERT INTO stocktaking_items (
                session_id, item_type, item_id, item_name, unit, theoretical_qty,
                actual_counted_qty, difference_qty, unit_cost_lbp, variance_cost_lbp, adjusted
            ) VALUES (?, 'inventory', ?, ?, ?, ?, ?, 0.0, ?, 0.0, 0)
        """, (session_id, raw['id'], raw['name'], unit, t_qty, t_qty, c_lbp))

    conn.commit()
    conn.close()
    return {'success': True, 'session_id': session_id, 'session_code': session_code}

def get_stocktaking_sessions(limit=50):
    """عرض قائمة جلسات الجرد الدوري المسجلة."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM stocktaking_sessions 
        ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_stocktaking_session_details(session_id):
    """جلب تفاصيل جلسة الجرد وجميع بنود المواد المحصورة."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stocktaking_sessions WHERE id = ?", (session_id,))
    session = cursor.fetchone()
    if not session:
        conn.close()
        return None
    session_dict = dict(session)

    cursor.execute("""
        SELECT * FROM stocktaking_items 
        WHERE session_id = ? 
        ORDER BY item_type DESC, item_name ASC
    """, (session_id,))
    items = [dict(r) for r in cursor.fetchall()]
    conn.close()
    session_dict['items'] = items
    return session_dict

def update_stocktaking_item_count(session_id, item_id, item_type, counted_qty, reason=''):
    """تسجيل الكمية الفعلية المحصورة لاحتساب الفروقات التلقائية."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, theoretical_qty, unit_cost_lbp 
        FROM stocktaking_items 
        WHERE session_id = ? AND item_id = ? AND item_type = ?
    """, (session_id, item_id, item_type))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "العنصر غير موجود في جلسة الجرد"

    t_qty = float(row['theoretical_qty'])
    cost = float(row['unit_cost_lbp'] or 0.0)
    diff = float(counted_qty) - t_qty
    var_cost = diff * cost

    cursor.execute("""
        UPDATE stocktaking_items 
        SET actual_counted_qty = ?, difference_qty = ?, variance_cost_lbp = ?, difference_reason = ?
        WHERE id = ?
    """, (float(counted_qty), diff, var_cost, reason, row['id']))

    # تحديث إجماليات الجلسة
    cursor.execute("""
        UPDATE stocktaking_sessions
        SET total_items_counted = (SELECT COUNT(*) FROM stocktaking_items WHERE session_id = ?),
            total_discrepancy_items = (SELECT COUNT(*) FROM stocktaking_items WHERE session_id = ? AND difference_qty != 0),
            total_variance_cost_lbp = (SELECT COALESCE(SUM(variance_cost_lbp), 0) FROM stocktaking_items WHERE session_id = ?)
        WHERE id = ?
    """, (session_id, session_id, session_id, session_id))

    conn.commit()
    conn.close()
    return True, "تم حفظ العد الفعلي بنجاح"

def finalize_stocktaking_session(session_id, approved_by_id=None, approved_by_name='المدير'):
    """اعتماد الجرد الفعلي وتطبيق التسويات المخزنية والقيود العكسية رسمياً."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stocktaking_sessions WHERE id = ?", (session_id,))
    session = cursor.fetchone()
    if not session:
        conn.close()
        return False, "جلسة الجرد غير موجودة"
    if session['status'] == 'completed':
        conn.close()
        return False, "تم اعتماد هذه الجلسة مسبقاً ولا يمكن تكرار التسوية"

    import datetime
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute("SELECT * FROM stocktaking_items WHERE session_id = ?", (session_id,))
    items = cursor.fetchall()

    conn.execute("BEGIN IMMEDIATE")
    try:
        adjusted_count = 0
        total_var = 0.0

        for item in items:
            diff = float(item['difference_qty'] or 0.0)
            if diff != 0.0:
                item_type = item['item_type']
                it_id = item['item_id']
                counted = float(item['actual_counted_qty'])
                theo = float(item['theoretical_qty'])
                cost = float(item['unit_cost_lbp'] or 0.0)
                reason = item['difference_reason'] or 'تسوية جرد دوري فعلي'

                # تعديل الرصيد المخزني الفعلي
                if item_type == 'cafe_item':
                    cursor.execute("UPDATE cafe_items SET stock_qty = ? WHERE id = ?", (counted, it_id))
                else:
                    cursor.execute("UPDATE inventory SET stock_qty = ?, updated_at = ? WHERE id = ?", (counted, now_str, it_id))

                # كتابة حركة مخزون رسمية غير قابلة للحذف
                cursor.execute("""
                    INSERT INTO stock_movements (
                        movement_type, item_type, item_id, item_name, quantity,
                        qty_before, qty_after, unit_cost_lbp, total_cost_lbp,
                        reference_type, reference_id, notes, user_name, created_at
                    ) VALUES (
                        'STOCKTAKE_ADJUSTMENT', ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        'stocktaking_session', ?, ?, ?, ?
                    )
                """, (
                    item_type, it_id, item['item_name'], diff,
                    theo, counted, cost, diff * cost,
                    session_id, reason, approved_by_name, now_str
                ))

                cursor.execute("UPDATE stocktaking_items SET adjusted = 1 WHERE id = ?", (item['id'],))
                adjusted_count += 1
                total_var += (diff * cost)

        cursor.execute("""
            UPDATE stocktaking_sessions
            SET status = 'completed',
                approved_by_id = ?,
                approved_by_name = ?,
                completed_at = ?,
                total_variance_cost_lbp = ?
            WHERE id = ?
        """, (approved_by_id, approved_by_name, now_str, total_var, session_id))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.exception("Error in finalize_stocktaking_session")
        return False, f"تعذر اعتماد الجرد: {e}"

    conn.close()
    return True, f"تم اعتماد الجرد بنجاح! تم تسوية {adjusted_count} مادة بفروقات إجمالية: {total_var:,.0f} ل.ل."

# ─────────────────────────────────────────────────────────────
# 16. Price Change History (سجل تاريخ وتعديل الأسعار)
# ─────────────────────────────────────────────────────────────

def log_price_change(item_id, item_name, old_lbp, new_lbp, old_usd, new_usd, changed_by='المدير', reason=''):
    """تسجيل أي تعديل يطرأ على سعر بيع المنتج لضمان تتبع الأسعار التاريخية."""
    if float(old_lbp or 0) == float(new_lbp or 0) and float(old_usd or 0) == float(new_usd or 0):
        return  # لا يوجد تغيير حقيقي في السعر
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO product_price_history (
                item_id, item_name, old_price_lbp, new_price_lbp,
                old_price_usd, new_price_usd, changed_by, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (item_id, item_name, old_lbp, new_lbp, old_usd, new_usd, changed_by, reason))
        conn.commit()
    except Exception as e:
        logger.warning("Could not log price change: %s", e)
    finally:
        conn.close()

def get_price_change_history(item_id=None, limit=100):
    """جلب سجل التعديلات السابقة لأسعار المنتجات."""
    conn = get_db()
    cursor = conn.cursor()
    if item_id:
        cursor.execute("""
            SELECT * FROM product_price_history 
            WHERE item_id = ? 
            ORDER BY id DESC LIMIT ?
        """, (item_id, limit))
    else:
        cursor.execute("""
            SELECT * FROM product_price_history 
            ORDER BY id DESC LIMIT ?
        """, (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

# ─────────────────────────────────────────────────────────────
# 17. 20 Core Comprehensive Reports Center (مركز التقارير الشامل)
# ─────────────────────────────────────────────────────────────

def get_comprehensive_reports_hub(date_from=None, date_to=None, employee_id=None, category_id=None):
    """
    إنتاج مركز التقارير الـ 20 الشامل وفق المعايير المالية والمخزنية المعتمدة.
    """
    conn = get_db()
    cursor = conn.cursor()
    today = get_business_date()
    df = date_from or today
    dt = date_to or today

    # 1. تقرير المبيعات الإجمالية
    cursor.execute("""
        SELECT 
            COUNT(id) as total_orders,
            COALESCE(SUM(total_lbp), 0) as total_sales_lbp,
            COALESCE(SUM(total_usd), 0) as total_sales_usd,
            COALESCE(SUM(discount_lbp), 0) as total_discounts_lbp,
            COALESCE(SUM(total_cost_lbp), 0) as total_cogs_lbp
        FROM cafe_orders
        WHERE (status = 'paid' OR status IS NULL OR status = '')
          AND (DATE(datetime(created_at, '-5 hours')) BETWEEN DATE(?) AND DATE(?))
    """, (df, dt))
    sales_overview = dict(cursor.fetchone() or {})

    # 2. تقرير طرق الدفع والعملات
    cursor.execute("""
        SELECT 
            COALESCE(payment_method, 'cash') as method,
            COUNT(id) as count,
            COALESCE(SUM(total_lbp), 0) as amount_lbp,
            COALESCE(SUM(total_usd), 0) as amount_usd
        FROM cafe_orders
        WHERE (status = 'paid' OR status IS NULL OR status = '')
          AND (DATE(datetime(created_at, '-5 hours')) BETWEEN DATE(?) AND DATE(?))
        GROUP BY method
    """, (df, dt))
    payment_methods = [dict(r) for r in cursor.fetchall()]

    # 3. تقرير المرتجعات والإلغاءات
    cursor.execute("""
        SELECT 
            COUNT(id) as cancelled_count,
            COALESCE(SUM(total_lbp), 0) as cancelled_lbp,
            COALESCE(SUM(total_usd), 0) as cancelled_usd
        FROM cafe_orders
        WHERE status = 'cancelled'
          AND (DATE(datetime(created_at, '-5 hours')) BETWEEN DATE(?) AND DATE(?))
    """, (df, dt))
    cancellations = dict(cursor.fetchone() or {})

    # 4. تقرير المصروفات التشغيلية
    cursor.execute("""
        SELECT 
            category,
            COUNT(id) as count,
            COALESCE(SUM(amount_lbp), 0) as amount_lbp,
            COALESCE(SUM(amount_usd), 0) as amount_usd
        FROM expenses
        WHERE (status = 'active' OR status IS NULL)
          AND (DATE(datetime(created_at, '-5 hours')) BETWEEN DATE(?) AND DATE(?))
        GROUP BY category
    """, (df, dt))
    expenses_by_cat = [dict(r) for r in cursor.fetchall()]

    # 5. تقرير مبيعات الأصناف الأكثر طلباً
    cursor.execute("""
        SELECT 
            item_name,
            SUM(quantity) as total_qty,
            COALESCE(SUM(subtotal_lbp), 0) as total_revenue_lbp,
            COALESCE(SUM(unit_cost_lbp * quantity), 0) as total_cost_lbp
        FROM cafe_order_items
        WHERE order_id IN (
            SELECT id FROM cafe_orders 
            WHERE (status = 'paid' OR status IS NULL OR status = '')
              AND (DATE(datetime(created_at, '-5 hours')) BETWEEN DATE(?) AND DATE(?))
        )
        GROUP BY item_name
        ORDER BY total_qty DESC LIMIT 15
    """, (df, dt))
    top_items = [dict(r) for r in cursor.fetchall()]

    # 6. تقرير ديون الزبائن والتحصيل
    cursor.execute("""
        SELECT 
            COUNT(id) as open_debts_count,
            COALESCE(SUM(remaining_lbp), 0) as total_outstanding_lbp,
            COALESCE(SUM(remaining_usd), 0) as total_outstanding_usd
        FROM customer_debts
        WHERE (status = 'unpaid' OR status = 'partial')
    """)
    debts_summary = dict(cursor.fetchone() or {})

    # 7. تقرير تنبيهات المخزون الحالي
    cursor.execute("""
        SELECT id, name, unit, stock_qty, low_stock_limit, cost_price_lbp
        FROM cafe_items
        WHERE track_stock = 1 AND stock_qty <= low_stock_limit AND is_active = 1
        ORDER BY stock_qty ASC
    """)
    low_stock_items = [dict(r) for r in cursor.fetchall()]

    # 8. تقرير فروقات الجرد الفعلي الأخيرة
    cursor.execute("""
        SELECT id, session_code, status, total_discrepancy_items, total_variance_cost_lbp, completed_at
        FROM stocktaking_sessions
        ORDER BY id DESC LIMIT 5
    """)
    recent_stocktakes = [dict(r) for r in cursor.fetchall()]

    # 9. تقرير الأرباح والخسائر التقديري (Gross & Net Profit)
    rev_lbp = float(sales_overview.get('total_sales_lbp', 0.0))
    cogs_lbp = float(sales_overview.get('total_cogs_lbp', 0.0))
    gross_profit_lbp = rev_lbp - cogs_lbp
    tot_exp_lbp = sum(float(e.get('amount_lbp', 0.0)) for e in expenses_by_cat)
    net_profit_lbp = gross_profit_lbp - tot_exp_lbp

    pnl_summary = {
        'revenue_lbp': rev_lbp,
        'cogs_lbp': cogs_lbp,
        'gross_profit_lbp': gross_profit_lbp,
        'operating_expenses_lbp': tot_exp_lbp,
        'net_profit_lbp': net_profit_lbp,
        'gross_margin_percent': round((gross_profit_lbp / rev_lbp * 100), 1) if rev_lbp > 0 else 0.0
    }

    conn.close()
    return {
        'date_from': df,
        'date_to': dt,
        'sales_overview': sales_overview,
        'payment_methods': payment_methods,
        'cancellations': cancellations,
        'expenses_by_cat': expenses_by_cat,
        'top_items': top_items,
        'debts_summary': debts_summary,
        'low_stock_items': low_stock_items,
        'recent_stocktakes': recent_stocktakes,
        'pnl_summary': pnl_summary
    }

# ─────────────────────────────────────────────────────────────
# 18. AI Business Intelligence & Smart Assistant Engine
# ─────────────────────────────────────────────────────────────

def ai_business_assistant_query(query_text):
    """
    المساعد الإداري الذكي: الإجابة الدقيقة على الأسئلة الإدارية والمالية والمخزنية
    بالاعتماد الحصري على الأرقام الحقيقية الموثقة في قاعدة البيانات، مع كشف الحالات الشاذة.
    """
    if not query_text:
        return {'success': False, 'message': 'يرجى كتابة السؤال المطلوب'}

    q = str(query_text).strip().lower()
    conn = get_db()
    cursor = conn.cursor()
    today = get_business_date()

    # 1. المنتجات الأكثر مبيعاً
    if 'أكثر' in q or 'مبيع' in q or 'top' in q:
        cursor.execute("""
            SELECT item_name, SUM(quantity) as qty, COALESCE(SUM(subtotal_lbp), 0) as rev
            FROM cafe_order_items
            GROUP BY item_name
            ORDER BY qty DESC LIMIT 5
        """)
        rows = cursor.fetchall()
        items_str = "\n".join([f"• {r['item_name']}: تم بيع {r['qty']} قطعة بإجمالي {r['rev']:,.0f} ل.ل" for r in rows])
        conn.close()
        return {
            'success': True,
            'topic': 'top_selling',
            'title': 'المنتجات الأكثر مبيعاً في النظام',
            'answer': f"استناداً إلى سجلات الفواتير المعتمدة، فإن أكثر الأصناف طلباً هي:\n\n{items_str}"
        }

    # 2. المواد التي تحتاج إلى إعادة طلب ونواقص المخزون
    elif 'نقص' in q or 'طلب' in q or 'مخزون' in q or 'reorder' in q:
        cursor.execute("""
            SELECT name, stock_qty, low_stock_limit, unit
            FROM cafe_items
            WHERE track_stock = 1 AND stock_qty <= low_stock_limit AND is_active = 1
            ORDER BY stock_qty ASC
        """)
        rows = cursor.fetchall()
        if not rows:
            conn.close()
            return {
                'success': True,
                'topic': 'inventory_health',
                'title': 'حالة المخزون ممتازة',
                'answer': "جميع الأصناف حالياً متوفرة بكميات أعلى من حد الأمان الأدنى، ولا توجد نواقص حرجة."
            }
        items_str = "\n".join([f"⚠️ {r['name']}: الرصيد الحالي {r['stock_qty']} {r['unit']} (الحد الأدنى: {r['low_stock_limit']})" for r in rows])
        conn.close()
        return {
            'success': True,
            'topic': 'low_stock_alerts',
            'title': 'تنبيه الأصناف التي تحتاج إلى إعادة طلب فوري',
            'answer': f"يوجد {len(rows)} أصناف وصلت إلى حد الأمان الأدنى أو أقل:\n\n{items_str}\n\n💡 نصيحة المساعد: يفضل إصدار طلب شراء لهذه المواد لتفادي نفادها."
        }

    # 3. الديون غير المسددة
    elif 'دين' in q or 'ذمم' in q or 'زبائن' in q or 'debt' in q:
        cursor.execute("""
            SELECT customer_name, phone, remaining_lbp, remaining_usd
            FROM customer_debts
            WHERE status IN ('unpaid', 'partial')
            ORDER BY remaining_lbp DESC LIMIT 5
        """)
        rows = cursor.fetchall()
        cursor.execute("SELECT COALESCE(SUM(remaining_lbp), 0), COALESCE(SUM(remaining_usd), 0) FROM customer_debts WHERE status IN ('unpaid', 'partial')")
        tot_lbp, tot_usd = cursor.fetchone()
        items_str = "\n".join([f"• {r['customer_name']}: متبقي {r['remaining_lbp']:,.0f} ل.ل (${r['remaining_usd']:,.2f})" for r in rows])
        conn.close()
        return {
            'success': True,
            'topic': 'debts_overview',
            'title': 'سجل الديون والذمم المدينة غير المسددة',
            'answer': f"إجمالي الديون القائمة غير المسددة هو {tot_lbp:,.0f} ل.ل (${tot_usd:,.2f}).\n\nأعلى الذمم المدينة المستحقة:\n{items_str}"
        }

    # 4. فروقات الورديات والإغلاقات
    elif 'وردية' in q or 'شفت' in q or 'فرق' in q or 'shift' in q:
        cursor.execute("""
            SELECT business_date, shift_number, employee_name, expected_cash_lbp, actual_cash_lbp, difference_lbp, difference_note
            FROM shift_closings
            WHERE difference_lbp != 0
            ORDER BY id DESC LIMIT 5
        """)
        rows = cursor.fetchall()
        if not rows:
            conn.close()
            return {
                'success': True,
                'topic': 'shift_discrepancies',
                'title': 'تطابق كامل للورديات',
                'answer': "جميع إغلاقات الورديات المسجلة متطابقة تماماً مع النقدية المتوقعة ولا توجد أي فروقات مسجلة."
            }
        items_str = "\n".join([f"• تاريخ {r['business_date']} (وردية {r['shift_number']} - {r['employee_name']}): الفرق {r['difference_lbp']:+,.0f} ل.ل (المتوقع: {r['expected_cash_lbp']:,.0f} | الفعلي: {r['actual_cash_lbp']:,.0f}) {r['difference_note'] or ''}" for r in rows])
        conn.close()
        return {
            'success': True,
            'topic': 'shift_discrepancies',
            'title': 'الورديات التي ظهرت بها فروقات صندوق',
            'answer': f"آخر الورديات المسجلة التي تضمنت فروقات في الصندوق:\n\n{items_str}"
        }

    # 5. كشف الحالات غير المعتادة (Anomalies)
    elif any(k in q for k in ['شاذ', 'معتاد', 'شذوذ', 'تحذير', 'anomaly', 'مراجعة', 'فحص']):
        # فحص كثرة الإلغاءات
        cursor.execute("SELECT COUNT(id), COALESCE(SUM(total_lbp), 0) FROM cafe_orders WHERE status = 'cancelled' AND DATE(datetime(created_at, '-5 hours')) = DATE(?)", (today,))
        c_count, c_val = cursor.fetchone()
        
        # فحص الخصومات الكبيرة
        cursor.execute("SELECT COUNT(id), COALESCE(SUM(discount_lbp), 0) FROM cafe_orders WHERE discount_lbp > 0 AND DATE(datetime(created_at, '-5 hours')) = DATE(?)", (today,))
        d_count, d_val = cursor.fetchone()

        conn.close()
        notes = []
        if c_count > 3:
            notes.append(f"⚠️ تنبيه: تم تسجيل {c_count} عمليات إلغاء اليوم بقيمة إجمالية {c_val:,.0f} ل.ل.")
        else:
            notes.append("✓ معدل إلغاء الفواتير اليوم ضمن النطاق الطبيعي.")

        if d_count > 5:
            notes.append(f"⚠️ تنبيه: تم منح حسم على {d_count} فواتير اليوم بإجمالي {d_val:,.0f} ل.ل.")
        else:
            notes.append("✓ الخصومات الممنوحة اليوم طبيعية.")

        return {
            'success': True,
            'topic': 'anomaly_detection',
            'title': 'كشف مؤشرات المراجعة والنشاط غير المعتاد',
            'answer': "\n".join(notes) + "\n\n💡 ملاحظة أمان: جميع هذه المؤشرات للإشراف والمراجعة ولا تعد دليلاً على وجود خطأ متعمد."
        }

    # استجابة عامة بالملخص المالي لليوم
    else:
        cursor.execute("""
            SELECT 
                COUNT(id) as count,
                COALESCE(SUM(total_lbp), 0) as tot_lbp,
                COALESCE(SUM(total_usd), 0) as tot_usd
            FROM cafe_orders 
            WHERE (status = 'paid' OR status IS NULL OR status = '')
              AND DATE(datetime(created_at, '-5 hours')) = DATE(?)
        """, (today,))
        row = cursor.fetchone()
        conn.close()
        return {
            'success': True,
            'topic': 'daily_summary',
            'title': f'ملخص أعمال اليوم ({today})',
            'answer': f"مرحباً بك في المساعد الإداري الذكي لـ STARGATE CAFE.\n\nمبيعات اليوم حتى اللحظة:\n• عدد الفواتير: {row['count']} فاتورة\n• الإجمالي: {row['tot_lbp']:,.0f} ل.ل (${row['tot_usd']:,.2f})\n\nيمكنك سؤالي عن: المنتجات الأكثر مبيعاً، المواد التي تحتاج لإعادة طلب، الديون غير المسددة، فروقات الورديات، أو فحص العمليات غير المعتادة."
        }




