
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
            qty = max(1, int(it.get('quantity') or 1))
        except (ValueError, TypeError):
            qty = 1

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
    business_date: str = None
) -> int:
    """
    سجل الحركة المالية المركزي المزدوج (Immutable Financial Ledger).
    يسجل حركة الكاش بدقة ويوثق الرصيد اللحظي قبل وبعد كل حركة في الدرج والخزنة.
    محمي بقفل تسلسلي Threading Lock و BEGIN IMMEDIATE لمنع أي تضارب أو Race Condition.
    """
    with _ledger_lock:
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
            conn.commit()
            conn.close()
            return ledger_id
        except Exception as e:
            logger.error(f"Error in record_financial_ledger_entry: {e}", exc_info=True)
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass
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
            status, handover_to_employee_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'closed', ?, ?)
    """, (
        business_date, employee_id, employee_name, now_str,
        opening_float_lbp, opening_float_usd,
        cash_sales_lbp, cash_sales_usd,
        debt_sales_lbp, debt_collected_lbp,
        expenses_lbp, safe_transfers_lbp,
        expected_cash_lbp, actual_cash_lbp,
        difference_lbp, difference_note, orders_count,
        handover_to_employee_name, now_str
    ))
    closing_id = cursor.lastrowid
    conn.commit()
    conn.close()

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

    cursor.execute(f"""
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
    'قهوة', 'قهوه', 'قهوة تركي', 'قهوه تركي', 'بن تركي', 'قهوة دوبل', 'قهوة اسبريسو', 'اسبريسو', 'اسبرسو حبوب', 'قهوة سادة'
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
    # Strictly exclude Cappuccino, Latte, Nescafe, sachets, tea, cold drinks, sweets, cakes
    if any(ex in name_norm for ex in ('3 in 1', '3in1', '3  1', 'ظرف', 'ساشيه', 'علبه', 'كابتشينو', 'كبتشينو', 'نسكافيه', 'لاتيه', 'موكا', 'شاي', 'عصير', 'بيبسي', 'سفن', 'مياه', 'كيك', 'حلو', 'بسكوت', 'شوكولا')):
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
    stock_qty = float(data.get('stock_qty') or 0.0)
    track_stock = 1 if data.get('track_stock') in (1, '1', True, 'on') else 0
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
    name = data.get('name', '').strip()
    category_id = data.get('category_id')
    price_lbp = float(data.get('price_lbp') or 0)
    price_usd = float(data.get('price_usd') or 0)
    icon = data.get('icon', '').strip()
    if not icon:
        existing = get_item(item_id)
        icon = existing.get('icon') if existing and existing.get('icon') else '☕'
    item_type = data.get('item_type', 'cafe').strip() or 'cafe'
    sort_order = int(data.get('sort_order') or 0)
    is_active = 1 if data.get('is_active') in (1, '1', True, 'on') else 0
    stock_qty = float(data.get('stock_qty') or 0.0) if 'stock_qty' in data else None
    track_stock = (1 if data.get('track_stock') in (1, '1', True, 'on') else 0) if 'track_stock' in data else None
    low_stock_limit = float(data.get('low_stock_limit') or 5.0) if 'low_stock_limit' in data else None
    is_coffee_bean_linked = (1 if data.get('is_coffee_bean_linked') in (1, '1', True, 'on') else 0) if 'is_coffee_bean_linked' in data else None

    # Coffee bean linked items protection
    if is_coffee_bean_linked == 1:
        if stock_qty is not None:
            stock_qty = 0.0
        if track_stock is not None:
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

    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    # 1. Calculate totals centrally using Decimal precision
    calc = calculate_order_totals(items_list, rate)
    total_lbp = calc['total_lbp']
    total_usd = calc['total_usd']
    computed_items = calc['items']

    customer_name = (order_data.get('customer_name') or '').strip() or 'زبون كاش'
    notes = order_data.get('notes', '')
    payment_method = order_data.get('payment_method', 'cash')
    paid_amount = total_lbp if payment_method == 'cash' else 0.0

    conn = get_db()
    cursor = conn.cursor()
    try:
        # 2. Check stock availability & Coffee Bag Batch BEFORE creating order or deducting (Atomic guard)
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
                conn.rollback()
                conn.close()
                first_coffee = coffee_items_found[0]
                return False, f"⚠️ لا يمكن إتمام الطلب! الصنف ({first_coffee}) مرتبط بحبوب البن، ولا يوجد كيلو قهوة مفتوح حالياً في المحل. يجب فتح كيلو جديد أولاً من زر 'فتح كيلو ☕' في قسم القهوة."

        if not tab_id:
            for it in computed_items:
                item_id = it.get('item_id')
                q = int(it.get('quantity') or 1)
                if item_id:
                    cursor.execute("SELECT stock_qty, name, track_stock FROM cafe_items WHERE id = ?", (item_id,))
                    st_row = cursor.fetchone()
                    if st_row and st_row['track_stock'] == 1:
                        available = float(st_row['stock_qty'] or 0.0)
                        if available < q:
                            conn.rollback()
                            conn.close()
                            return False, f"الكمية المطلوبة ({q}) غير متوفرة في المخزون للمنتج: {st_row['name']} (المتوفر حالياً: {int(available) if available.is_integer() else available})"

        is_wholesale = 1 if order_data.get('is_wholesale') in (1, '1', True, 'true') else 0
        if tab_id:
            # Checkout & Settle existing open customer tab
            emp_id = order_data.get('employee_id')
            emp_name = order_data.get('employee_name', 'كاشير')
            cursor.execute("""
            UPDATE cafe_orders SET
                customer_name = ?,
                total_lbp = ?,
                total_usd = ?,
                paid_amount = ?,
                payment_method = ?,
                notes = ?,
                status = 'paid',
                is_tab = 0,
                is_wholesale = ?,
                employee_id = COALESCE(?, employee_id),
                employee_name = COALESCE(?, employee_name),
                created_at = ?
            WHERE id = ?
            """, (customer_name, total_lbp, total_usd, paid_amount, payment_method, notes, is_wholesale, emp_id, emp_name, get_local_now(), tab_id))
            order_id = tab_id
            cursor.execute("SELECT order_number FROM cafe_orders WHERE id = ?", (order_id,))
            row = cursor.fetchone()
            order_num = row['order_number'] if row else generate_order_number()
            cursor.execute("DELETE FROM cafe_order_items WHERE order_id = ?", (order_id,))
        else:
            # New direct Order
            order_num = generate_order_number()
            emp_id = order_data.get('employee_id')
            emp_name = order_data.get('employee_name', 'كاشير')
            cursor.execute("""
            INSERT INTO cafe_orders (order_number, total_lbp, total_usd, paid_amount, payment_method, customer_name, notes, status, is_tab, employee_id, employee_name, is_wholesale, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'paid', 0, ?, ?, ?, ?)
            """, (order_num, total_lbp, total_usd, paid_amount, payment_method, customer_name, notes, emp_id, emp_name, is_wholesale, get_local_now()))
            order_id = cursor.lastrowid

        total_order_cogs_lbp = 0.0
        total_order_cogs_usd = 0.0
        order_coffee_cups = 0
        order_coffee_rev_lbp = 0.0
        order_coffee_rev_usd = 0.0

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

            cursor.execute("""
            INSERT INTO cafe_order_items (order_id, item_id, item_name, item_type, quantity, unit_price_lbp, unit_price_usd, subtotal_lbp, subtotal_usd, is_wholesale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, item_id, item_name, item_type, q, u_lbp, u_usd, sub_lbp, sub_usd, item_is_wholesale))

            # ☕ Accumulate coffee cups in this order ONLY if linked to coffee beans kilo bag
            item_is_coffee_bean_linked = is_coffee_item(item_name, item_id=item_id)
            if item_is_coffee_bean_linked:
                order_coffee_cups += q
                order_coffee_rev_lbp += sub_lbp
                order_coffee_rev_usd += sub_usd

            # Deduct stock for finalized sales (direct sale or tab settlement)
            # Coffee bean linked items skip individual cup tracking because they are tracked via the coffee beans batch
            if item_is_coffee_bean_linked:
                pass
            elif item_id:
                # 1. Direct finished goods stock deduction if tracked
                cursor.execute("SELECT stock_qty, name, track_stock, cost_price_lbp, cost_price_usd FROM cafe_items WHERE id = ?", (item_id,))
                cur_item_row = cursor.fetchone()
                if cur_item_row and cur_item_row['track_stock'] == 1:
                    q_before = float(cur_item_row['stock_qty'] or 0.0)
                    q_after = max(0.0, q_before - q)
                    cursor.execute("UPDATE cafe_items SET stock_qty = ? WHERE id = ?", (q_after, item_id))
                    
                    # Record Stock Movement
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
                for rec in raw_recipes:
                    consumed_qty = float(rec['required_qty'] or 0.0) * q
                    raw_id = rec['inv_id']
                    raw_before = float(rec['raw_stock'] or 0.0)
                    raw_after = max(0.0, raw_before - consumed_qty)
                    cost_unit = float(rec['cost_per_unit'] or 0.0)
                    total_cogs = consumed_qty * cost_unit
                    total_order_cogs_lbp += total_cogs

                    cursor.execute("UPDATE inventory SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (raw_after, raw_id))
                    try:
                        cursor.execute("""
                            INSERT INTO stock_movements (
                                movement_type, item_type, item_id, item_name, quantity,
                                qty_before, qty_after, unit_cost_lbp, total_cost_lbp,
                                reference_type, reference_id, user_name, notes
                            ) VALUES ('RECIPE_CONSUMPTION', 'inventory', ?, ?, ?, ?, ?, ?, ?, 'cafe_orders', ?, ?, ?)
                        """, (raw_id, rec['raw_name'], consumed_qty, raw_before, raw_after, cost_unit, total_cogs, order_id, emp_name, f"استهلاك مبيع ({q} {item_name})"))
                    except Exception:
                        pass

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

        # ☕ Update Active Coffee Bag Batch atomically in the same transaction
        if order_coffee_cups > 0:
            try:
                cursor.execute("SELECT * FROM coffee_bag_batches WHERE status = 'active' ORDER BY id DESC LIMIT 1")
                act_b = cursor.fetchone()
                if act_b:
                    n_sold = int(act_b['cups_sold'] or 0) + order_coffee_cups
                    n_rev_lbp = float(act_b['total_revenue_lbp'] or 0.0) + order_coffee_rev_lbp
                    n_rev_usd = float(act_b['total_revenue_usd'] or 0.0) + order_coffee_rev_usd
                    n_damaged = int(act_b['cups_damaged'] or 0)
                    n_tot = n_sold + n_damaged
                    c_kg_lbp = float(act_b['cost_per_kg_lbp'] or 0.0)
                    c_kg_usd = float(act_b['cost_per_kg_usd'] or 0.0)
                    n_prof_lbp = n_rev_lbp - c_kg_lbp
                    n_prof_usd = n_rev_usd - c_kg_usd

                    cursor.execute("""
                        UPDATE coffee_bag_batches
                        SET cups_sold = ?,
                            total_cups = ?,
                            total_revenue_lbp = ?,
                            total_revenue_usd = ?,
                            cost_per_cup_lbp = 0.0,
                            cost_per_cup_usd = 0.0,
                            net_profit_lbp = ?,
                            net_profit_usd = ?
                        WHERE id = ?
                    """, (n_sold, n_tot, n_rev_lbp, n_rev_usd, n_prof_lbp, n_prof_usd, act_b['id']))
            except Exception:
                pass

        conn.commit()
        conn.close()

        # Record in central financial ledger & Double Entry Accounting
        try:
            if payment_method == 'cash':
                record_financial_ledger_entry(
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
                    business_date=get_business_date()
                )

                # Double Entry: Debit Cash Drawer (1010), Credit Sales Revenue (4010)
                record_double_entry_journal(
                    description=f"مبيع نقدي فاتورة #{order_num} ({customer_name})",
                    lines=[
                        {'account_code': '1010', 'debit_lbp': total_lbp, 'credit_lbp': 0.0, 'debit_usd': total_usd, 'credit_usd': 0.0, 'memo': f"قبض نقدي #{order_num}"},
                        {'account_code': '4010', 'debit_lbp': 0.0, 'credit_lbp': total_lbp, 'debit_usd': 0.0, 'credit_usd': total_usd, 'memo': f"إيراد مبيعات كافيه #{order_num}"}
                    ],
                    reference_type='cafe_orders',
                    reference_id=order_id,
                    user_name=emp_name
                )
            elif payment_method == 'debt':
                # Double Entry: Debit Accounts Receivable (1030), Credit Sales Revenue (4010)
                record_double_entry_journal(
                    description=f"مبيع آجل دين على الزبون فاتورة #{order_num} ({customer_name})",
                    lines=[
                        {'account_code': '1030', 'debit_lbp': total_lbp, 'credit_lbp': 0.0, 'debit_usd': total_usd, 'credit_usd': 0.0, 'memo': f"ذمة مدينة #{order_num}"},
                        {'account_code': '4010', 'debit_lbp': 0.0, 'credit_lbp': total_lbp, 'debit_usd': 0.0, 'credit_usd': total_usd, 'memo': f"إيراد مبيعات آجل #{order_num}"}
                    ],
                    reference_type='cafe_orders',
                    reference_id=order_id,
                    user_name=emp_name
                )
        except Exception:
            pass

        return True, {'order_id': order_id, 'order_number': order_num, 'total_lbp': total_lbp, 'total_usd': total_usd, 'payment_method': payment_method}
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)

def save_customer_tab(customer_name, items_list=None, tab_id=None, notes=''):
    """Save or update an open customer tab (الزبائن الجالسون بالمحل)."""
    items_list = items_list or []
    customer_name = (customer_name or '').strip() or 'زبون في المحل'
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    calc = calculate_order_totals(items_list, rate)
    total_lbp = calc['total_lbp']
    total_usd = calc['total_usd']
    computed_items = calc['items']

    conn = get_db()
    cursor = conn.cursor()
    try:
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

        if tab_id:
            # Update existing open tab
            cursor.execute("""
            UPDATE cafe_orders SET
                customer_name = ?,
                total_lbp = ?,
                total_usd = ?,
                notes = ?,
                status = 'open',
                is_tab = 1
            WHERE id = ?
            """, (customer_name, total_lbp, total_usd, notes, tab_id))
            order_id = tab_id
            cursor.execute("SELECT order_number FROM cafe_orders WHERE id = ?", (order_id,))
            row = cursor.fetchone()
            order_num = row['order_number'] if row else generate_order_number()
            cursor.execute("DELETE FROM cafe_order_items WHERE order_id = ?", (order_id,))
        else:
            # Create new open tab
            order_num = generate_order_number()
            cursor.execute("""
            INSERT INTO cafe_orders (order_number, total_lbp, total_usd, paid_amount, payment_method, customer_name, notes, status, is_tab, created_at)
            VALUES (?, ?, ?, 0.0, 'tab', ?, ?, 'open', 1, ?)
            """, (order_num, total_lbp, total_usd, customer_name, notes, get_local_now()))
            order_id = cursor.lastrowid

        for it in computed_items:
            item_id = it.get('item_id')
            item_name = it.get('name', 'صنف')
            item_type = it.get('item_type') or ('gaming' if 'gaming' in item_name.lower() or 'ألعاب' in item_name or 'كمبيوتر' in item_name else ('others' if it.get('is_custom') or not item_id else 'cafe'))
            q = it['quantity']
            u_lbp = it['price_lbp']
            u_usd = it['price_usd']
            sub_lbp = it['subtotal_lbp']
            sub_usd = it['subtotal_usd']

            cursor.execute("""
            INSERT INTO cafe_order_items (order_id, item_id, item_name, item_type, quantity, unit_price_lbp, unit_price_usd, subtotal_lbp, subtotal_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, item_id, item_name, item_type, q, u_lbp, u_usd, sub_lbp, sub_usd))

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


