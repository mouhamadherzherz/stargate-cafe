
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
import database
from database import get_db, init_db

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

def generate_order_number():
    date_str = datetime.now().strftime('%Y%m%d')
    rand_num = random.randint(1000, 9999)
    return f"CAF-{date_str}-{rand_num}"

# ----------------- SETTINGS -----------------

def get_settings():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM settings WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {
        'company_name': 'STARGATE',
        'currency': 'ل.ل',
        'secondary_currency': '$',
        'exchange_rate': 89500.0,
        'pc_price_per_click_lbp': 100000.0,
        'admin_password': '19701313'
    }

def get_admin_password():
    """Retrieve current active admin password."""
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
    return '19701313'

def verify_admin_password(entered_pin):
    """Verify if entered PIN matches the active admin password."""
    if not entered_pin:
        return False
    current_pin = get_admin_password()
    return str(entered_pin).strip() == str(current_pin).strip()

def update_admin_password(new_pin):
    """Update admin password to a new value."""
    if not new_pin or len(str(new_pin).strip()) == 0:
        return False, "يرجى إدخال كلمة سر صحيحة"
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET admin_password = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1", (str(new_pin).strip(),))
        conn.commit()
        conn.close()
        return True, "تم تغيير كلمة سر الإدارة بنجاح!"
    except Exception as e:
        return False, f"فشل أثناء تغيير كلمة السر: {str(e)}"

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
    query += " ORDER BY (CASE WHEN i.item_type = 'gaming' THEN 0 ELSE 1 END), c.sort_order ASC, i.sort_order ASC, i.name ASC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def add_item(data):
    name = data.get('name', '').strip()
    category_id = data.get('category_id')
    price_lbp = float(data.get('price_lbp') or 0)
    icon = data.get('icon', '☕').strip() or '☕'
    item_type = data.get('item_type', 'cafe').strip() or 'cafe'
    sort_order = int(data.get('sort_order') or 0)
    stock_qty = float(data.get('stock_qty') or 0.0)
    track_stock = 1 if data.get('track_stock') in (1, '1', True, 'on') else 0
    low_stock_limit = float(data.get('low_stock_limit') or 5.0)

    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    price_usd = round(price_lbp / rate, 2) if rate > 0 else 0

    if not name or not category_id:
        return False, "اسم الصنف والتصنيف مطلوبان"

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
        INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, icon, item_type, sort_order, is_active, stock_qty, track_stock, low_stock_limit)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """, (category_id, name, price_lbp, price_usd, icon, item_type, sort_order, stock_qty, track_stock, low_stock_limit))
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

    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    price_usd = round(price_lbp / rate, 2) if rate > 0 else 0

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
                low_stock_limit = ?
            WHERE id = ?
            """, (category_id, name, price_lbp, price_usd, icon, item_type, sort_order, is_active, stock_qty, track_stock, low_stock_limit, item_id))
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
                is_active = ?
            WHERE id = ?
            """, (category_id, name, price_lbp, price_usd, icon, item_type, sort_order, is_active, item_id))
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

    total_lbp = 0.0
    for it in items_list:
        q = int(it.get('quantity') or 1)
        p = float(it.get('price_lbp') or 0)
        total_lbp += (q * p)
    total_usd = round(total_lbp / rate, 2) if rate > 0 else 0.0

    customer_name = (order_data.get('customer_name') or '').strip() or 'زبون كاش'
    notes = order_data.get('notes', '')
    payment_method = order_data.get('payment_method', 'cash')
    paid_amount = total_lbp if payment_method == 'cash' else 0.0

    conn = get_db()
    cursor = conn.cursor()
    try:
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
                employee_id = COALESCE(?, employee_id),
                employee_name = COALESCE(?, employee_name),
                created_at = ?
            WHERE id = ?
            """, (customer_name, total_lbp, total_usd, paid_amount, payment_method, notes, emp_id, emp_name, get_local_now(), tab_id))
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
            INSERT INTO cafe_orders (order_number, total_lbp, total_usd, paid_amount, payment_method, customer_name, notes, status, is_tab, employee_id, employee_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'paid', 0, ?, ?, ?)
            """, (order_num, total_lbp, total_usd, paid_amount, payment_method, customer_name, notes, emp_id, emp_name, get_local_now()))
            order_id = cursor.lastrowid

        for it in items_list:
            item_id = it.get('item_id')
            item_name = it.get('name', 'صنف')
            item_type = it.get('item_type') or ('gaming' if 'gaming' in item_name.lower() or 'ألعاب' in item_name or 'كمبيوتر' in item_name else ('others' if it.get('is_custom') or not item_id else 'cafe'))
            q = int(it.get('quantity') or 1)
            u_lbp = float(it.get('price_lbp') or 0)
            u_usd = round(u_lbp / rate, 2) if rate > 0 else 0
            sub_lbp = u_lbp * q
            sub_usd = round(sub_lbp / rate, 2) if rate > 0 else 0

            cursor.execute(f"""
            INSERT INTO cafe_order_items (order_id, item_id, item_name, item_type, quantity, unit_price_lbp, unit_price_usd, subtotal_lbp, subtotal_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, item_id, item_name, item_type, q, u_lbp, u_usd, sub_lbp, sub_usd))

            # Deduct stock ONLY if direct sale (not already deducted on open tab)
            if item_id and not tab_id:
                try:
                    cursor.execute(f"""
                    UPDATE cafe_items 
                    SET stock_qty = MAX(0, stock_qty - ?) 
                    WHERE id = ? AND track_stock = 1
                    """, (q, item_id))
                except Exception:
                    pass

        # If payment is debt (آجل), automatically insert into customer_debts
        if payment_method == 'debt':
            cursor.execute("""
            INSERT INTO customer_debts (customer_name, phone, order_id, order_number, amount_lbp, amount_usd, paid_lbp, paid_usd, remaining_lbp, remaining_usd, status, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0.0, 0.0, ?, ?, 'unpaid', ?, ?)
            """, (customer_name, order_data.get('phone', ''), order_id, order_num, total_lbp, total_usd, total_lbp, total_usd, notes or 'فاتورة كاشير معلقة على الحساب', get_local_now()))

        conn.commit()
        conn.close()
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

    total_lbp = 0.0
    for it in items_list:
        q = int(it.get('quantity') or 1)
        p = float(it.get('price_lbp') or 0)
        total_lbp += (q * p)
    total_usd = round(total_lbp / rate, 2) if rate > 0 else 0.0

    conn = get_db()
    cursor = conn.cursor()
    try:
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

        for it in items_list:
            item_id = it.get('item_id')
            item_name = it.get('name', 'صنف')
            item_type = it.get('item_type') or ('gaming' if 'gaming' in item_name.lower() or 'ألعاب' in item_name or 'كمبيوتر' in item_name else ('others' if it.get('is_custom') or not item_id else 'cafe'))
            q = int(it.get('quantity') or 1)
            u_lbp = float(it.get('price_lbp') or 0)
            u_usd = round(u_lbp / rate, 2) if rate > 0 else 0
            sub_lbp = u_lbp * q
            sub_usd = round(sub_lbp / rate, 2) if rate > 0 else 0

            cursor.execute(f"""
            INSERT INTO cafe_order_items (order_id, item_id, item_name, item_type, quantity, unit_price_lbp, unit_price_usd, subtotal_lbp, subtotal_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, item_id, item_name, item_type, q, u_lbp, u_usd, sub_lbp, sub_usd))

            # Deduct stock ONLY if direct sale (not already deducted on open tab)
            if item_id and not tab_id:
                try:
                    cursor.execute(f"""
                    UPDATE cafe_items 
                    SET stock_qty = MAX(0, stock_qty - ?) 
                    WHERE id = ? AND track_stock = 1
                    """, (q, item_id))
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


def delete_tab(tab_id):
    """إلغاء طاولة/حساب مفتوح مع استرجاع كميات المخزون للأصناف فورياً."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        # 1. Restore stock for items in this tab
        cursor.execute("SELECT item_id, quantity FROM cafe_order_items WHERE order_id = ?", (tab_id,))
        for row in cursor.fetchall():
            iid = row['item_id']
            qty = row['quantity']
            if iid:
                cursor.execute("""
                UPDATE cafe_items
                SET stock_qty = stock_qty + ?
                WHERE id = ? AND track_stock = 1
                """, (qty, iid))

        # 2. Delete tab
        cursor.execute("DELETE FROM cafe_orders WHERE id = ? AND status = 'open'", (tab_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        conn.close()
        return False

def get_orders(target_date=None, limit=100, employee_id=None):
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
        query += " AND DATE(datetime(o.created_at, '-5 hours')) = DATE(?)"
        params.append(target_date)
    if employee_id is not None:
        query += " AND o.employee_id = ?"
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
        SUM(i.subtotal_lbp) as total_lbp,
        SUM(i.subtotal_usd) as total_usd,
        ROUND(AVG(i.unit_price_lbp), 0) as avg_price_lbp,
        ROUND(AVG(i.unit_price_usd), 2) as avg_price_usd
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

    for r in rows:
        r['pct'] = round((float(r['total_lbp'] or 0) / grand_total_lbp * 100), 1) if grand_total_lbp > 0 else 0.0
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

def delete_order(order_id):
    """حذف/إلغاء فاتورة مع استرجاع المخزون تلقائياً وإلغاء أي ذمة مرتبطة."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        # 1. Restore inventory for all items in this order
        cursor.execute("SELECT item_id, quantity FROM cafe_order_items WHERE order_id = ?", (order_id,))
        for row in cursor.fetchall():
            iid = row['item_id']
            qty = row['quantity']
            if iid:
                cursor.execute("""
                UPDATE cafe_items
                SET stock_qty = stock_qty + ?
                WHERE id = ? AND track_stock = 1
                """, (qty, iid))

        # 2. Delete or cancel associated debt if was on credit
        cursor.execute("DELETE FROM customer_debts WHERE order_id = ?", (order_id,))

        # 3. Delete order and items (via CASCADE)
        cursor.execute("DELETE FROM cafe_orders WHERE id = ?", (order_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        conn.close()
        return False

def log_single_pc_click(price_lbp=None, note='استخدام كمبيوتر GAMING'):
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
    success, res = create_order({'customer_name': 'لاعب GAMING', 'notes': note}, items_list)
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
        return True, eid
    except Exception as e:
        conn.close()
        return False, str(e)

def get_expenses(target_date=None, limit=200, source=None):
    """جلب سجل المصاريف مع دعم التصفية باليوم ومصدر السداد."""
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM expenses WHERE 1=1"
    params = []
    if target_date:
        query += " AND DATE(datetime(created_at, '-5 hours')) = DATE(?)"
        params.append(target_date)
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

def delete_expense(expense_id):
    """حذف مصروف وإلغاء أثره المحاسبي في الخزنة إذا كان مرتبطاً بها."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,))
    row = cursor.fetchone()
    if row:
        exp = dict(row)
        if exp.get('source') == 'safe':
            # تنظيف حركة سحب الخزنة المرتبطة
            cursor.execute("DELETE FROM safe_transfers WHERE note LIKE ? AND operation_type = 'withdraw'", (f"%مصروف من الخزنة: {exp.get('title')}%",))
        cursor.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        conn.commit()
    conn.close()
    return True

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
        'net_profit_usd': net_cash_profit_usd
    }

    return {
        'target_date': target_date,
        'exchange_rate': rate,
        'cafe': cafe_res,
        'pc': pc_res,
        'others': others_res,
        'open_tabs': open_tabs_res,
        'expenses': exp_res,
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

def factory_reset(reset_type='full'):
    """
    Reset system to factory default or clear transactions.
    reset_type: 'full' -> completely drops everything and re-creates seed menu & settings from scratch.
                'transactions_only' -> clears all orders, open tabs, expenses, logs, debts, and resets counters.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        if reset_type == 'transactions_only':
            cursor.execute("DELETE FROM cafe_order_items")
            cursor.execute("DELETE FROM cafe_orders")
            cursor.execute("DELETE FROM expenses")
            cursor.execute("DELETE FROM pc_usage_logs")
            cursor.execute("DELETE FROM debt_payments")
            cursor.execute("DELETE FROM customer_debts")
            cursor.execute("DELETE FROM safe_transfers")  # BUG-FIX: clear vault history on reset
            try:
                cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('cafe_orders', 'cafe_order_items', 'expenses', 'pc_usage_logs', 'customer_debts', 'debt_payments', 'safe_transfers')")
            except Exception:
                pass
            conn.commit()
            try:
                cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            conn.close()
            return True, "تم تصفير جميع المبيعات والفواتير والزبائن الجالسين والمصاريف والديون والخزنة كلياً بنجاح! تم الحفاظ على قائمة المشروبات وأسعار المنيو."
        else: # 'full'
            all_tables = ['debt_payments', 'customer_debts', 'pc_usage_logs', 'expenses',
                          'cafe_order_items', 'cafe_orders', 'safe_transfers',
                          'cafe_items', 'cafe_categories', 'settings']
            for t in all_tables:
                cursor.execute(f"DROP TABLE IF EXISTS {t}")
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

            # Re-init fresh clean empty database (NO ITEMS, NO CATEGORIES - COMPLETELY BLANK)
            database.init_db(seed_items=False)

            # Force settings to default STARGATE and mark is_seeded = 1 so it never auto-populates on restart
            conn2 = get_db()
            conn2.execute("UPDATE settings SET company_name = 'STARGATE', exchange_rate = 89500.0, pc_price_per_click_lbp = 100000.0, is_seeded = 1 WHERE id = 1")
            conn2.commit()
            try:
                conn2.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            conn2.close()

            return True, "تم مسح وتصفير السيستم بالكامل 100%! تم حذف جميع المنتجات، الفواتير، ديون الزبائن، المصاريف، وسجل الخزنة ليصبح السيستم فارغاً ونظيفاً تماماً."
    except Exception as e:
        return False, f"فشل أثناء ضبط المصنع: {str(e)}"

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
    WHERE remaining_lbp > 0
    """)
    active_res = dict(cursor.fetchone() or {})
    
    # Distinct active debtors count
    cursor.execute("SELECT COUNT(DISTINCT customer_name) as customers_count FROM customer_debts WHERE remaining_lbp > 0")
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
    WHERE remaining_lbp > 0
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
    query = "SELECT * FROM customer_debts WHERE 1=1"
    params = []
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

def delete_debt(debt_id):
    """Delete / Cancel a debt record."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM customer_debts WHERE id = ?", (debt_id,))
    cursor.execute("DELETE FROM debt_payments WHERE debt_id = ?", (debt_id,))
    conn.commit()
    conn.close()
    return True

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
    """Ultra-fast inline edit for item price (LBP or USD), name, or stock quantity."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        settings = get_settings()
        rate = float(settings.get('exchange_rate') or 89500.0)
        if field == 'price_lbp':
            p_lbp = float(value or 0)
            p_usd = round(p_lbp / rate, 2) if rate > 0 else 0
            cursor.execute("UPDATE cafe_items SET price_lbp = ?, price_usd = ? WHERE id = ?", (p_lbp, p_usd, item_id))
        elif field == 'price_usd':
            p_usd = float(value or 0)
            p_lbp = round(p_usd * rate, -3) if rate > 0 else 0
            cursor.execute("UPDATE cafe_items SET price_lbp = ?, price_usd = ? WHERE id = ?", (p_lbp, p_usd, item_id))
        elif field == 'stock_qty':
            cursor.execute("UPDATE cafe_items SET stock_qty = ?, track_stock = 1 WHERE id = ?", (float(value or 0), item_id))
        elif field == 'name':
            cursor.execute("UPDATE cafe_items SET name = ? WHERE id = ?", (str(value).strip(), item_id))
        conn.commit()
        conn.close()
        return True, "تم التعديل الفوري بنجاح"
    except Exception as e:
        conn.close()
        return False, str(e)

def get_inventory_stock():
    """Retrieve all items with their stock information and category name."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        i.id,
        i.name,
        i.price_lbp,
        i.price_usd,
        i.icon,
        i.item_type,
        i.is_active,
        COALESCE(i.stock_qty, 0) as stock_qty,
        COALESCE(i.track_stock, 0) as track_stock,
        COALESCE(i.low_stock_limit, 5) as low_stock_limit,
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
    """Add new employee with username, password, pin and role."""
    name = (data.get('name') or '').strip()
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    pin = (data.get('pin') or '').strip()
    role = data.get('role', 'cashier').strip()
    phone = (data.get('phone') or '').strip()

    if not name or not username or not password:
        return False, "الاسم، اسم المستخدم، وكلمة المرور حقول مطلوبة"

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO employees (name, username, password, pin, role, phone, is_active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (name, username, password, pin, role, phone))
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
    """Update employee details and password."""
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
            cursor.execute("""
            UPDATE employees SET name=?, username=?, password=?, pin=?, role=?, phone=?, is_active=?
            WHERE id=?
            """, (name, username, password, pin, role, phone, is_active, emp_id))
        else:
            cursor.execute("""
            UPDATE employees SET name=?, username=?, pin=?, role=?, phone=?, is_active=?
            WHERE id=?
            """, (name, username, pin, role, phone, is_active, emp_id))
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
    """Authenticate employee by username+password or by quick PIN."""
    conn = get_db()
    cursor = conn.cursor()
    # Check by PIN
    if secret is None or secret == "":
        cursor.execute("SELECT * FROM employees WHERE pin = ? AND is_active = 1", (identifier,))
    else:
        cursor.execute("SELECT * FROM employees WHERE username = ? AND password = ? AND is_active = 1", (identifier, secret))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

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
    """نقل أو سحب مبلغ من/إلى الخزنة الخاصة مع التمييز الدقيق بين مصادر النقدية والوجهات."""
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
        conn.commit()
    except Exception:
        pass

    cursor.execute("""
        INSERT INTO safe_transfers (amount_lbp, amount_usd, note, transferred_by, operation_type, source, target, employee_id, employee_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (amount_lbp, amount_usd, note.strip(), transferred_by.strip(), op_type, source, target, employee_id, transferred_by.strip(), get_local_now()))
    conn.commit()
    transfer_id = cursor.lastrowid
    conn.close()
    return transfer_id


def get_safe_transfers(start_date=None, end_date=None, search_query=None, limit=500, target_date=None):
    """
    جلب سجل عمليات الخزنة مع البحث بالتواريخ (يوم محدد أو فترة من - إلى) والبحث النصي.
    """
    # Backward compatibility with target_date
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
    return rows


def get_safe_balance():
    """حساب الرصيد الإجمالي الحقيقي للخزنة (الإيداعات - المسحوبات)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_lbp END), 0) as total_deposit_lbp,
            COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_lbp ELSE 0 END), 0) as total_withdraw_lbp,
            COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN 0 ELSE amount_usd END), 0) as total_deposit_usd,
            COALESCE(SUM(CASE WHEN operation_type = 'withdraw' THEN amount_usd ELSE 0 END), 0) as total_withdraw_usd,
            COUNT(id) as transfers_count
        FROM safe_transfers
    """)
    row = dict(cursor.fetchone() or {})
    conn.close()

    dep_lbp = float(row.get('total_deposit_lbp') or 0.0)
    wth_lbp = float(row.get('total_withdraw_lbp') or 0.0)
    bal_lbp = dep_lbp - wth_lbp

    dep_usd = float(row.get('total_deposit_usd') or 0.0)
    wth_usd = float(row.get('total_withdraw_usd') or 0.0)
    bal_usd = dep_usd - wth_usd

    cnt = int(row.get('transfers_count') or 0)

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
    """ملخص حركة الخزنة لفترة محددة (اليوم أو نطاق زمني)."""
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
            WHERE DATE(datetime(created_at, '-5 hours')) >= DATE(?) AND DATE(datetime(created_at, '-5 hours')) <= DATE(?)
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
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
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
        'recommended_transfer_lbp': rem_to_transfer_lbp if rem_to_transfer_lbp > 0 else net_day_cash_lbp,
        'recommended_transfer_usd': rem_to_transfer_usd if rem_to_transfer_usd > 0 else net_day_cash_usd,
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

    # 1. تحديد المبلغ بالليرة
    amount_lbp = 0.0
    if custom_amount_lbp is not None and float(custom_amount_lbp) > 0:
        amount_lbp = float(custom_amount_lbp)
    elif status['recommended_transfer_lbp'] > 0:
        amount_lbp = float(status['recommended_transfer_lbp'])
    elif status['total_sales_lbp'] > 0:
        amount_lbp = float(status['total_sales_lbp'])
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
