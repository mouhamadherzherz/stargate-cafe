# -*- coding: utf-8 -*-
"""
STARGATE CAFE — Database Migration v6.3.1
Adds:
- cafe_items: sku, barcode, unit, supplier_id, min_order_qty
- product_price_history: tracking price adjustments
- stocktaking_sessions & stocktaking_items: periodic physical inventory counting & variance tracking
- indexes for high-speed barcode, SKU, and date filtering
"""
import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

def run_migration(db_path=None):
    if not db_path:
        db_path = r"d:\STARGATE\organized_programs\cafe\data\cafe_accounting.db"
    
    print(f"=== Running STARGATE CAFE Database Migration v6.3.1 on: {db_path} ===")
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        return False
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Update cafe_items columns
    cursor.execute("PRAGMA table_info(cafe_items)")
    existing_cols = [c[1] for c in cursor.fetchall()]
    
    new_cols = [
        ("sku", "TEXT"),
        ("barcode", "TEXT"),
        ("unit", "TEXT DEFAULT 'قطعة'"),
        ("supplier_id", "INTEGER DEFAULT NULL"),
        ("min_order_qty", "REAL DEFAULT 1.0")
    ]
    
    for col_name, col_type in new_cols:
        if col_name not in existing_cols:
            print(f"  Adding column '{col_name}' to cafe_items...")
            cursor.execute(f"ALTER TABLE cafe_items ADD COLUMN {col_name} {col_type}")
    
    # Create index on barcode and sku
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cafe_items_barcode ON cafe_items(barcode)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cafe_items_sku ON cafe_items(sku)")

    # 2. Create product_price_history table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        item_name TEXT,
        old_price_lbp REAL,
        new_price_lbp REAL,
        old_price_usd REAL,
        new_price_usd REAL,
        changed_by TEXT,
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (item_id) REFERENCES cafe_items(id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_history_item ON product_price_history(item_id, created_at)")

    # 3. Create stocktaking_sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stocktaking_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_code TEXT UNIQUE NOT NULL,
        status TEXT DEFAULT 'draft', -- draft, completed, cancelled
        notes TEXT,
        conducted_by_id INTEGER,
        conducted_by_name TEXT,
        approved_by_id INTEGER,
        approved_by_name TEXT,
        total_items_counted INTEGER DEFAULT 0,
        total_discrepancy_items INTEGER DEFAULT 0,
        total_variance_cost_lbp REAL DEFAULT 0.0,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocktaking_sessions_code ON stocktaking_sessions(session_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocktaking_sessions_status ON stocktaking_sessions(status)")

    # 4. Create stocktaking_items table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stocktaking_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        item_type TEXT DEFAULT 'cafe_item', -- 'cafe_item' or 'inventory'
        item_id INTEGER NOT NULL,
        item_name TEXT NOT NULL,
        unit TEXT DEFAULT 'قطعة',
        theoretical_qty REAL NOT NULL,
        actual_counted_qty REAL NOT NULL,
        difference_qty REAL NOT NULL,
        unit_cost_lbp REAL DEFAULT 0.0,
        variance_cost_lbp REAL DEFAULT 0.0,
        difference_reason TEXT,
        adjusted INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES stocktaking_sessions(id) ON DELETE CASCADE
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocktaking_items_session ON stocktaking_items(session_id)")

    # 5. Add role check or permissions support in employees if needed
    cursor.execute("PRAGMA table_info(employees)")
    emp_cols = [c[1] for c in cursor.fetchall()]
    if "custom_permissions" not in emp_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN custom_permissions TEXT DEFAULT NULL")
        print("  Added 'custom_permissions' to employees.")

    # 6. Verify integrity
    integrity = cursor.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != 'ok':
        conn.rollback()
        conn.close()
        raise Exception(f"Integrity check failed: {integrity}")

    conn.commit()
    conn.close()
    print(f"=== Migration completed successfully! Integrity: {integrity} ===")
    return True

if __name__ == '__main__':
    run_migration()
