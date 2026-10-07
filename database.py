# -*- coding: utf-8 -*-
"""
قاعدة بيانات STARGATE Cafe - النسخة الاحترافية v4.6.1
- Password hashing (werkzeug)
- Audit log table
- WAL + FK + busy_timeout
- Automatic migration
- No hardcoded credentials
"""

import sqlite3
import os
import sys
from werkzeug.security import generate_password_hash, check_password_hash

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
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
        user_appdata = os.path.join(
            os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
            'CafeGamingAccounting', 'data'
        )
        os.makedirs(user_appdata, exist_ok=True)
        return user_appdata


DB_DIR  = get_db_dir()
DB_PATH = os.path.join(DB_DIR, 'cafe_accounting.db')


# ──────────────────────────────────────────────
# Connection
# ──────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


# ──────────────────────────────────────────────
# Backup Helper (defined with full integrity & replication below)
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
# Password helpers
# ──────────────────────────────────────────────
def hash_password(plain: str) -> str:
    """Hash a plain-text password/PIN using werkzeug pbkdf2."""
    return generate_password_hash(plain)


def verify_password(plain: str, stored: str) -> bool:
    """
    Verify plain text against a stored hash OR plain-text legacy value.
    Supports transparent migration: if stored is not a hash, compare directly
    (only during the migration window), then upgrade automatically.
    """
    if not plain or not stored:
        return False
    # Modern hashed value
    if stored.startswith('pbkdf2:') or stored.startswith('scrypt:'):
        return check_password_hash(stored, plain)
    # Legacy plain-text (migration path) – still accept but caller must upgrade
    return plain.strip() == stored.strip()


def _needs_hash_upgrade(stored: str) -> bool:
    return bool(stored) and not stored.startswith('pbkdf2:') and not stored.startswith('scrypt:')


