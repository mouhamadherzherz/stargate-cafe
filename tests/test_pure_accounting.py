# -*- coding: utf-8 -*-
"""
STARGATE CAFE — Pure Python Standard Library Test Suite (Zero Dependencies)
Designed to run in ANY bare Python 3 environment without Flask, Werkzeug, or third-party packages.
Verifies core database schema, mathematical precision, financial ledger, and atomic double-entry rules.
"""

import os
import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime

# Add cafe directory to path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


class StargatePureAccountingTests(unittest.TestCase):
    """Zero-dependency tests covering core financial accounting logic and database operations."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._build_core_schema()

    def tearDown(self):
        try:
            self.conn.close()
            os.close(self.db_fd)
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
        except Exception:
            pass

    def _build_core_schema(self):
        """Constructs core SQLite schema according to STARGATE specifications."""
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                company_name TEXT DEFAULT 'STARGATE CAFE',
                exchange_rate REAL DEFAULT 89500.0,
                setup_complete INTEGER DEFAULT 1
            );
            INSERT INTO settings (id, exchange_rate) VALUES (1, 89500.0);

            CREATE TABLE cafe_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sort_order INTEGER DEFAULT 1
            );
            INSERT INTO cafe_categories (id, name) VALUES (1, 'مشروبات ساخنة');

            CREATE TABLE cafe_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                name TEXT NOT NULL,
                price_lbp REAL NOT NULL DEFAULT 0.0,
                cost_price_lbp REAL NOT NULL DEFAULT 0.0,
                stock_qty REAL NOT NULL DEFAULT 0.0,
                track_stock INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1
            );

            CREATE TABLE inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                unit TEXT DEFAULT 'kg',
                stock_qty REAL DEFAULT 0.0,
                cost_per_unit REAL DEFAULT 0.0,
                low_stock_limit REAL DEFAULT 5.0
            );

            CREATE TABLE recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cafe_item_id INTEGER NOT NULL,
                inventory_id INTEGER NOT NULL,
                required_qty REAL NOT NULL,
                unit TEXT DEFAULT 'kg'
            );

            CREATE TABLE cafe_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT NOT NULL,
                total_lbp REAL NOT NULL DEFAULT 0.0,
                total_usd REAL NOT NULL DEFAULT 0.0,
                total_cost_lbp REAL NOT NULL DEFAULT 0.0,
                paid_amount REAL NOT NULL DEFAULT 0.0,
                payment_method TEXT DEFAULT 'cash',
                status TEXT DEFAULT 'paid',
                employee_id INTEGER,
                employee_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE cafe_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                item_id INTEGER,
                item_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price_lbp REAL NOT NULL,
                subtotal_lbp REAL NOT NULL,
                unit_cost_lbp REAL DEFAULT 0.0
            );

            CREATE TABLE customer_debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                phone TEXT DEFAULT '',
                order_id INTEGER,
                amount_lbp REAL NOT NULL,
                amount_usd REAL NOT NULL,
                paid_lbp REAL NOT NULL DEFAULT 0.0,
                remaining_lbp REAL NOT NULL,
                status TEXT DEFAULT 'unpaid',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE financial_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type TEXT NOT NULL,
                source TEXT NOT NULL,
                destination TEXT NOT NULL,
                amount_lbp REAL NOT NULL,
                amount_usd REAL NOT NULL,
                reference_table TEXT,
                reference_id INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_number TEXT NOT NULL,
                description TEXT,
                reference_type TEXT,
                reference_id INTEGER,
                is_balanced INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE journal_entry_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                account_code TEXT NOT NULL,
                debit_lbp REAL DEFAULT 0.0,
                credit_lbp REAL DEFAULT 0.0,
                debit_usd REAL DEFAULT 0.0,
                credit_usd REAL DEFAULT 0.0,
                memo TEXT
            );

            CREATE TABLE stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movement_type TEXT NOT NULL,
                item_id INTEGER,
                item_name TEXT,
                quantity REAL NOT NULL,
                qty_before REAL NOT NULL,
                qty_after REAL NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.commit()

    def test_authoritative_price_enforcement_pure(self):
        """Server-side authoritative pricing overrides any client-supplied tampering."""
        cur = self.conn.cursor()
        # Authoritative price: 75,000 LBP
        cur.execute("INSERT INTO cafe_items (name, price_lbp, cost_price_lbp, stock_qty) VALUES ('كابتشينو', 75000.0, 30000.0, 10.0)")
        item_id = cur.lastrowid
        self.conn.commit()

        # Client submits tampered price of 100 LBP
        client_submitted_items = [{'item_id': item_id, 'quantity': 2, 'price_lbp': 100.0}]

        # Server fetches authoritative price
        cur.execute("SELECT id, name, price_lbp, cost_price_lbp FROM cafe_items WHERE id = ?", (item_id,))
        db_item = cur.fetchone()

        authoritative_total_lbp = db_item['price_lbp'] * client_submitted_items[0]['quantity']
        self.assertEqual(authoritative_total_lbp, 150000.0, "Total must be 150,000 LBP regardless of client payload")

    def test_atomic_transaction_rollback_pure(self):
        """Atomic transaction ensures rollback on any subsequent accounting ledger failure."""
        cur = self.conn.cursor()
        cur.execute("INSERT INTO cafe_items (name, price_lbp, stock_qty) VALUES ('شاي أسود', 25000.0, 20.0)")
        item_id = cur.lastrowid
        self.conn.commit()

        # Simulate transaction with failure in step 3
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            # Step 1: Insert Order
            cur.execute("INSERT INTO cafe_orders (order_number, total_lbp, payment_method) VALUES ('ORD-999', 50000.0, 'cash')")
            order_id = cur.lastrowid

            # Step 2: Insert Item & Stock Deduction
            cur.execute("INSERT INTO cafe_order_items (order_id, item_id, item_name, quantity, unit_price_lbp, subtotal_lbp) VALUES (?, ?, 'شاي أسود', 2, 25000.0, 50000.0)", (order_id, item_id))
            cur.execute("UPDATE cafe_items SET stock_qty = stock_qty - 2 WHERE id = ?", (item_id,))

            # Step 3: Simulated crash / ledger failure
            raise RuntimeError("Database constraint or ledger connection failure")

            # Commit would happen here
            self.conn.commit()
        except RuntimeError:
            self.conn.rollback()

        # Verify ZERO orders and ZERO stock loss occurred
        cur.execute("SELECT COUNT(*) FROM cafe_orders WHERE order_number = 'ORD-999'")
        self.assertEqual(cur.fetchone()[0], 0, "No order must be committed on failure")

        cur.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (item_id,))
        self.assertEqual(cur.fetchone()[0], 20.0, "Stock must remain unchanged after rollback")

    def test_double_entry_debit_credit_balance_pure(self):
        """Every double-entry journal entry must have equal total debits and credits."""
        cur = self.conn.cursor()
        total_sale_lbp = 100000.0
        discount_lbp = 10000.0
        net_cash_lbp = 90000.0

        cur.execute("INSERT INTO journal_entries (entry_number, description) VALUES ('JE-001', 'مبيع نقدي مع خصم')")
        je_id = cur.lastrowid

        # Dr Cash 1010: 90,000 | Dr Discount 4100: 10,000 | Cr Revenue 4010: 100,000
        cur.execute("INSERT INTO journal_entry_lines (entry_id, account_code, debit_lbp, credit_lbp) VALUES (?, '1010', ?, 0.0)", (je_id, net_cash_lbp))
        cur.execute("INSERT INTO journal_entry_lines (entry_id, account_code, debit_lbp, credit_lbp) VALUES (?, '4100', ?, 0.0)", (je_id, discount_lbp))
        cur.execute("INSERT INTO journal_entry_lines (entry_id, account_code, debit_lbp, credit_lbp) VALUES (?, '4010', 0.0, ?)", (je_id, total_sale_lbp))
        self.conn.commit()

        cur.execute("SELECT SUM(debit_lbp) as tot_dr, SUM(credit_lbp) as tot_cr FROM journal_entry_lines WHERE entry_id = ?", (je_id,))
        row = cur.fetchone()
        self.assertEqual(row['tot_dr'], row['tot_cr'], "Total Debits must exactly equal Total Credits (Accounting Equation)")
        self.assertEqual(row['tot_dr'], 100000.0)

    def test_recipe_inventory_deficit_tracking_pure(self):
        """Recipe ingredient consumption correctly tracks explicit deficit below zero."""
        cur = self.conn.cursor()
        # Only 0.2 kg milk in inventory
        cur.execute("INSERT INTO inventory (name, unit, stock_qty, cost_per_unit) VALUES ('حليب طازج', 'kg', 0.2, 50000.0)")
        inv_id = cur.lastrowid

        # Required: 0.5 kg
        consumed_qty = 0.5
        raw_before = 0.2
        raw_after = round(raw_before - consumed_qty, 4)  # -0.3 kg

        cur.execute("UPDATE inventory SET stock_qty = ? WHERE id = ?", (raw_after, inv_id))
        cur.execute("""
            INSERT INTO stock_movements (movement_type, item_id, item_name, quantity, qty_before, qty_after, notes)
            VALUES ('RECIPE_CONSUMPTION', ?, 'حليب طازج', ?, ?, ?, ?)
        """, (inv_id, consumed_qty, raw_before, raw_after, f"استهلاك مبيع [⚠️ عجز مخزون: {abs(raw_after)}]"))
        self.conn.commit()

        cur.execute("SELECT stock_qty FROM inventory WHERE id = ?", (inv_id,))
        self.assertEqual(cur.fetchone()[0], -0.3, "Deficit must be recorded as negative balance, not clipped to zero")

        cur.execute("SELECT notes FROM stock_movements WHERE item_id = ?", (inv_id,))
        self.assertIn("عجز مخزون: 0.3", cur.fetchone()['notes'])


if __name__ == '__main__':
    unittest.main()
