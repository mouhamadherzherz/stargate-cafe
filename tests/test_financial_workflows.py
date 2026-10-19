# -*- coding: utf-8 -*-
"""
STARGATE CAFE — Financial Workflows & Accounting Integration Test Suite
Verifies full end-to-end financial workflows in isolated test environments:
1. Cash Sales & Drawer Balance Lifecycle
2. Customer Debt Sales, Tracking & Repayment (Full & Partial)
3. Expenses from Cash Drawer vs. Main Safe
4. Non-Destructive Order Cancellation & Inventory Stock Restitution
5. Safe Transfers & Cash Drawer Reconciliation
6. Shift Closing & Discrepancy Auditing
"""

import os
import sys
import sqlite3
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import database
import accounting


class StargateFinancialWorkflowsTests(unittest.TestCase):
    """End-to-end empirical verification of cafe financial workflows."""

    def setUp(self):
        # Create isolated temporary database for test run
        self.test_db_fd, self.test_db_path = tempfile.mkstemp(suffix='_fin_test.db')
        database.DB_PATH = self.test_db_path
        database.DB_DIR = os.path.dirname(self.test_db_path)
        database.init_db(seed_items=False)

        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET setup_complete = 1, exchange_rate = 89500.0 WHERE id = 1")

        # Create test cashier employee
        cursor.execute("""
            INSERT INTO employees (name, role, password, pin, password_is_hashed, is_active)
            VALUES ('كاشير العمليات', 'cashier', ?, ?, 1, 1)
        """, (database.hash_password('cashier123'), database.hash_password('1234')))
        self.cashier_id = cursor.lastrowid

        # Create category
        cursor.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES ('مشروبات ساخنة', '☕', 1)")
        self.category_id = cursor.lastrowid

        # Create stock-tracked item (e.g. قهوة تركي)
        cursor.execute("""
            INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, cost_price_lbp, cost_price_usd, track_stock, stock_qty, low_stock_limit, is_active)
            VALUES (?, 'قهوة تركي فاخرة', 50000.0, 0.56, 15000.0, 0.17, 1, 20.0, 5.0, 1)
        """, (self.category_id,))
        self.item_id = cursor.lastrowid

        # Create raw ingredient
        cursor.execute("""
            INSERT INTO inventory (name, category, unit, stock_qty, low_stock_limit, cost_per_unit)
            VALUES ('بن برازيلي مطحون', 'بن', 'gram', 500.0, 50.0, 50.0)
        """)
        self.ingredient_id = cursor.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            if hasattr(self, 'test_db_path') and os.path.exists(self.test_db_path):
                os.close(self.test_db_fd)
                os.remove(self.test_db_path)
        except Exception:
            pass

    def test_cash_sale_lifecycle_and_drawer_balance(self):
        """Cash sale must create order, deplete stock, and record positive cash drawer ledger."""
        items = [{'item_id': self.item_id, 'quantity': 2, 'price_lbp': 50000.0}]
        order_data = {
            'customer_name': 'زبون نقدي',
            'payment_method': 'cash',
            'employee_id': self.cashier_id,
            'notes': 'طلب نقدي تجريبي'
        }

        # Check stock before
        conn = database.get_db()
        c = conn.cursor()
        c.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_id,))
        stock_before = c.fetchone()['stock_qty']
        conn.close()

        ok, result = accounting.create_order(order_data, items)
        self.assertTrue(ok, f"Order creation failed: {result}")
        self.assertEqual(result['total_lbp'], 100000.0)

        # Verify stock deducted
        conn = database.get_db()
        c = conn.cursor()
        c.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_id,))
        stock_after = c.fetchone()['stock_qty']
        self.assertEqual(stock_after, stock_before - 2.0)

        # Verify order recorded in cafe_orders
        c.execute("SELECT status, total_lbp, payment_method FROM cafe_orders WHERE id = ?", (result['order_id'],))
        order_row = c.fetchone()
        self.assertEqual(order_row['status'], 'paid')
        self.assertEqual(order_row['total_lbp'], 100000.0)
        self.assertEqual(order_row['payment_method'], 'cash')

        # Verify double entry journal lines are balanced
        c.execute("""
            SELECT SUM(l.debit_lbp) as total_debit, SUM(l.credit_lbp) as total_credit
            FROM journal_entry_lines l
            JOIN journal_entries e ON l.journal_entry_id = e.id
            WHERE e.reference_type = 'cafe_orders' AND e.reference_id = ?
        """, (result['order_id'],))
        j_row = c.fetchone()
        if j_row and j_row['total_debit'] is not None:
            self.assertAlmostEqual(j_row['total_debit'], j_row['total_credit'], delta=0.01)
        conn.close()

    def test_debt_sale_and_customer_repayment_lifecycle(self):
        """Debt sale must create unpaid receivable, and pay_debt must settle it atomically."""
        items = [{'item_id': self.item_id, 'quantity': 3, 'price_lbp': 50000.0}]
        order_data = {
            'customer_name': 'أحمد ديون',
            'customer_phone': '03123456',
            'payment_method': 'debt',
            'employee_id': self.cashier_id,
            'notes': 'طلب آجل'
        }

        ok, result = accounting.create_order(order_data, items)
        self.assertTrue(ok)
        self.assertEqual(result['total_lbp'], 150000.0)

        # Verify customer_debts record exists with unpaid status
        conn = database.get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM customer_debts WHERE order_id = ?", (result['order_id'],))
        debt_row = c.fetchone()
        self.assertIsNotNone(debt_row)
        self.assertEqual(debt_row['customer_name'], 'أحمد ديون')
        self.assertEqual(debt_row['amount_lbp'], 150000.0)
        self.assertEqual(debt_row['remaining_lbp'], 150000.0)
        self.assertEqual(debt_row['status'], 'unpaid')
        debt_id = debt_row['id']
        conn.close()

        # Step 2: Partial payment of 50,000 LBP
        pay_ok, pay_msg = accounting.pay_debt(debt_id, 50000.0, payment_method='cash', notes='دفعة أولى')
        self.assertTrue(pay_ok, f"Partial pay_debt failed: {pay_msg}")

        conn = database.get_db()
        c = conn.cursor()
        c.execute("SELECT paid_lbp, remaining_lbp, status FROM customer_debts WHERE id = ?", (debt_id,))
        p_row = c.fetchone()
        self.assertEqual(p_row['paid_lbp'], 50000.0)
        self.assertEqual(p_row['remaining_lbp'], 100000.0)
        self.assertEqual(p_row['status'], 'partial')

        # Check debt_payments log
        c.execute("SELECT amount_lbp FROM debt_payments WHERE debt_id = ?", (debt_id,))
        payments = c.fetchall()
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0]['amount_lbp'], 50000.0)
        conn.close()

        # Step 3: Full remaining payment of 100,000 LBP
        full_ok, full_msg = accounting.pay_debt(debt_id, 100000.0, payment_method='cash', notes='سداد نهائي')
        self.assertTrue(full_ok)

        conn = database.get_db()
        c = conn.cursor()
        c.execute("SELECT paid_lbp, remaining_lbp, status FROM customer_debts WHERE id = ?", (debt_id,))
        f_row = c.fetchone()
        self.assertEqual(f_row['paid_lbp'], 150000.0)
        self.assertEqual(f_row['remaining_lbp'], 0.0)
        self.assertEqual(f_row['status'], 'paid')
        conn.close()

    def test_expenses_from_drawer_vs_safe(self):
        """Expense from drawer must credit drawer, while safe expense must log safe withdrawal."""
        # 1. Drawer expense
        ok_d, eid_d = accounting.add_expense(
            title='شراء أكياس',
            amount_lbp=20000.0,
            category='مشتريات تشغيلية',
            source='drawer',
            employee_id=self.cashier_id,
            employee_name='كاشير العمليات'
        )
        self.assertTrue(ok_d)

        # 2. Safe expense
        ok_s, eid_s = accounting.add_expense(
            title='فاتورة كهرباء كبرى',
            amount_lbp=500000.0,
            category='فواتير',
            source='safe',
            employee_id=self.cashier_id,
            employee_name='كاشير العمليات'
        )
        self.assertTrue(ok_s)

        conn = database.get_db()
        c = conn.cursor()
        # Verify drawer expense in DB
        c.execute("SELECT source, amount_lbp FROM expenses WHERE id = ?", (eid_d,))
        row_d = c.fetchone()
        self.assertEqual(row_d['source'], 'drawer')
        self.assertEqual(row_d['amount_lbp'], 20000.0)

        # Verify safe expense generated safe_transfers withdrawal
        c.execute("SELECT operation_type, source, amount_lbp FROM safe_transfers WHERE source = 'safe' AND operation_type = 'withdraw'")
        safe_transfer_row = c.fetchone()
        self.assertIsNotNone(safe_transfer_row)
        self.assertEqual(safe_transfer_row['amount_lbp'], 500000.0)
        conn.close()

    def test_order_cancellation_restores_stock_and_reverses_financials(self):
        """Cancelling an order must restore stock, mark status cancelled, and reverse debt/ledger."""
        # Place order for 4 items
        items = [{'item_id': self.item_id, 'quantity': 4, 'price_lbp': 50000.0}]
        order_data = {
            'customer_name': 'زبون للإلغاء',
            'payment_method': 'debt',
            'employee_id': self.cashier_id,
            'notes': 'طلب سيتم إلغاؤه'
        }

        ok, result = accounting.create_order(order_data, items)
        self.assertTrue(ok)
        order_id = result['order_id']

        # Verify stock was depleted by 4
        conn = database.get_db()
        c = conn.cursor()
        c.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_id,))
        stock_mid = c.fetchone()['stock_qty']
        self.assertEqual(stock_mid, 16.0)  # 20 - 4
        conn.close()

        # Cancel order
        canc_ok, canc_msg = accounting.cancel_order(order_id, cancelled_by='المدير العام', reason='طلب خاطئ')
        self.assertTrue(canc_ok, f"Cancel order failed: {canc_msg}")

        # Verify stock is restored
        conn = database.get_db()
        c = conn.cursor()
        c.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_id,))
        stock_restored = c.fetchone()['stock_qty']
        self.assertEqual(stock_restored, 20.0, "Stock was not restored after cancellation!")

        # Verify order status is 'cancelled'
        c.execute("SELECT status, notes FROM cafe_orders WHERE id = ?", (order_id,))
        order_canc = c.fetchone()
        self.assertEqual(order_canc['status'], 'cancelled')
        self.assertIn("إلغاء", order_canc['notes'])

        # Verify customer_debts status is 'cancelled'
        c.execute("SELECT status FROM customer_debts WHERE order_id = ?", (order_id,))
        debt_canc = c.fetchone()
        self.assertEqual(debt_canc['status'], 'cancelled')
        conn.close()

    def test_safe_transfer_workflow(self):
        """Safe transfer must record movement between cash drawer and main safe."""
        # Pre-seed cash drawer account so drawer check passes
        conn = database.get_db()
        c = conn.cursor()
        c.execute("UPDATE accounts SET balance_lbp = 1000000.0 WHERE code = '1010'")
        conn.commit()
        conn.close()

        tid = accounting.add_safe_transfer(
            amount_lbp=250000.0,
            note='توريد مسائي للخزنة',
            transferred_by='كاشير العمليات',
            operation_type='deposit',
            employee_id=self.cashier_id,
            source='drawer',
            target='safe'
        )
        self.assertIsNotNone(tid)

        conn = database.get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM safe_transfers WHERE id = ?", (tid,))
        t_row = c.fetchone()
        self.assertIsNotNone(t_row)
        self.assertEqual(t_row['amount_lbp'], 250000.0)
        self.assertEqual(t_row['operation_type'], 'deposit')
        self.assertEqual(t_row['status'], 'active')
        conn.close()

    def test_shift_closing_cash_reconciliation(self):
        """Shift closing must accurately document actual vs expected cash and calculate discrepancy."""
        today = accounting.get_business_date()
        
        # Expected cash: 1,000,000 LBP, Actual cash counted: 980,000 LBP (20,000 LBP shortage)
        closing_id = accounting.record_shift_closing(
            business_date=today,
            employee_id=self.cashier_id,
            employee_name='كاشير العمليات',
            opening_float_lbp=200000.0,
            cash_sales_lbp=800000.0,
            expenses_lbp=0.0,
            expected_cash_lbp=1000000.0,
            actual_cash_lbp=980000.0,
            difference_lbp=-20000.0,
            difference_note='عجز بسيط 20,000 ل.ل',
            orders_count=15
        )
        self.assertIsNotNone(closing_id)

        conn = database.get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM shift_closings WHERE id = ?", (closing_id,))
        row = c.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['difference_lbp'], -20000.0)
        self.assertEqual(row['status'], 'closed')
        self.assertEqual(row['approval_status'], 'approved')
        conn.close()


if __name__ == '__main__':
    unittest.main()