# ──────────────────────────────────────────────
# DB Init
# ──────────────────────────────────────────────
def init_db(seed_items=True):
    """Initialize database – create tables, run migrations, seed defaults."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()

    # ── Settings ──────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        company_name TEXT DEFAULT 'STARGATE',
        phone TEXT DEFAULT '',
        address TEXT DEFAULT '',
        receipt_footer_text TEXT DEFAULT '',
        currency TEXT DEFAULT 'ل.ل',
        secondary_currency TEXT DEFAULT '$',
        exchange_rate REAL DEFAULT 89500.0,
        pc_price_per_click_lbp REAL DEFAULT 100000.0,
        admin_password TEXT DEFAULT '',
        default_delivery_fee REAL DEFAULT 268500.0,
        default_driver_commission REAL DEFAULT 30000.0,
        default_return_fee REAL DEFAULT 89500.0,
        whatsapp_gateway_enabled INTEGER DEFAULT 0,
        whatsapp_provider TEXT DEFAULT 'ultramsg',
        whatsapp_instance_id TEXT DEFAULT '',
        whatsapp_token TEXT DEFAULT '',
        whatsapp_api_url TEXT DEFAULT 'https://api.ultramsg.com',
        is_seeded INTEGER DEFAULT 0,
        setup_complete INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Cafe Categories ────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cafe_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        icon TEXT DEFAULT '☕',
        sort_order INTEGER DEFAULT 0
    )
    """)

    # ── Cafe Items ─────────────────────────────
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
        stock_qty REAL DEFAULT 0,
        track_stock INTEGER DEFAULT 0,
        low_stock_limit REAL DEFAULT 5,
        image_path TEXT DEFAULT NULL,
        FOREIGN KEY (category_id) REFERENCES cafe_categories(id) ON DELETE CASCADE
    )
    """)

    # ── Cafe Orders ────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cafe_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        subtotal_lbp REAL DEFAULT 0.0,
        subtotal_usd REAL DEFAULT 0.0,
        discount_lbp REAL DEFAULT 0.0,
        discount_usd REAL DEFAULT 0.0,
        discount_percent REAL DEFAULT 0.0,
        discount_reason TEXT DEFAULT '',
        total_lbp REAL NOT NULL DEFAULT 0.0,
        total_usd REAL NOT NULL DEFAULT 0.0,
        paid_amount REAL NOT NULL DEFAULT 0.0,
        payment_method TEXT DEFAULT 'cash',
        customer_name TEXT DEFAULT 'زبون كاش',
        notes TEXT,
        status TEXT DEFAULT 'paid',
        is_tab INTEGER DEFAULT 0,
        employee_id INTEGER,
        employee_name TEXT DEFAULT 'كاشير',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Order Items ────────────────────────────
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

    # ── PC Usage Logs ──────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pc_usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        price_lbp REAL NOT NULL DEFAULT 100000.0,
        price_usd REAL NOT NULL DEFAULT 1.10,
        note TEXT DEFAULT 'استخدام كمبيوتر GAMING',
        employee_id INTEGER,
        employee_name TEXT DEFAULT 'كاشير',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Expenses ───────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        amount_lbp REAL NOT NULL DEFAULT 0.0,
        amount_usd REAL NOT NULL DEFAULT 0.0,
        category TEXT DEFAULT 'مصاريف عامة',
        notes TEXT,
        source TEXT DEFAULT 'drawer',
        employee_id INTEGER,
        employee_name TEXT DEFAULT 'كاشير',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Customer Debts ─────────────────────────
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

    # ── Debt Payments ──────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS debt_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        debt_id INTEGER NOT NULL,
        customer_name TEXT NOT NULL,
        amount_lbp REAL NOT NULL DEFAULT 0.0,
        amount_usd REAL NOT NULL DEFAULT 0.0,
        payment_method TEXT DEFAULT 'cash',
        notes TEXT DEFAULT '',
        employee_id INTEGER,
        employee_name TEXT DEFAULT 'كاشير',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (debt_id) REFERENCES customer_debts(id) ON DELETE CASCADE
    )
    """)

    # ── Safe Transfers ─────────────────────────
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

    # ── Employees ──────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        username TEXT UNIQUE,
        password TEXT NOT NULL,
        pin TEXT,
        role TEXT DEFAULT 'cashier',
        phone TEXT,
        is_active INTEGER DEFAULT 1,
        password_is_hashed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Audit Log ──────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        table_name TEXT,
        record_id INTEGER,
        old_value TEXT,
        new_value TEXT,
        reason TEXT,
        ip_address TEXT DEFAULT '127.0.0.1',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Inventory ──────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT DEFAULT 'عام',
        unit TEXT DEFAULT 'قطعة',
        stock_qty REAL DEFAULT 0.0,
        cost_per_unit REAL DEFAULT 0.0,
        low_stock_limit REAL DEFAULT 5.0,
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Financial Ledger (سجل الحركة المالية المركزي المزدوج) ─────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS financial_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_type TEXT NOT NULL,
        source TEXT NOT NULL,
        destination TEXT NOT NULL,
        reference_table TEXT,
        reference_id INTEGER,
        amount_lbp REAL NOT NULL DEFAULT 0.0,
        amount_usd REAL NOT NULL DEFAULT 0.0,
        exchange_rate REAL NOT NULL DEFAULT 89500.0,
        drawer_balance_before REAL DEFAULT 0.0,
        drawer_balance_after REAL DEFAULT 0.0,
        safe_balance_lbp_before REAL DEFAULT 0.0,
        safe_balance_lbp_after REAL DEFAULT 0.0,
        safe_balance_usd_before REAL DEFAULT 0.0,
        safe_balance_usd_after REAL DEFAULT 0.0,
        user_id INTEGER,
        user_name TEXT DEFAULT 'النظام',
        status TEXT DEFAULT 'active',
        cancelled_by TEXT,
        cancelled_at TIMESTAMP,
        cancel_reason TEXT,
        notes TEXT DEFAULT '',
        business_date TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Shift Closings (إغلاق ومطابقة الورديات اليومية) ─────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shift_closings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_date TEXT NOT NULL,
        shift_number INTEGER DEFAULT 1,
        employee_id INTEGER,
        employee_name TEXT NOT NULL,
        opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        closed_at TIMESTAMP,
        opening_float_lbp REAL DEFAULT 0.0,
        opening_float_usd REAL DEFAULT 0.0,
        cash_sales_lbp REAL DEFAULT 0.0,
        cash_sales_usd REAL DEFAULT 0.0,
        debt_sales_lbp REAL DEFAULT 0.0,
        debt_collected_lbp REAL DEFAULT 0.0,
        expenses_lbp REAL DEFAULT 0.0,
        safe_transfers_lbp REAL DEFAULT 0.0,
        expected_cash_lbp REAL DEFAULT 0.0,
        actual_cash_lbp REAL DEFAULT 0.0,
        difference_lbp REAL DEFAULT 0.0,
        difference_note TEXT DEFAULT '',
        orders_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'closed',
        handover_to_employee_id INTEGER,
        handover_to_employee_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Suppliers (الموردين وحساباتهم) ───────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        phone TEXT DEFAULT '',
        company TEXT DEFAULT '',
        balance_usd REAL DEFAULT 0.0,
        balance_lbp REAL DEFAULT 0.0,
        notes TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Purchase Invoices (فواتير المشتريات ومصروفات البضاعة) ────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS purchase_invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT UNIQUE,
        supplier_id INTEGER,
        supplier_name TEXT DEFAULT '',
        total_usd REAL DEFAULT 0.0,
        total_lbp REAL DEFAULT 0.0,
        paid_usd REAL DEFAULT 0.0,
        paid_lbp REAL DEFAULT 0.0,
        payment_source TEXT DEFAULT 'safe',
        status TEXT DEFAULT 'completed',
        cancelled_by TEXT,
        cancelled_at TIMESTAMP,
        cancel_reason TEXT,
        notes TEXT DEFAULT '',
        created_by TEXT DEFAULT 'المدير',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
    )
    """)

    # ── Purchase Invoice Items (عناصر فاتورة الشراء) ──────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS purchase_invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        inventory_id INTEGER,
        item_name TEXT NOT NULL,
        qty REAL NOT NULL DEFAULT 1.0,
        unit TEXT DEFAULT 'قطعة',
        cost_unit_usd REAL DEFAULT 0.0,
        cost_unit_lbp REAL DEFAULT 0.0,
        total_usd REAL DEFAULT 0.0,
        total_lbp REAL DEFAULT 0.0,
        FOREIGN KEY (invoice_id) REFERENCES purchase_invoices(id) ON DELETE CASCADE
    )
    """)

    # ── Supplier Payments (سداد دفعات الموردين النقدية ومن الخزنة) ───────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS supplier_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_id INTEGER NOT NULL,
        amount_usd REAL DEFAULT 0.0,
        amount_lbp REAL DEFAULT 0.0,
        payment_method TEXT DEFAULT 'safe',
        notes TEXT DEFAULT '',
        created_by TEXT DEFAULT 'المدير',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE
    )
    """)

    # ── Recipes (معادلات التصنيع واستهلاك المواد الخام للوجبات والقهوة) ─
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cafe_item_id INTEGER NOT NULL,
        inventory_id INTEGER NOT NULL,
        required_qty REAL NOT NULL DEFAULT 1.0,
        unit TEXT DEFAULT 'g',
        FOREIGN KEY (cafe_item_id) REFERENCES cafe_items(id) ON DELETE CASCADE,
        FOREIGN KEY (inventory_id) REFERENCES inventory(id) ON DELETE CASCADE
    )
    """)

    # ── Dining Tables (إدارة الطاولات وصالات الكافيه) ─────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dining_tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_number TEXT NOT NULL UNIQUE,
        table_name TEXT DEFAULT '',
        section TEXT DEFAULT 'الصالة الرئيسية',
        status TEXT DEFAULT 'available',
        current_order_id INTEGER,
        seats INTEGER DEFAULT 4,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Accounts / Chart of Accounts (شجرة الحسابات المحاسبية) ───────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        name_ar TEXT NOT NULL,
        account_type TEXT NOT NULL, -- asset, liability, equity, revenue, expense
        balance_lbp REAL DEFAULT 0.0,
        balance_usd REAL DEFAULT 0.0,
        description TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Journal Entries (قيود اليومية المزدوجة - Double Entry) ────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS journal_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_number TEXT UNIQUE NOT NULL,
        entry_date TEXT NOT NULL,
        description TEXT NOT NULL,
        reference_type TEXT,
        reference_id INTEGER,
        total_amount_lbp REAL NOT NULL DEFAULT 0.0,
        total_amount_usd REAL NOT NULL DEFAULT 0.0,
        user_name TEXT DEFAULT 'النظام',
        status TEXT DEFAULT 'posted', -- posted, void
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Journal Entry Lines (أطراف القيد المحاسبي مدين / دائن) ──────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS journal_entry_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        journal_entry_id INTEGER NOT NULL,
        account_code TEXT NOT NULL,
        account_name TEXT NOT NULL,
        debit_lbp REAL NOT NULL DEFAULT 0.0,
        credit_lbp REAL NOT NULL DEFAULT 0.0,
        debit_usd REAL NOT NULL DEFAULT 0.0,
        credit_usd REAL NOT NULL DEFAULT 0.0,
        memo TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE
    )
    """)

    # ── Stock Movements (سجل حركات المخزون والمواد الخام التفصيلي) ─────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        movement_type TEXT NOT NULL, -- PURCHASE_IN, SALE_OUT, WASTE, MANUAL_ADJUST, RECIPE_CONSUMPTION
        item_type TEXT DEFAULT 'inventory', -- 'inventory' (مواد خام) أو 'cafe_item' (منتجات بيع)
        item_id INTEGER NOT NULL,
        item_name TEXT NOT NULL,
        quantity REAL NOT NULL,
        qty_before REAL NOT NULL DEFAULT 0.0,
        qty_after REAL NOT NULL DEFAULT 0.0,
        unit_cost_lbp REAL DEFAULT 0.0,
        unit_cost_usd REAL DEFAULT 0.0,
        total_cost_lbp REAL DEFAULT 0.0,
        total_cost_usd REAL DEFAULT 0.0,
        reference_type TEXT, -- cafe_order, purchase_invoice, adjustment
        reference_id INTEGER,
        user_name TEXT DEFAULT 'النظام',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ── Coffee Bag Batches (سجل تتبع أكياس وكيلوات القهوة وحساب الفناجين) ─────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS coffee_bag_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_code TEXT UNIQUE NOT NULL,
        bag_weight_grams REAL DEFAULT 1000.0,
        cost_per_kg_lbp REAL NOT NULL DEFAULT 0.0,
        cost_per_kg_usd REAL NOT NULL DEFAULT 0.0,
        opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        opened_by TEXT DEFAULT 'كاشير',
        status TEXT DEFAULT 'active', -- 'active' (مفتوح حالياً), 'closed' (منتهي ومغلق)
        closed_at TIMESTAMP,
        closed_by TEXT,
        cups_sold INTEGER DEFAULT 0,
        cups_damaged INTEGER DEFAULT 0,
        total_cups INTEGER DEFAULT 0,
        cost_per_cup_lbp REAL DEFAULT 0.0,
        cost_per_cup_usd REAL DEFAULT 0.0,
        total_revenue_lbp REAL DEFAULT 0.0,
        total_revenue_usd REAL DEFAULT 0.0,
        net_profit_lbp REAL DEFAULT 0.0,
        net_profit_usd REAL DEFAULT 0.0,
        prev_batch_id INTEGER,
        prev_batch_code TEXT,
        prev_batch_cups INTEGER DEFAULT 0,
        expected_cups_yield REAL DEFAULT 0.0,
        initial_cup_cost_lbp REAL DEFAULT 0.0,
        initial_cup_cost_usd REAL DEFAULT 0.0,
        notes TEXT DEFAULT ''
    )
    """)

    # ── Coffee Waste Logs (سجل هدر وتوالف فناجين القهوة - تلف) ─────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS coffee_waste_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER,
        item_name TEXT DEFAULT 'فنجان قهوة',
        qty INTEGER DEFAULT 1,
        unit_cost_lbp REAL DEFAULT 0.0,
        unit_cost_usd REAL DEFAULT 0.0,
        loss_cost_lbp REAL DEFAULT 0.0,
        loss_cost_usd REAL DEFAULT 0.0,
        reason TEXT DEFAULT 'تلف أثناء التحضير',
        employee_name TEXT DEFAULT 'كاشير',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (batch_id) REFERENCES coffee_bag_batches(id) ON DELETE SET NULL
    )
    """)

    conn.commit()

    # ── Column Migrations (idempotent) ─────────
    _run_migrations(cursor, conn)

    # ── Indexes ────────────────────────────────
    _create_indexes(cursor)
    conn.commit()

    # ── Seed Chart of Accounts ─────────────────
    _seed_chart_of_accounts(cursor)
    conn.commit()

    # ── Seed Settings (first run only) ─────────
    cursor.execute("SELECT COUNT(*) as c FROM settings")
    if cursor.fetchone()['c'] == 0:
        # No default password – setup_complete = 0 forces setup wizard
        cursor.execute("""
            INSERT INTO settings (id, company_name, exchange_rate,
                                  pc_price_per_click_lbp, admin_password,
                                  is_seeded, setup_complete)
            VALUES (1, 'STARGATE', 89500.0, 100000.0, '', 0, 0)
        """)
        conn.commit()

    # ── Seed Menu (first run only) ─────────────
    cursor.execute("SELECT is_seeded FROM settings WHERE id = 1")
    row = cursor.fetchone()
    already_seeded = bool(row and row['is_seeded'] == 1)
    if seed_items and not already_seeded:
        seed_default_sample_menu(force=False)

    # ── Migrate plain-text passwords to hashes ─
    _migrate_passwords(cursor, conn)

    conn.commit()
    conn.close()


def _run_migrations(cursor, conn):
    """Add missing columns to existing databases (idempotent)."""
    migrations = [
        "ALTER TABLE cafe_items ADD COLUMN item_type TEXT DEFAULT 'cafe'",
        "ALTER TABLE cafe_order_items ADD COLUMN item_type TEXT DEFAULT 'cafe'",
        "ALTER TABLE cafe_orders ADD COLUMN status TEXT DEFAULT 'paid'",
        "ALTER TABLE cafe_orders ADD COLUMN is_tab INTEGER DEFAULT 0",
        "ALTER TABLE cafe_orders ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE cafe_orders ADD COLUMN employee_id INTEGER",
        "ALTER TABLE cafe_orders ADD COLUMN employee_name TEXT DEFAULT 'كاشير'",
        "ALTER TABLE settings ADD COLUMN pc_price_per_click_lbp REAL DEFAULT 100000.0",
        "ALTER TABLE settings ADD COLUMN admin_password TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN is_seeded INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN setup_complete INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN address TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN receipt_footer_text TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN default_delivery_fee REAL DEFAULT 268500.0",
        "ALTER TABLE settings ADD COLUMN default_driver_commission REAL DEFAULT 30000.0",
        "ALTER TABLE settings ADD COLUMN default_return_fee REAL DEFAULT 89500.0",
        "ALTER TABLE settings ADD COLUMN whatsapp_gateway_enabled INTEGER DEFAULT 0",
        "ALTER TABLE settings ADD COLUMN whatsapp_provider TEXT DEFAULT 'ultramsg'",
        "ALTER TABLE settings ADD COLUMN whatsapp_instance_id TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN whatsapp_token TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN whatsapp_api_url TEXT DEFAULT 'https://api.ultramsg.com'",
        "ALTER TABLE cafe_items ADD COLUMN stock_qty REAL DEFAULT 0",
        "ALTER TABLE cafe_items ADD COLUMN track_stock INTEGER DEFAULT 0",
        "ALTER TABLE cafe_items ADD COLUMN low_stock_limit REAL DEFAULT 5",
        "ALTER TABLE cafe_items ADD COLUMN image_path TEXT DEFAULT NULL",
        "ALTER TABLE expenses ADD COLUMN source TEXT DEFAULT 'drawer'",
        "ALTER TABLE expenses ADD COLUMN employee_id INTEGER",
        "ALTER TABLE expenses ADD COLUMN employee_name TEXT DEFAULT 'كاشير'",
        "ALTER TABLE safe_transfers ADD COLUMN source TEXT DEFAULT 'drawer'",
        "ALTER TABLE safe_transfers ADD COLUMN target TEXT DEFAULT 'safe'",
        "ALTER TABLE safe_transfers ADD COLUMN employee_id INTEGER",
        "ALTER TABLE safe_transfers ADD COLUMN employee_name TEXT DEFAULT 'المدير'",
        "ALTER TABLE debt_payments ADD COLUMN employee_id INTEGER",
        "ALTER TABLE debt_payments ADD COLUMN employee_name TEXT DEFAULT 'كاشير'",
        "ALTER TABLE employees ADD COLUMN password_is_hashed INTEGER DEFAULT 0",
        "ALTER TABLE pc_usage_logs ADD COLUMN employee_id INTEGER",
        "ALTER TABLE pc_usage_logs ADD COLUMN employee_name TEXT DEFAULT 'كاشير'",
        "ALTER TABLE safe_transfers ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE safe_transfers ADD COLUMN cancelled_by TEXT",
        "ALTER TABLE safe_transfers ADD COLUMN cancelled_at TIMESTAMP",
        "ALTER TABLE safe_transfers ADD COLUMN cancel_reason TEXT",
        "ALTER TABLE safe_transfers ADD COLUMN ledger_id INTEGER",
        "ALTER TABLE expenses ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE expenses ADD COLUMN cancelled_by TEXT",
        "ALTER TABLE expenses ADD COLUMN cancelled_at TIMESTAMP",
        "ALTER TABLE expenses ADD COLUMN cancel_reason TEXT",
        "ALTER TABLE expenses ADD COLUMN ledger_id INTEGER",
        "ALTER TABLE cafe_orders ADD COLUMN ledger_id INTEGER",
        "ALTER TABLE cafe_orders ADD COLUMN cancelled_by TEXT",
        "ALTER TABLE cafe_orders ADD COLUMN cancelled_at TIMESTAMP",
        "ALTER TABLE cafe_orders ADD COLUMN cancel_reason TEXT",
        "ALTER TABLE customer_debts ADD COLUMN cancelled_by TEXT",
        "ALTER TABLE customer_debts ADD COLUMN cancelled_at TIMESTAMP",
        "ALTER TABLE customer_debts ADD COLUMN cancel_reason TEXT",
        "ALTER TABLE cafe_orders ADD COLUMN dining_table_id INTEGER",
        "ALTER TABLE cafe_orders ADD COLUMN dining_table_name TEXT DEFAULT ''",
        "ALTER TABLE cafe_orders ADD COLUMN exchange_rate_used REAL DEFAULT 89500.0",
        "ALTER TABLE cafe_orders ADD COLUMN total_cost_lbp REAL DEFAULT 0.0",
        "ALTER TABLE cafe_orders ADD COLUMN total_cost_usd REAL DEFAULT 0.0",
        "ALTER TABLE cafe_items ADD COLUMN cost_price_lbp REAL DEFAULT 0.0",
        "ALTER TABLE cafe_items ADD COLUMN cost_price_usd REAL DEFAULT 0.0",
        "ALTER TABLE cafe_order_items ADD COLUMN unit_cost_lbp REAL DEFAULT 0.0",
        "ALTER TABLE cafe_order_items ADD COLUMN unit_cost_usd REAL DEFAULT 0.0",
        "ALTER TABLE shift_closings ADD COLUMN approved_by TEXT DEFAULT NULL",
        "ALTER TABLE shift_closings ADD COLUMN approved_at TIMESTAMP DEFAULT NULL",
        "ALTER TABLE shift_closings ADD COLUMN approval_status TEXT DEFAULT 'pending'",
        "ALTER TABLE shift_closings ADD COLUMN approval_notes TEXT DEFAULT ''",
        "ALTER TABLE cafe_items ADD COLUMN wholesale_price_lbp REAL DEFAULT 0.0",
        "ALTER TABLE cafe_items ADD COLUMN wholesale_price_usd REAL DEFAULT 0.0",
        "ALTER TABLE cafe_orders ADD COLUMN is_wholesale INTEGER DEFAULT 0",
        "ALTER TABLE cafe_order_items ADD COLUMN is_wholesale INTEGER DEFAULT 0",
        "ALTER TABLE cafe_items ADD COLUMN is_coffee_bean_linked INTEGER DEFAULT 0",
        "ALTER TABLE coffee_bag_batches ADD COLUMN prev_batch_id INTEGER",
        "ALTER TABLE coffee_bag_batches ADD COLUMN prev_batch_code TEXT",
        "ALTER TABLE coffee_bag_batches ADD COLUMN prev_batch_cups INTEGER DEFAULT 0",
        "ALTER TABLE coffee_bag_batches ADD COLUMN expected_cups_yield REAL DEFAULT 0.0",
        "ALTER TABLE coffee_bag_batches ADD COLUMN initial_cup_cost_lbp REAL DEFAULT 0.0",
        "ALTER TABLE coffee_bag_batches ADD COLUMN initial_cup_cost_usd REAL DEFAULT 0.0",
        "ALTER TABLE coffee_waste_logs ADD COLUMN unit_cost_lbp REAL DEFAULT 0.0",
        "ALTER TABLE coffee_waste_logs ADD COLUMN unit_cost_usd REAL DEFAULT 0.0",
        "ALTER TABLE cafe_order_items ADD COLUMN coffee_batch_id INTEGER DEFAULT NULL",
        "ALTER TABLE cafe_orders ADD COLUMN subtotal_lbp REAL DEFAULT 0.0",
        "ALTER TABLE cafe_orders ADD COLUMN subtotal_usd REAL DEFAULT 0.0",
        "ALTER TABLE cafe_orders ADD COLUMN discount_lbp REAL DEFAULT 0.0",
        "ALTER TABLE cafe_orders ADD COLUMN discount_usd REAL DEFAULT 0.0",
        "ALTER TABLE cafe_orders ADD COLUMN discount_percent REAL DEFAULT 0.0",
        "ALTER TABLE cafe_orders ADD COLUMN discount_reason TEXT DEFAULT ''",
    ]
    for sql in migrations:
        try:
            cursor.execute(sql)
        except Exception:
            pass
    conn.commit()


def _create_indexes(cursor):
    """Create performance indexes (idempotent)."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON cafe_orders(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_orders_status ON cafe_orders(status)",
        "CREATE INDEX IF NOT EXISTS idx_orders_is_tab ON cafe_orders(is_tab)",
        "CREATE INDEX IF NOT EXISTS idx_orders_employee_id ON cafe_orders(employee_id)",
        "CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON cafe_order_items(order_id)",
        "CREATE INDEX IF NOT EXISTS idx_order_items_item_id ON cafe_order_items(item_id)",
        "CREATE INDEX IF NOT EXISTS idx_items_category_id ON cafe_items(category_id)",
        "CREATE INDEX IF NOT EXISTS idx_items_is_active ON cafe_items(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_items_track_stock ON cafe_items(track_stock)",
        "CREATE INDEX IF NOT EXISTS idx_debts_status ON customer_debts(status)",
        "CREATE INDEX IF NOT EXISTS idx_debts_customer ON customer_debts(customer_name)",
        "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor)",
        "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)",
        "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_safe_transfers_created_at ON safe_transfers(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_expenses_created_at ON expenses(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_pc_usage_created_at ON pc_usage_logs(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_business_date ON financial_ledger(business_date)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_entry_type ON financial_ledger(entry_type)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_status ON financial_ledger(status)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_created ON financial_ledger(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_shift_closings_date ON shift_closings(business_date)",
        "CREATE INDEX IF NOT EXISTS idx_shift_closings_status ON shift_closings(status)",
        "CREATE INDEX IF NOT EXISTS idx_accounts_code ON accounts(code)",
        "CREATE INDEX IF NOT EXISTS idx_accounts_type ON accounts(account_type)",
        "CREATE INDEX IF NOT EXISTS idx_journal_entries_date ON journal_entries(entry_date)",
        "CREATE INDEX IF NOT EXISTS idx_journal_entry_lines_acc ON journal_entry_lines(account_code)",
        "CREATE INDEX IF NOT EXISTS idx_stock_movements_item ON stock_movements(item_id, item_type)",
        "CREATE INDEX IF NOT EXISTS idx_stock_movements_type ON stock_movements(movement_type)",
        "CREATE INDEX IF NOT EXISTS idx_stock_movements_created ON stock_movements(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_orders_status_created ON cafe_orders(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_order_items_order_item ON cafe_order_items(order_id, item_id)",
        "CREATE INDEX IF NOT EXISTS idx_debts_status_rem ON customer_debts(status, remaining_lbp)",
        "CREATE INDEX IF NOT EXISTS idx_debts_status_cust ON customer_debts(status, customer_name)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_status_date ON financial_ledger(status, business_date)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_source_dest ON financial_ledger(source, destination, status)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_ref ON financial_ledger(reference_table, reference_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_expenses_source_date ON expenses(source, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_stock_movements_ref ON stock_movements(reference_type, reference_id)",
        "CREATE INDEX IF NOT EXISTS idx_items_coffee_link ON cafe_items(is_coffee_bean_linked)",
    ]
    for sql in indexes:
        try:
            cursor.execute(sql)
        except Exception:
            pass


