import sqlite3
import os
import sys

def get_db_dir():
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    
    local_data = os.path.join(app_dir, 'data')
    try:
        os.makedirs(local_data, exist_ok=True)
        test_file = os.path.join(local_data, '.write_test')
        with open(test_file, 'w') as f:
            f.write('ok')
        os.remove(test_file)
        return local_data
    except Exception:
        user_appdata = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'CafeGamingAccounting', 'data')
        os.makedirs(user_appdata, exist_ok=True)
        return user_appdata

DB_DIR = get_db_dir()
DB_PATH = os.path.join(DB_DIR, 'cafe_accounting.db')

def get_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn

def init_db(seed_items=True):
    """Initialize database for Cafe & Single Gaming PC & Others."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()

    # Settings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        company_name TEXT DEFAULT 'STARGATE',
        phone TEXT DEFAULT '',
        currency TEXT DEFAULT 'ل.ل',
        secondary_currency TEXT DEFAULT '$',
        exchange_rate REAL DEFAULT 89500.0,
        pc_price_per_click_lbp REAL DEFAULT 100000.0,
        admin_password TEXT DEFAULT '19701313',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Cafe Categories
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cafe_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        icon TEXT DEFAULT '☕',
        sort_order INTEGER DEFAULT 0
    )
    """)

    # Cafe Items (المنتجات المعروضة في الخارج)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cafe_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        price_lbp REAL NOT NULL DEFAULT 0.0,
        price_usd REAL NOT NULL DEFAULT 0.0,
        icon TEXT DEFAULT '☕',
        item_type TEXT DEFAULT 'cafe',
        sort_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY (category_id) REFERENCES cafe_categories(id) ON DELETE CASCADE
    )
    """)

    # Cafe Orders (الفواتير والمبيعات)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cafe_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        total_lbp REAL NOT NULL DEFAULT 0.0,
        total_usd REAL NOT NULL DEFAULT 0.0,
        paid_amount REAL NOT NULL DEFAULT 0.0,
        payment_method TEXT DEFAULT 'cash',
        customer_name TEXT DEFAULT 'زبون كاش',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Cafe Order Items (تفاصيل الفاتورة بما فيها القهوة، GAMING، و Others)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cafe_order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        item_id INTEGER,
        item_name TEXT NOT NULL,
        item_type TEXT DEFAULT 'cafe',
        quantity INTEGER NOT NULL DEFAULT 1,
        unit_price_lbp REAL NOT NULL DEFAULT 0.0,
        unit_price_usd REAL NOT NULL DEFAULT 0.0,
        subtotal_lbp REAL NOT NULL DEFAULT 0.0,
        subtotal_usd REAL NOT NULL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES cafe_orders(id) ON DELETE CASCADE
    )
    """)

    # Direct Single Gaming PC Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pc_usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        price_lbp REAL NOT NULL DEFAULT 100000.0,
        price_usd REAL NOT NULL DEFAULT 1.10,
        note TEXT DEFAULT 'استخدام كمبيوتر GAMING',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Expenses (المصاريف والمسحوبات)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        amount_lbp REAL NOT NULL DEFAULT 0.0,
        amount_usd REAL NOT NULL DEFAULT 0.0,
        category TEXT DEFAULT 'مصاريف عامة',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Customer Debts (سجل ديون الزبائن والآجل)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customer_debts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT NOT NULL,
        phone TEXT DEFAULT '',
        order_id INTEGER,
        order_number TEXT DEFAULT '',
        amount_lbp REAL NOT NULL DEFAULT 0.0,
        amount_usd REAL NOT NULL DEFAULT 0.0,
        paid_lbp REAL NOT NULL DEFAULT 0.0,
        paid_usd REAL NOT NULL DEFAULT 0.0,
        remaining_lbp REAL NOT NULL DEFAULT 0.0,
        remaining_usd REAL NOT NULL DEFAULT 0.0,
        status TEXT DEFAULT 'unpaid',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES cafe_orders(id) ON DELETE SET NULL
    )
    """)

    # Debt Repayments (سجل دفعات سداد الديون)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS debt_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        debt_id INTEGER NOT NULL,
        customer_name TEXT NOT NULL,
        amount_lbp REAL NOT NULL DEFAULT 0.0,
        amount_usd REAL NOT NULL DEFAULT 0.0,
        payment_method TEXT DEFAULT 'cash',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (debt_id) REFERENCES customer_debts(id) ON DELETE CASCADE
    )
    """)

    # Safe / Vault Transfer Records (خزنة المدير)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS safe_transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount_lbp REAL NOT NULL DEFAULT 0.0,
        amount_usd REAL NOT NULL DEFAULT 0.0,
        note TEXT DEFAULT '',
        transferred_by TEXT DEFAULT 'المدير',
            operation_type TEXT DEFAULT 'deposit',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Safe column migrations

    try:
        cursor.execute("ALTER TABLE cafe_items ADD COLUMN item_type TEXT DEFAULT 'cafe'")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE cafe_order_items ADD COLUMN item_type TEXT DEFAULT 'cafe'")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE cafe_orders ADD COLUMN status TEXT DEFAULT 'paid'")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE cafe_orders ADD COLUMN is_tab INTEGER DEFAULT 0")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE cafe_orders ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN pc_price_per_click_lbp REAL DEFAULT 100000.0")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN admin_password TEXT DEFAULT '19701313'")
    except Exception:
        pass

    # Employees Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        username TEXT UNIQUE,
        password TEXT NOT NULL,
        pin TEXT,
        role TEXT DEFAULT 'cashier',
        phone TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    try:
        cursor.execute("ALTER TABLE cafe_orders ADD COLUMN employee_id INTEGER")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE cafe_orders ADD COLUMN employee_name TEXT DEFAULT 'كاشير'")
    except Exception:
        pass

    # Ensure default employees exist if table is empty
    try:
        cursor.execute("SELECT COUNT(*) FROM employees")
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
                INSERT INTO employees (name, username, password, pin, role)
                VALUES ('المدير العام', 'admin', '19701313', '1313', 'admin'),
                       ('كاشير 1', 'cashier1', '1234', '1234', 'cashier')
            ''')
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE cafe_items ADD COLUMN stock_qty REAL DEFAULT 0")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE cafe_items ADD COLUMN track_stock INTEGER DEFAULT 0")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE cafe_items ADD COLUMN low_stock_limit REAL DEFAULT 5")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN is_seeded INTEGER DEFAULT 0")
    except Exception:
        pass

    # Ensure safe_transfers table exists (migration for existing DBs)
    try:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS safe_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount_lbp REAL NOT NULL DEFAULT 0.0,
            amount_usd REAL NOT NULL DEFAULT 0.0,
            note TEXT DEFAULT '',
            transferred_by TEXT DEFAULT 'المدير',
            operation_type TEXT DEFAULT 'deposit',
            source TEXT DEFAULT 'drawer',
            target TEXT DEFAULT 'safe',
            employee_id INTEGER,
            employee_name TEXT DEFAULT 'المدير',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    except Exception:
        pass

    # Financial Migrations
    for col_sql in [
        "ALTER TABLE expenses ADD COLUMN source TEXT DEFAULT 'drawer'",
        "ALTER TABLE expenses ADD COLUMN employee_id INTEGER",
        "ALTER TABLE expenses ADD COLUMN employee_name TEXT DEFAULT 'كاشير'",
        "ALTER TABLE safe_transfers ADD COLUMN source TEXT DEFAULT 'drawer'",
        "ALTER TABLE safe_transfers ADD COLUMN target TEXT DEFAULT 'safe'",
        "ALTER TABLE safe_transfers ADD COLUMN employee_id INTEGER",
        "ALTER TABLE safe_transfers ADD COLUMN employee_name TEXT DEFAULT 'المدير'",
        "ALTER TABLE debt_payments ADD COLUMN employee_id INTEGER",
        "ALTER TABLE debt_payments ADD COLUMN employee_name TEXT DEFAULT 'كاشير'",
    ]:
        try:
            cursor.execute(col_sql)
        except Exception:
            pass

    # Professional Performance Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON cafe_orders(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON cafe_orders(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_is_tab ON cafe_orders(is_tab)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_employee_id ON cafe_orders(employee_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON cafe_order_items(order_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_items_item_id ON cafe_order_items(item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_category_id ON cafe_items(category_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_is_active ON cafe_items(is_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_track_stock ON cafe_items(track_stock)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_debts_status ON customer_debts(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_debts_customer ON customer_debts(customer_name)")

    conn.commit()

    # Seed Default Settings
    cursor.execute("SELECT COUNT(*) as count FROM settings")
    if cursor.fetchone()['count'] == 0:
        cursor.execute("INSERT INTO settings (id, company_name, exchange_rate, pc_price_per_click_lbp, admin_password, is_seeded) VALUES (1, 'STARGATE', 89500.0, 100000.0, '19701313', 0)")
        conn.commit()

    # Check if system has already been seeded in the past
    cursor.execute("SELECT is_seeded FROM settings WHERE id = 1")
    row = cursor.fetchone()
    already_seeded = bool(row and row['is_seeded'] == 1)

    # Seed Cafe Categories & Items ONLY on the very first fresh database creation
    if seed_items and not already_seeded:
        seed_default_sample_menu(force=False)

    conn.commit()
    conn.close()

def seed_default_sample_menu(force=False):
    """Seed default cafe categories and items cleanly."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM cafe_categories")
    cat_count = cursor.fetchone()['count']
    if cat_count == 0 or force:
        if force:
            cursor.execute("DELETE FROM cafe_items")
            cursor.execute("DELETE FROM cafe_categories")

        default_categories = [
            ('قهوة وإسبريسو', '☕', 1),
            ('مشروبات ساخنة', '🫖', 2),
            ('مشروبات باردة', '🧋', 3),
            ('مياه ومشروبات غازية', '💧', 4),
            ('تسالي وسناكات', '🍪', 5),
            ('GAMING والألعاب', '🎮', 6)
        ]
        cursor.executemany("INSERT INTO cafe_categories (name, icon, sort_order) VALUES (?, ?, ?)", default_categories)
        conn.commit()

        cursor.execute("SELECT id, name FROM cafe_categories")
        cat_map = {row['name']: row['id'] for row in cursor.fetchall()}

        default_items = [
            (cat_map.get('GAMING والألعاب'), 'كمبيوتر ألعاب GAMING 🎮', 100000.0, 1.10, '🎮', 'gaming', 0),
            (cat_map.get('قهوة وإسبريسو'), 'قهوة تركية سادة / وسط', 80000.0, 0.90, '☕', 'cafe', 1),
            (cat_map.get('قهوة وإسبريسو'), 'قهوة تركية بالحليب', 100000.0, 1.10, '☕', 'cafe', 2),
            (cat_map.get('قهوة وإسبريسو'), 'إسبريسو سنغل (Single)', 90000.0, 1.00, '☕', 'cafe', 3),
            (cat_map.get('قهوة وإسبريسو'), 'إسبريسو دبل (Double)', 140000.0, 1.55, '☕', 'cafe', 4),
            (cat_map.get('قهوة وإسبريسو'), 'كابتشينو (Cappuccino)', 150000.0, 1.70, '☕', 'cafe', 5),
            (cat_map.get('قهوة وإسبريسو'), 'كافيه لاتيه (Latte)', 160000.0, 1.80, '☕', 'cafe', 6),
            (cat_map.get('قهوة وإسبريسو'), 'نسكافيه بلاك / مع حليب', 110000.0, 1.25, '☕', 'cafe', 7),
            (cat_map.get('مشروبات ساخنة'), 'شاي أحمر / بالنعناع', 60000.0, 0.70, '🫖', 'cafe', 1),
            (cat_map.get('مشروبات ساخنة'), 'شاي أخضر', 60000.0, 0.70, '🍵', 'cafe', 2),
            (cat_map.get('مشروبات ساخنة'), 'هوت شوكليت (Hot Chocolate)', 150000.0, 1.70, '🍫', 'cafe', 3),
            (cat_map.get('مشروبات ساخنة'), 'سحلب ساخن مع مكسرات', 170000.0, 1.90, '🥛', 'cafe', 4),
            (cat_map.get('مشروبات ساخنة'), 'زهورات وبابونج', 70000.0, 0.80, '🌿', 'cafe', 5),
            (cat_map.get('مشروبات باردة'), 'آيس كوفي / آيس لاتيه', 180000.0, 2.00, '🧋', 'cafe', 1),
            (cat_map.get('مشروبات باردة'), 'موهيتو ليمون ونعناع', 160000.0, 1.80, '🍋', 'cafe', 2),
            (cat_map.get('مشروبات باردة'), 'ميلك شيك شوكولاتة / فانيلا', 200000.0, 2.25, '🥤', 'cafe', 3),
            (cat_map.get('مشروبات باردة'), 'ريد بول / مشروب طاقة', 220000.0, 2.45, '⚡', 'cafe', 4),
            (cat_map.get('مياه ومشروبات غازية'), 'مياه معدنية صغيرة (0.5L)', 30000.0, 0.35, '💧', 'cafe', 1),
            (cat_map.get('مياه ومشروبات غازية'), 'مياه معدنية كبيرة (1.5L)', 60000.0, 0.70, '💧', 'cafe', 2),
            (cat_map.get('مياه ومشروبات غازية'), 'مشروب غازي (بيبسي / كولا / سفن)', 80000.0, 0.90, '🥤', 'cafe', 3),
            (cat_map.get('مياه ومشروبات غازية'), 'عصير معلب فريش', 70000.0, 0.80, '🧃', 'cafe', 4),
            (cat_map.get('تسالي وسناكات'), 'كوكيز / بسكويت', 70000.0, 0.80, '🍪', 'cafe', 1),
            (cat_map.get('تسالي وسناكات'), 'شيبس مشكل', 50000.0, 0.55, '🥔', 'cafe', 2),
            (cat_map.get('تسالي وسناكات'), 'كرواسون', 120000.0, 1.35, '🥐', 'cafe', 3),
        ]
        cursor.executemany("""
        INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, icon, item_type, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, default_items)

        # Mark system as seeded so it will never overwrite user deletions/changes on future launches
        cursor.execute("UPDATE settings SET is_seeded = 1 WHERE id = 1")
        conn.commit()

    conn.close()

def reset_operational_data():
    """Reset daily transactions without deleting menu items or settings."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cafe_order_items")
    cursor.execute("DELETE FROM cafe_orders")
    cursor.execute("DELETE FROM pc_usage_logs")
    cursor.execute("DELETE FROM expenses")
    cursor.execute("DELETE FROM debt_payments")
    cursor.execute("DELETE FROM customer_debts")
    
    # Professional Performance Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON cafe_orders(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON cafe_orders(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_is_tab ON cafe_orders(is_tab)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_employee_id ON cafe_orders(employee_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON cafe_order_items(order_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_items_item_id ON cafe_order_items(item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_debts_status ON customer_debts(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_debts_created_at ON customer_debts(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_debt_payments_debt_id ON debt_payments(debt_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_created_at ON expenses(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pc_usage_created_at ON pc_usage_logs(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_safe_transfers_created_at ON safe_transfers(created_at)")
    conn.commit()

    conn.close()
    return True

def create_backup_copy():
    """Create a consistent sqlite backup file and return its path and filename."""
    from datetime import datetime
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"cafe_accounting_backup_{timestamp}.db"
    backup_path = os.path.join(DB_DIR, backup_filename)

    source_conn = get_db()
    dest_conn = sqlite3.connect(backup_path)
    with dest_conn:
        source_conn.backup(dest_conn)
    dest_conn.close()
    source_conn.close()
    return backup_path, backup_filename

def restore_from_backup(uploaded_file):
    """Safely restore database from an uploaded backup file."""
    from datetime import datetime
    temp_filename = f"restore_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    temp_path = os.path.join(DB_DIR, temp_filename)
    uploaded_file.save(temp_path)

    # 1. Integrity check on uploaded database
    try:
        test_conn = sqlite3.connect(temp_path)
        cursor = test_conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        test_conn.close()

        required_tables = ['settings', 'cafe_orders']
        if not any(t in tables for t in required_tables):
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            return False, "الملف المحدد ليس نسخة احتياطية صالحة لهذا النظام."
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return False, f"الملف المرفوع تالف أو غير صالح: {str(e)}"

    # 2. Restore database safely using SQLite backup API
    try:
        source_conn = sqlite3.connect(temp_path)
        target_conn = get_db()
        with target_conn:
            source_conn.backup(target_conn)
        source_conn.close()
        target_conn.close()

        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

        # Run init_db to ensure any migration columns exist
        init_db()
        return True, "تمت استعادة النسخة الاحتياطية بنجاح! تم استرجاع كافة البيانات والمبيعات والمنيو."
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return False, f"فشل أثناء استعادة البيانات: {str(e)}"