def delete_tab(tab_id):
    """إلغاء طاولة/حساب مفتوح دون المساس بالمخزون (لأن المخزون لا يُخصم إلا عند الدفع وإصدار الفاتورة)."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Delete open tab items and order
        cursor.execute("DELETE FROM cafe_order_items WHERE order_id = ?", (tab_id,))
        cursor.execute("DELETE FROM cafe_orders WHERE id = ? AND status = 'open'", (tab_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error in delete_tab: {e}", exc_info=True)
        conn.rollback()
        conn.close()
        return False

def get_orders(target_date=None, limit=5000, employee_id=None):
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
    WHERE (o.status = 'paid' OR o.status IS NULL OR o.status = '')
    """
    params = []
    if target_date:
        query += " AND (DATE(datetime(o.created_at, '-5 hours')) = DATE(?) OR DATE(o.created_at) = DATE(?))"
        params.extend([target_date, target_date])
    if employee_id is not None:
        query += " AND (o.employee_id = ? OR o.employee_id IS NULL)"
        params.append(employee_id)
    query += " GROUP BY o.id ORDER BY o.id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


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
        SUM(i.subtotal_lbp) as total_lbp,
        SUM(i.subtotal_usd) as total_usd,
        SUM(CASE WHEN i.is_wholesale = 1 OR o.is_wholesale = 1 THEN i.subtotal_lbp ELSE 0 END) as wholesale_revenue_lbp,
        SUM(CASE WHEN (i.is_wholesale = 0 OR i.is_wholesale IS NULL) AND (o.is_wholesale = 0 OR o.is_wholesale IS NULL) THEN i.subtotal_lbp ELSE 0 END) as retail_revenue_lbp,
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
        SUM(i.subtotal_lbp - (COALESCE(
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
    cursor.execute("SELECT * FROM cafe_order_items WHERE order_id = ? ORDER BY id ASC", (order_id,))
    items_list = [dict(r) for r in cursor.fetchall()]
    res['items'] = items_list
    res['order_items'] = items_list
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

        # 2. Restore inventory for all items (return stock)
        cursor.execute("SELECT item_id, quantity FROM cafe_order_items WHERE order_id = ?", (order_id,))
        for item_row in cursor.fetchall():
            iid = item_row['item_id']
            qty = item_row['quantity']
            if iid:
                cursor.execute("""
                UPDATE cafe_items
                SET stock_qty = stock_qty + ?
                WHERE id = ? AND track_stock = 1
                """, (qty, iid))

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
    cursor.execute(f"""
    SELECT 
        COUNT(id) as orders_count,
        COALESCE(SUM(total_lbp), 0) as total_lbp,
        COALESCE(SUM(total_usd), 0) as total_usd,
        COALESCE(SUM(CASE WHEN payment_method = 'cash' THEN total_lbp ELSE 0 END), 0) as cash_sales_lbp,
        COALESCE(SUM(CASE WHEN payment_method = 'cash' THEN total_usd ELSE 0 END), 0) as cash_sales_usd,
        COALESCE(SUM(CASE WHEN payment_method = 'debt' THEN total_lbp ELSE 0 END), 0) as debt_sales_lbp,
        COALESCE(SUM(CASE WHEN payment_method = 'debt' THEN total_usd ELSE 0 END), 0) as debt_sales_usd
    FROM cafe_orders
    WHERE DATE(datetime(created_at, '-5 hours')) = DATE(?) AND (status = 'paid' OR status IS NULL OR status = '')
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

    # 1. Cafe items breakdown (coffee, drinks, snacks) - Strictly isolated
    cursor.execute("""
    SELECT 
        COALESCE(SUM(i.quantity), 0) as cups_count,
        COALESCE(SUM(i.subtotal_lbp), 0) as total_lbp,
        COALESCE(SUM(i.subtotal_usd), 0) as total_usd
    FROM cafe_order_items i
    JOIN cafe_orders o ON i.order_id = o.id
    WHERE DATE(datetime(o.created_at, '-5 hours')) = DATE(?) AND (o.status = 'paid' OR o.status IS NULL OR o.status = '') AND (
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

    # 2. GAMING PC & Computer breakdown - Dedicated isolated accounts & profit
    cursor.execute("""
    SELECT 
        COALESCE(SUM(i.quantity), 0) as clicks_count,
        COALESCE(SUM(i.subtotal_lbp), 0) as total_lbp,
        COALESCE(SUM(i.subtotal_usd), 0) as total_usd
    FROM cafe_order_items i
    JOIN cafe_orders o ON i.order_id = o.id
    WHERE DATE(datetime(o.created_at, '-5 hours')) = DATE(?) AND (o.status = 'paid' OR o.status IS NULL OR o.status = '') AND (
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
    # 100% of gaming/computer revenue is pure net profit (no raw food/drink cost)
    pc_res['profit_lbp'] = pc_res['total_lbp']
    pc_res['profit_usd'] = pc_res['total_usd']

    # 3. Others breakdown
    cursor.execute("""
    SELECT 
        COALESCE(SUM(i.quantity), 0) as count,
        COALESCE(SUM(i.subtotal_lbp), 0) as total_lbp,
        COALESCE(SUM(i.subtotal_usd), 0) as total_usd
    FROM cafe_order_items i
    JOIN cafe_orders o ON i.order_id = o.id
    WHERE DATE(datetime(o.created_at, '-5 hours')) = DATE(?) AND (o.status = 'paid' OR o.status IS NULL OR o.status = '') AND i.item_type = 'others'
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
    """, (target_date, target_date, f"%{target_date}%"))
    safe_day_row = dict(cursor.fetchone() or {})

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

    grand_totals = {
        'revenue_lbp': actual_cash_in_lbp,
        'revenue_usd': actual_cash_in_usd,
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

        else: # 'full' (ضبط المصنع الشامل 100%)
            # Get list of all user tables
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

            # Re-initialize clean fresh database schema
            database.init_db(seed_items=False)

            # Determine admin password / PIN securely
            if admin_pin and len(str(admin_pin).strip()) >= 4:
                final_admin_hash = database.hash_password(str(admin_pin).strip())
                pin_notice = f"رمز دخول الإدارة المعتمد: {admin_pin}"
            elif preserved_admin_hash:
                final_admin_hash = preserved_admin_hash
                pin_notice = "تم الحفاظ على رمز وكلمة سر الإدارة السابقة"
            else:
                # Generate a secure random 6-digit PIN
                gen_pin = str(random.randint(100000, 999999))
                final_admin_hash = database.hash_password(gen_pin)
                pin_notice = f"رمز دخول الإدارة العشوائي الجديد: {gen_pin}"

            # Ensure default STARGATE settings with hashed admin credentials
            conn2 = get_db()
            conn2.execute("""
                UPDATE settings 
                SET company_name = 'STARGATE', exchange_rate = 89500.0, 
                    pc_price_per_click_lbp = 100000.0, is_seeded = 1,
                    admin_password = ?
                WHERE id = 1
            """, (final_admin_hash,))
            
            # Ensure default admin employee exists with the same secure credentials
            cursor2 = conn2.cursor()
            cursor2.execute("SELECT id FROM employees WHERE role = 'admin' LIMIT 1")
            admin_emp = cursor2.fetchone()
            if not admin_emp:
                cursor2.execute("""
                    INSERT INTO employees (name, role, pin_hash, is_active, max_discount_pct, can_void_orders)
                    VALUES (?, ?, ?, 1, 100, 1)
                """, ('المدير العام', 'admin', final_admin_hash))
            
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
                reason='استعادة ضبط المصنع الشامل'
            )
            return True, f"تمت استعادة ضبط المصنع بنجاح 100%! تم تصفير ومسح كافة البيانات ليصبح السيستم نظيفاً تماماً. ({pin_notice})"

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
                cursor.execute(f"""
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
    """Export complete system data (Settings, Categories, Menu, Debts, Expenses, Orders) as JSON dictionary."""
    conn = get_db()
    cursor = conn.cursor()
    
    settings = get_settings()
    
    cursor.execute("SELECT * FROM cafe_categories ORDER BY sort_order ASC, id ASC")
    categories = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM cafe_items ORDER BY sort_order ASC, id ASC")
    items = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM customer_debts ORDER BY id ASC")
    debts = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM debt_payments ORDER BY id ASC")
    debt_payments = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM expenses ORDER BY id ASC")
    expenses = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM pc_usage_logs ORDER BY id ASC")
    pc_logs = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM cafe_orders ORDER BY id ASC")
    orders = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM cafe_order_items ORDER BY id ASC")
    order_items = [dict(r) for r in cursor.fetchall()]

    try:
        cursor.execute("SELECT * FROM safe_transfers ORDER BY id ASC")
        safe_transfers = [dict(r) for r in cursor.fetchall()]
    except Exception:
        safe_transfers = []
    
    conn.close()
    
    return {
        'app': 'STARGATE',
        'version': '4.5.0',
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
        'safe_transfers': safe_transfers
    }

def import_full_system_data(data):
    """Safely restore all system data from full JSON dictionary."""
    if not isinstance(data, dict) or data.get('app') != 'STARGATE':
        return False, "ملف غير صالح أو لا يتبع لنظام STARGATE"

    conn = get_db()
    cursor = conn.cursor()
    try:
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
                INSERT OR REPLACE INTO cafe_items (id, category_id, name, price_lbp, price_usd, icon, item_type, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (i.get('id'), i.get('category_id'), i.get('name'), float(i.get('price_lbp') or 0), float(i.get('price_usd') or 0),
                      i.get('icon', '☕'), i.get('item_type', 'cafe'), i.get('sort_order', 0), int(i.get('is_active', 1))))

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
                INSERT OR REPLACE INTO cafe_order_items (id, order_id, item_id, item_name, item_type, quantity, unit_price_lbp, unit_price_usd, subtotal_lbp, subtotal_usd, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (oi.get('id'), oi.get('order_id'), oi.get('item_id'), oi.get('item_name'), oi.get('item_type', 'cafe'),
                      int(oi.get('quantity', 1)), float(oi.get('unit_price_lbp') or 0), float(oi.get('unit_price_usd') or 0),
                      float(oi.get('subtotal_lbp') or 0), float(oi.get('subtotal_usd') or 0), oi.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))))

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

        conn.commit()
        try:
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        conn.close()
        return True, "تمت استعادة كافة بيانات النظام والمنيو والديون وسجل الخزنة بنجاح 100%!"
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

def add_safe_transfer(amount_lbp=0.0, note='', transferred_by='المدير', rate=None, amount_usd=None, operation_type='deposit', employee_id=None, source='drawer', target='safe'):
    """نقل أو سحب مبلغ من/إلى الخزنة الخاصة مع التمييز الدقيق بين مصادر النقدية والوجهات وتوثيقه في السجل المالي."""
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
        WHERE payment_method = 'cash' AND (status = 'paid' OR status IS NULL OR status = '')
    """)
    all_cash_sales_lbp = float(cursor.fetchone()[0] or 0.0)

    # 2. مبيعات كاش اليوم
    cursor.execute("""
        SELECT COALESCE(SUM(total_lbp), 0)
        FROM cafe_orders
        WHERE payment_method = 'cash' AND (status = 'paid' OR status IS NULL OR status = '')
          AND DATE(datetime(created_at, '-5 hours')) = DATE(?)
    """, (today_bdate,))
    today_cash_sales_lbp = float(cursor.fetchone()[0] or 0.0)

    # 3. مبيعات كاش الأمس والفترات السابقة
    past_cash_sales_lbp = max(0.0, all_cash_sales_lbp - today_cash_sales_lbp)

    # 4. إجمالي سدادات الديون المستلمة عبر كل التاريخ
    cursor.execute("SELECT COALESCE(SUM(amount_lbp), 0) FROM debt_payments")
    all_debt_rep_lbp = float(cursor.fetchone()[0] or 0.0)

    # 5. إجمالي المصاريف المسددة من الدرج عبر كل التاريخ (المصاريف من الخزنة لا تخصم من الدرج)
    cursor.execute("SELECT COALESCE(SUM(amount_lbp), 0) FROM expenses WHERE source != 'safe' OR source IS NULL")
    all_expenses_lbp = float(cursor.fetchone()[0] or 0.0)

    # 6. إجمالي ما رُحِّل للخزنة الخاصة من الدرج (خصماً من الدرج)
    # ملاحظة جوهرية: مسحوبات الخزنة الشخصية للمدير لا تُعاد للدرج إلا إذا حُدد صراحة أنها تمويل للدرج (target='drawer')
    cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN operation_type = 'deposit' AND (source != 'external' OR source IS NULL) THEN amount_lbp ELSE 0 END), 0) as deposits_from_drawer,
            COALESCE(SUM(CASE WHEN operation_type = 'withdraw' AND target = 'drawer' THEN amount_lbp ELSE 0 END), 0) as returned_to_drawer
        FROM safe_transfers
    """)
    safe_row = cursor.fetchone()
    total_safe_deposits_lbp = float(safe_row[0] or 0.0)
    total_returned_to_drawer_lbp = float(safe_row[1] or 0.0)
    # الكاش الصافي الذي خرج من الدرج باتجاه الخزنة
    net_to_safe_lbp = max(0.0, total_safe_deposits_lbp - total_returned_to_drawer_lbp)

    conn.close()

    # الكاش الإجمالي الفعلي الموجود بالدرج الآن ولم ينقل للخزنة بعد:
    # (كل الكاش الداخل للدرج) - (مصاريف الدرج) - (صافي ما نُقل للخزنة)
    total_income_lbp = all_cash_sales_lbp + all_debt_rep_lbp
    total_outflow_lbp = all_expenses_lbp + net_to_safe_lbp
    total_untransferred_lbp = max(0.0, total_income_lbp - total_outflow_lbp)
    total_untransferred_usd = round(total_untransferred_lbp / rate, 2) if rate > 0 else 0.0

    # الكاش السابق (قبل اليوم) غير المرحّل للخزنة
    # نحسبه بنسبة: (past_cash / all_cash) * total_untransferred
    if all_cash_sales_lbp > 0:
        past_ratio = past_cash_sales_lbp / all_cash_sales_lbp
    else:
        past_ratio = 0.0
    past_untransferred_lbp = round(total_untransferred_lbp * past_ratio, 0)
    past_untransferred_usd = round(past_untransferred_lbp / rate, 2) if rate > 0 else 0.0

    return {
        'all_cash_sales_lbp': all_cash_sales_lbp,
        'today_cash_sales_lbp': today_cash_sales_lbp,
        'past_cash_sales_lbp': past_cash_sales_lbp,
        'past_untransferred_lbp': past_untransferred_lbp,
        'past_untransferred_usd': past_untransferred_usd,
        'total_untransferred_lbp': total_untransferred_lbp,
        'total_untransferred_usd': total_untransferred_usd,
        'all_transferred_to_safe_lbp': net_to_safe_lbp,
        'all_debt_rep_lbp': all_debt_rep_lbp,
        'all_expenses_lbp': all_expenses_lbp
    }


# =========================================================================
# SPECIAL SAFE DAILY TRANSFER & COMPREHENSIVE REPORTS ENGINE
# =========================================================================

def check_daily_safe_transfer_status(target_date=None):
    """
    يفحص ما إذا كان كاش اليوم أو تاريخ محدد قد تم ترحيله إلى الخزنة الخاصة بالفعل أم لا،
    ويحسب صافي الكاش المتاح للترحيل (المبيعات النقدية - المصاريف النقدية).
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
        ORDER BY id DESC
    """, (target_date, target_date, f"%{target_date}%"))
    existing_transfers = [dict(r) for r in cursor.fetchall()]

    # 2. احتساب إجمالي مبيعات اليوم النقدية فقط (الكاش الفعلي الداخل للدرج)
    cursor.execute("""
        SELECT 
            COALESCE(SUM(total_lbp), 0) as cash_sales_lbp,
            COALESCE(SUM(total_usd), 0) as cash_sales_usd,
            COUNT(id) as orders_count
        FROM cafe_orders
        WHERE payment_method = 'cash'
          AND (status = 'paid' OR status IS NULL OR status = '')
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
    """, (target_date, target_date))
    exp_row = dict(cursor.fetchone() or {})
    total_expenses_lbp = float(exp_row.get('expenses_lbp') or 0.0)
    total_expenses_usd = float(exp_row.get('expenses_usd') or 0.0)

    # 4. مجموع ما تم ترحيله بالفعل لهذا التاريخ من الدرج إلى الخزنة
    already_transferred_lbp = sum(float(t.get('amount_lbp') or 0.0) for t in existing_transfers if t.get('source') != 'external')
    already_transferred_usd = sum(float(t.get('amount_usd') or 0.0) for t in existing_transfers if t.get('source') != 'external')

    conn.close()

    # صافي الكاش المتبقي للترحيل
    net_day_cash_lbp = max(0.0, total_sales_lbp - total_expenses_lbp)
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

    # Log in General Ledger
    try:
        record_financial_ledger_entry(
            account_type='cash_safe' if payment_source == 'safe' else 'cash_drawer',
            entry_type='credit',
            amount_lbp=paid_l,
            amount_usd=paid_u,
            reference_table='supplier_payments',
            reference_id=supplier_id,
            user_name=created_by,
            notes=f"سداد دفعة للمورد {supp['name']} ({notes})"
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
    """جلب شجرة الحسابات المحاسبية كاملة مع أرصدتها وحالتها."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.*,
            COALESCE(SUM(jel.debit_lbp - jel.credit_lbp), 0) as calculated_balance_lbp,
            COALESCE(SUM(jel.debit_usd - jel.credit_usd), 0) as calculated_balance_usd
        FROM accounts a
        LEFT JOIN journal_entry_lines jel ON a.code = jel.account_code
        GROUP BY a.id
        ORDER BY a.code ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def record_double_entry_journal(description: str, lines: list, reference_type: str = None,
                                reference_id: int = None, user_name: str = 'النظام',
                                entry_date: str = None) -> tuple:
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

    conn = get_db()
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
            cursor.execute("SELECT name_ar, name FROM accounts WHERE code = ?", (code,))
            acc_row = cursor.fetchone()
            acc_name = acc_row['name_ar'] if acc_row else (l.get('account_name') or code)

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

            # تحديث رصيد الحساب المباشر
            net_change_lbp = float(l.get('debit_lbp') or 0.0) - float(l.get('credit_lbp') or 0.0)
            net_change_usd = float(l.get('debit_usd') or 0.0) - float(l.get('credit_usd') or 0.0)
            cursor.execute("""
                UPDATE accounts
                SET balance_lbp = balance_lbp + ?,
                    balance_usd = balance_usd + ?
                WHERE code = ?
            """, (net_change_lbp, net_change_usd, code))

        conn.commit()
        conn.close()
        return True, entry_number
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


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
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM coffee_bag_batches WHERE status = 'active' ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if not row:
        conn.close()
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

        cursor.execute("""
            UPDATE coffee_bag_batches 
            SET prev_batch_id = ?, prev_batch_code = ?, prev_batch_cups = ?, expected_cups_yield = ?,
                initial_cup_cost_lbp = ?, initial_cup_cost_usd = ?
            WHERE id = ?
        """, (prev_batch_id, prev_code, int(expected_yield), expected_yield,
              round(c_lbp / expected_yield, 2), round(c_usd / expected_yield, 4), d['id']))
        conn.commit()

    # 2. متوسط سعر بيع فنجان القهوة من قائمة المنيو
    cursor.execute("""
        SELECT AVG(price_lbp) as avg_p, AVG(price_usd) as avg_u 
        FROM cafe_items 
        WHERE (is_coffee_bean_linked = 1 OR (is_coffee_bean_linked IS NULL AND name LIKE '%قهوة%')) AND name NOT LIKE '%دوبل%'
    """)
    cp_row = cursor.fetchone()
    avg_cup_price_lbp = float(cp_row['avg_p'] or 70000.0) if cp_row and cp_row['avg_p'] else 70000.0
    avg_cup_price_usd = float(cp_row['avg_u'] or 0.78) if cp_row and cp_row['avg_u'] else 0.78
    conn.close()

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
        conn.close()
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
        conn.close()
        return False, str(e)

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
        conn.close()
        return True, "تم تسجيل بيع الفناجين بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)

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
        conn.close()

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
        conn.close()
        return False, str(e)

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
        conn.close()

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
        conn.close()
        return False, str(e)

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