def _seed_chart_of_accounts(cursor):
    """Seed standard Chart of Accounts for Cafe & Gaming ERP."""
    default_accounts = [
        # Assets (الأصول)
        ('1010', 'Cash Drawer', 'صندوق الكاشير (الدرج)', 'asset', 'النقدية المتوفرة في درج الكاشير للعمليات اليومية'),
        ('1020', 'Safe Vault', 'الخزنة الخاصة (صندوق المالك)', 'asset', 'الخزنة المركزية لحفظ السيولة وإيداعات وسحوبات الإدارة'),
        ('1030', 'Accounts Receivable', 'حسابات الزبائن (المدينون - ديون)', 'asset', 'مستحقات وفواتير الزبائن الآجلة'),
        ('1040', 'Raw Materials Inventory', 'مخزون المواد الخام', 'asset', 'قيمة مخزون القهوة، الحليب، السكر، والنكهات'),
        ('1050', 'Finished Goods Inventory', 'مخزون منتجات البيع المباشر', 'asset', 'المشروبات الجاهزة، السناكس، والشيبس'),
        
        # Liabilities (الخصوم والالتزامات)
        ('2010', 'Accounts Payable (Suppliers)', 'حسابات الموردين (الدائنون)', 'liability', 'المبالغ المستحقة لشركات التوريد وفواتير الشراء الآجلة'),
        
        # Equity (حقوق الملكية)
        ('3010', 'Owner Equity & Retained Earnings', 'رأس المال والأرباح المبقاة', 'equity', 'حقوق ملكية الكافيه والمشروع'),
        
        # Revenues & Contra-Revenues (الإيرادات والخصومات)
        ('4010', 'Cafe & Beverage Sales Revenue', 'إيرادات مبيعات القهوة والمشروبات', 'revenue', 'مبيعات المنتجات الجاهزة والمصنعة'),
        ('4020', 'Gaming & Computer Revenue', 'إيرادات ألعاب GAMING والكمبيوتر', 'revenue', 'إيرادات ألعاب البلايستيشن والكمبيوتر (100% ربح)'),
        ('4030', 'Other Miscellaneous Revenue', 'إيرادات أخرى متنوعة', 'revenue', 'إيرادات المبيعات الحرة والخدمات'),
        ('4100', 'Sales Discounts & Hospitality', 'خصومات المبيعات والضيافة', 'expense', 'حسميات الأسعار للزبائن الدائمين، الضيافة، والفناجين المجانية'),
        
        # Expenses (المصروفات والتكاليف)
        ('5010', 'Cost of Goods Sold (COGS)', 'تكلفة البضاعة والمواد المستهلكة', 'expense', 'تكلفة المواد الخام المخصومة مع كل عملية بيع (Recipes & Inventory)'),
        ('5020', 'Operational Expenses', 'مصاريف تشغيلية ونثريات', 'expense', 'المصاريف العامة اليومية والكهرباء والإنترنت والضيافة'),
        ('5030', 'Staff Wages & Commissions', 'رواتب وعمولات الموظفين', 'expense', 'رواتب الكاشير والعمال'),
        ('5040', 'Spoilage & Waste Expense', 'تكلفة التالف والهدر', 'expense', 'هدر وتلف المواد الخام'),
    ]
    for code, name, name_ar, acc_type, desc in default_accounts:
        cursor.execute("""
            INSERT OR IGNORE INTO accounts (code, name, name_ar, account_type, description)
            VALUES (?, ?, ?, ?, ?)
        """, (code, name, name_ar, acc_type, desc))


