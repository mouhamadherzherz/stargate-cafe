import sqlite3
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect(r'C:\STARGATE_CAFE\data\cafe_accounting.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("Tables:", tables)

# Check employees table
emp_table = [t for t in tables if 'emp' in t.lower() or 'user' in t.lower()]
print("Emp tables:", emp_table)
for et in emp_table:
    c.execute(f"SELECT * FROM {et}")
    print(f"Data in {et}:", c.fetchall())

# Check recent orders
c.execute("SELECT id, order_number, total_lbp, payment_method, employee_id, employee_name, created_at FROM cafe_orders ORDER BY id DESC LIMIT 10")
print("Recent orders:")
for r in c.fetchall():
    print(r)

conn.close()
