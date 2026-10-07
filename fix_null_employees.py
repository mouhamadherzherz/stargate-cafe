import sqlite3
import os

dbs = [
    r'C:\STARGATE_CAFE\data\cafe_accounting.db',
    r'd:\STARGATE\stargate_cafe_source\data\cafe_accounting.db'
]

for db_path in dbs:
    if not os.path.exists(db_path):
        continue
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        c.execute("SELECT id FROM employees WHERE role = 'cashier' AND name LIKE '%جواد%' LIMIT 1")
        jawad_row = c.fetchone()
        jawad_id = jawad_row[0] if jawad_row else 3

        c.execute("SELECT id FROM employees WHERE role = 'cashier' ORDER BY id ASC LIMIT 1")
        cashier_row = c.fetchone()
        cashier_id = cashier_row[0] if cashier_row else 4

        # Update orders where employee_name has 'جواد'
        c.execute("UPDATE cafe_orders SET employee_id = ? WHERE employee_id IS NULL AND employee_name LIKE '%جواد%'", (jawad_id,))
        # Update other NULL orders to cashier_id
        c.execute("UPDATE cafe_orders SET employee_id = ? WHERE employee_id IS NULL", (cashier_id,))
        
        # Also ensure debt_payments and expenses have employee_id filled
        c.execute("UPDATE debt_payments SET employee_id = ? WHERE employee_id IS NULL", (cashier_id,))
        c.execute("UPDATE expenses SET employee_id = ? WHERE employee_id IS NULL AND (source != 'safe' OR source IS NULL)", (cashier_id,))
        
        conn.commit()
        print(f"Fixed NULL employee_id in {db_path} successfully.")
        conn.close()
    except Exception as e:
        print(f"Error in {db_path}: {e}")