def _migrate_passwords(cursor, conn):
    """
    One-time migration: convert plain-text employee passwords/PINs to hashes.
    Safe to call on every startup (skips already-hashed rows).
    """
    cursor.execute("SELECT id, password, pin, password_is_hashed FROM employees")
    rows = cursor.fetchall()
    for row in rows:
        if row['password_is_hashed'] == 1:
            continue  # already hashed
        emp_id = row['id']
        pwd = row['password'] or ''
        pin = row['pin'] or ''
        new_pwd = hash_password(pwd) if pwd else hash_password('changeme')
        new_pin = hash_password(pin) if pin else None
        cursor.execute(
            "UPDATE employees SET password=?, pin=?, password_is_hashed=1 WHERE id=?",
            (new_pwd, new_pin, emp_id)
        )
    conn.commit()

    # Migrate settings admin_password if it's plain text
    cursor.execute("SELECT admin_password FROM settings WHERE id=1")
    row = cursor.fetchone()
    if row:
        pwd = row['admin_password'] or ''
        if pwd and _needs_hash_upgrade(pwd):
            cursor.execute(
                "UPDATE settings SET admin_password=? WHERE id=1",
                (hash_password(pwd),)
            )
            conn.commit()


def _needs_hash_upgrade(stored: str) -> bool:
    return bool(stored) and not stored.startswith('pbkdf2:') and not stored.startswith('scrypt:')


