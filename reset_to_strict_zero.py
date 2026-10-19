import database

conn = database.get_db()
cur = conn.cursor()

tables_to_clear = [
    'cafe_items',
    'cafe_categories',
    'coffee_bag_batches',
    'coffee_waste_logs',
    'recipes',
    'stock_movements',
    'cafe_orders',
    'cafe_order_items',
    'expenses',
    'customer_debts',
    'debt_payments',
    'safe_transfers',
    'employees',
    'pc_usage_logs',
    'shift_closings',
    'financial_ledger',
    'suppliers',
    'purchase_invoices',
    'purchase_invoice_items',
    'supplier_payments',
    'dining_tables',
    'journal_entries',
    'journal_entry_lines',
    'audit_log'
]

for tbl in tables_to_clear:
    try:
        cur.execute(f"DELETE FROM {tbl}")
    except Exception as e:
        pass

# Ensure settings is reset with setup_complete = 0 and is_seeded = 1 (so sample items are NEVER auto-injected)
cur.execute("DELETE FROM settings")
cur.execute("""
    INSERT INTO settings (id, company_name, exchange_rate, pc_price_per_click_lbp, admin_password, is_seeded, setup_complete)
    VALUES (1, 'STARGATE', 89500.0, 100000.0, '', 1, 0)
""")

conn.commit()

print("STATUS CHECK:")
for tbl in ['employees', 'cafe_items', 'cafe_categories', 'coffee_bag_batches', 'recipes', 'cafe_orders', 'financial_ledger']:
    c = cur.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
    print(f" - {tbl}: {c}")

s = cur.execute("SELECT setup_complete, is_seeded FROM settings WHERE id=1").fetchone()
print(f"Settings: setup_complete={s['setup_complete']}, is_seeded={s['is_seeded']}")

conn.close()