# ──────────────────────────────────────────────
# Audit Log helper
# ──────────────────────────────────────────────
def write_audit_log(actor: str = None, action: str = None, table_name: str = None,
                    record_id: int = None, old_value: str = None,
                    new_value: str = None, reason: str = None, **kwargs):
    """Write structured audit entry to DB. Accepts both positional and keyword variants."""
    try:
        if not actor and 'username' in kwargs:
            actor = kwargs.get('username')
        if not actor and 'user_id' in kwargs:
            actor = f"user_{kwargs.get('user_id')}"
        if not actor:
            actor = 'system'

        if not reason and 'details' in kwargs:
            reason = kwargs.get('details')

        ip_address = kwargs.get('ip_address', '127.0.0.1')

        conn = get_db()
        conn.execute(
            """INSERT INTO audit_log
               (actor, action, table_name, record_id, old_value, new_value, reason, ip_address)
               VALUES (?,?,?,?,?,?,?,?)""",
            (actor, action or 'ACTION', table_name, record_id,
             str(old_value) if old_value is not None else None,
             str(new_value) if new_value is not None else None,
             reason, ip_address)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # audit must never crash the main operation


# ──────────────────────────────────────────────
# Seed
# ──────────────────────────────────────────────
def seed_default_sample_menu(force=False):
    """Seed default cafe categories and items – only on first run."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM cafe_categories")
    cat_count = cursor.fetchone()['count']
    if cat_count > 0 and not force:
        conn.close()
        return

    if force:
        cursor.execute("DELETE FROM cafe_items")
        cursor.execute("DELETE FROM cafe_categories")

    default_categories = [
        ('قهوة وإسبريسو', '☕', 1),
        ('مشروبات ساخنة', '🫖', 2),
        ('مشروبات باردة', '🧋', 3),
        ('مياه ومشروبات غازية', '💧', 4),
        ('تسالي وسناكات', '🍪', 5),
        ('GAMING والألعاب', '🎮', 6),
    ]
    cursor.executemany(
        "INSERT INTO cafe_categories (name, icon, sort_order) VALUES (?, ?, ?)",
        default_categories
    )
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
        (cat_map.get('مشروبات ساخنة'), 'هوت شوكليت', 150000.0, 1.70, '🍫', 'cafe', 3),
        (cat_map.get('مشروبات ساخنة'), 'سحلب ساخن مع مكسرات', 170000.0, 1.90, '🥛', 'cafe', 4),
        (cat_map.get('مشروبات باردة'), 'آيس كوفي / آيس لاتيه', 180000.0, 2.00, '🧋', 'cafe', 1),
        (cat_map.get('مشروبات باردة'), 'موهيتو ليمون ونعناع', 160000.0, 1.80, '🍋', 'cafe', 2),
        (cat_map.get('مشروبات باردة'), 'ميلك شيك شوكولاتة / فانيلا', 200000.0, 2.25, '🥤', 'cafe', 3),
        (cat_map.get('مشروبات باردة'), 'ريد بول / مشروب طاقة', 220000.0, 2.45, '⚡', 'cafe', 4),
        (cat_map.get('مياه ومشروبات غازية'), 'مياه معدنية صغيرة (0.5L)', 30000.0, 0.35, '💧', 'cafe', 1),
        (cat_map.get('مياه ومشروبات غازية'), 'مياه معدنية كبيرة (1.5L)', 60000.0, 0.70, '💧', 'cafe', 2),
        (cat_map.get('مياه ومشروبات غازية'), 'مشروب غازي (بيبسي / كولا)', 80000.0, 0.90, '🥤', 'cafe', 3),
        (cat_map.get('مياه ومشروبات غازية'), 'عصير معلب فريش', 70000.0, 0.80, '🧃', 'cafe', 4),
        (cat_map.get('تسالي وسناكات'), 'كوكيز / بسكويت', 70000.0, 0.80, '🍪', 'cafe', 1),
        (cat_map.get('تسالي وسناكات'), 'شيبس مشكل', 50000.0, 0.55, '🥔', 'cafe', 2),
        (cat_map.get('تسالي وسناكات'), 'كرواسون', 120000.0, 1.35, '🥐', 'cafe', 3),
    ]
    cursor.executemany(
        "INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, icon, item_type, sort_order) VALUES (?,?,?,?,?,?,?)",
        default_items
    )
    cursor.execute("UPDATE settings SET is_seeded=1 WHERE id=1")
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# Reset / Backup / Restore
# ──────────────────────────────────────────────
def reset_operational_data():
    """Reset daily transactions without touching menu or settings."""
    conn = get_db()
    try:
        conn.execute("BEGIN")
        for tbl in ['cafe_order_items', 'cafe_orders', 'pc_usage_logs',
                    'expenses', 'debt_payments', 'customer_debts', 'safe_transfers']:
            conn.execute(f"DELETE FROM {tbl}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True


def _prune_old_backups(directory: str, keep: int = 30):
    """Keep the latest N backups in a directory and safely delete older ones."""
    try:
        if not os.path.isdir(directory):
            return
        files = [
            os.path.join(directory, f) for f in os.listdir(directory)
            if f.endswith('.db') and ('cafe_accounting' in f or 'backup' in f)
        ]
        if len(files) > keep:
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            for old_file in files[keep:]:
                try:
                    os.remove(old_file)
                except Exception:
                    pass
    except Exception:
        pass


def create_backup_copy(backup_dir=None):
    """Create a consistent sqlite backup, verify integrity, replicate to safe locations, and return (path, filename)."""
    from datetime import datetime
    import shutil

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"cafe_accounting_backup_{timestamp}.db"
    
    # 1. Primary storage: data/backups
    primary_dir = backup_dir or os.path.join(DB_DIR, 'backups')
    os.makedirs(primary_dir, exist_ok=True)
    backup_path = os.path.join(primary_dir, backup_filename)

    source_conn = get_db()
    dest_conn = sqlite3.connect(backup_path)
    with dest_conn:
        source_conn.backup(dest_conn)
    dest_conn.close()
    source_conn.close()

    # 2. Integrity check
    check_conn = sqlite3.connect(backup_path)
    result = check_conn.execute("PRAGMA integrity_check").fetchone()[0]
    check_conn.close()
    if result != 'ok':
        try:
            os.remove(backup_path)
        except Exception:
            pass
        raise RuntimeError(f"Backup integrity check failed: {result}")

    # 3. Replicate to secondary safe locations (AppData and external drive F: if available)
    secondary_targets = [
        os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'STARGATE_Backups'),
        r"F:\STARGATE_CAFE_BACKUPS"
    ]
    for sec_dir in secondary_targets:
        try:
            if sec_dir.startswith("F:") and not os.path.exists(r"F:\\"):
                continue
            os.makedirs(sec_dir, exist_ok=True)
            sec_path = os.path.join(sec_dir, backup_filename)
            shutil.copy2(backup_path, sec_path)
            _prune_old_backups(sec_dir, keep=30)
        except Exception:
            pass

    _prune_old_backups(primary_dir, keep=30)
    return backup_path, backup_filename


def restore_from_backup(uploaded_file):
    """Safely restore database from uploaded backup file with rollback on failure."""
    from datetime import datetime
    import shutil

    temp_filename = f"restore_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    temp_path = os.path.join(DB_DIR, temp_filename)
    current_backup_path = os.path.join(DB_DIR, f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")

    if hasattr(uploaded_file, 'save'):
        uploaded_file.save(temp_path)
    elif isinstance(uploaded_file, str) and os.path.exists(uploaded_file):
        shutil.copy2(uploaded_file, temp_path)
    else:
        return False, "ملف النسخة الاحتياطية غير صالح أو غير موجود"

    # 1. Validate uploaded DB
    try:
        test_conn = sqlite3.connect(temp_path)
        ic = test_conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [r[0] for r in test_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        test_conn.close()

        if ic != 'ok':
            _safe_remove(temp_path)
            return False, f"الملف المرفوع تالف: {ic}"

        required = ['settings', 'cafe_orders']
        if not any(t in tables for t in required):
            _safe_remove(temp_path)
            return False, "الملف المحدد ليس نسخة احتياطية صالحة لهذا النظام."
    except Exception as e:
        _safe_remove(temp_path)
        return False, f"الملف المرفوع تالف أو غير صالح: {e}"

    # 2. Backup current DB before overwriting
    try:
        source_conn = get_db()
        dest_conn = sqlite3.connect(current_backup_path)
        with dest_conn:
            source_conn.backup(dest_conn)
        dest_conn.close()
        source_conn.close()
    except Exception as e:
        _safe_remove(temp_path)
        return False, f"فشل إنشاء نسخة احتياطية من البيانات الحالية قبل الاستعادة: {e}"

    # 3. Apply restore
    try:
        source_conn = sqlite3.connect(temp_path)
        target_conn = get_db()
        with target_conn:
            source_conn.backup(target_conn)
        source_conn.close()
        target_conn.close()

        _safe_remove(temp_path)

        # Run migrations to ensure schema is up to date
        init_db(seed_items=False)
        return True, "تمت استعادة النسخة الاحتياطية بنجاح! تم استرجاع كافة البيانات."
    except Exception as e:
        # Rollback
        try:
            rollback_conn = sqlite3.connect(current_backup_path)
            target_conn = get_db()
            with target_conn:
                rollback_conn.backup(target_conn)
            rollback_conn.close()
            target_conn.close()
        except Exception:
            pass
        _safe_remove(temp_path)
        return False, f"فشل أثناء استعادة البيانات (تم التراجع تلقائياً): {e}"


def _safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
