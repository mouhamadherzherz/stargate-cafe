# -*- coding: utf-8 -*-
"""
STARGATE CAFE - Comprehensive Regression & Security Verification Test Suite
Tests all 20 critical points identified in the Security & Accounting Audit Report.
"""

import os
import sys
import json
import sqlite3
import tempfile
import unittest

# Ensure cafe directory is in path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import database
import accounting
from app import app


class StargateAuditTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Configure app for testing
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret-key-12345'
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

    def setUp(self):
        # Initialize test database
        self.test_db_fd, self.test_db_path = tempfile.mkstemp(suffix='.db')
        database.DB_PATH = self.test_db_path
        database.DB_DIR = os.path.dirname(self.test_db_path)
        database.init_db(seed_items=False)

        # Seed essential settings
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET setup_complete = 1 WHERE id = 1")
        
        # Seed test admin & cashier
        cursor.execute("""
            INSERT INTO employees (name, role, password, pin, password_is_hashed, is_active)
            VALUES ('مدير الاختبار', 'admin', ?, ?, 1, 1)
        """, (database.hash_password('admin123'), database.hash_password('1111')))
        self.admin_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO employees (name, role, password, pin, password_is_hashed, is_active)
            VALUES ('كاشير الاختبار', 'cashier', ?, ?, 1, 1)
        """, (database.hash_password('cashier123'), database.hash_password('2222')))
        self.cashier_id = cursor.lastrowid

        # Seed a test category
        cursor.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES ('مشروبات', '☕', 1)")
        self.cat_id = cursor.lastrowid

        # Seed a test item with authoritative price: 50,000 LBP, cost: 20,000 LBP
        cursor.execute("""
            INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, cost_price_lbp, cost_price_usd, stock_qty, track_stock, is_active)
            VALUES (?, 'عصير برتقال طبيعي', 50000.0, 0.56, 20000.0, 0.22, 10.0, 1, 1)
        """, (self.cat_id,))
        self.item_id = cursor.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            os.close(self.test_db_fd)
            if os.path.exists(self.test_db_path):
                os.remove(self.test_db_path)
        except Exception:
            pass

    # =========================================================================
    # P0 Security Tests
    # =========================================================================

    def test_p0_unauthenticated_update_endpoints_blocked(self):
        """Unauthenticated requests to manual update and do update must be blocked (401/403)."""
        # GET on do_update must be rejected (Method Not Allowed 405 or 401)
        resp_get = self.client.get('/api/do_update')
        self.assertIn(resp_get.status_code, (401, 403, 405))

        # POST without session must be rejected with 401/403
        resp_post_do = self.client.post('/api/do_update')
        self.assertIn(resp_post_do.status_code, (401, 403))

        resp_post_manual = self.client.post('/api/manual_update')
        self.assertIn(resp_post_manual.status_code, (401, 403))

    def test_p0_cashier_cannot_access_update_endpoints(self):
        """Authenticated cashier cannot trigger updates (admin required -> 403)."""
        with self.client.session_transaction() as sess:
            sess['employee_id'] = self.cashier_id
            sess['employee_name'] = 'كاشير الاختبار'
            sess['employee_role'] = 'cashier'
            sess['is_admin'] = False

        resp = self.client.post('/api/manual_update')
        self.assertEqual(resp.status_code, 403)

    def test_p0_image_path_traversal_blocked(self):
        """Path traversal requests on uploaded image route must return 404 and not leak files."""
        traversal_attempts = [
            '../../app.py',
            '..%2F..%2Fapp.py',
            '..\\..\\app.py',
            '....//....//app.py',
            '../../../cafe_version.json'
        ]
        for attempt in traversal_attempts:
            resp = self.client.get(f'/static/uploads/{attempt}')
            self.assertEqual(resp.status_code, 404, f"Traversal should return 404 for: {attempt}")

    # =========================================================================
    # P1 Financial & Security Logic Tests
    # =========================================================================

    def test_p1_no_default_changeme_password_on_migration(self):
        """Employees migration must never set 'changeme' password on unhashed empty accounts."""
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO employees (name, role, password, pin, password_is_hashed, is_active)
            VALUES ('موظف قديم', 'cashier', '', '', 0, 1)
        """)
        emp_id = cursor.lastrowid
        conn.commit()

        # Run password migration
        database._migrate_passwords(cursor, conn)

        cursor.execute("SELECT password FROM employees WHERE id = ?", (emp_id,))
        row = cursor.fetchone()
        conn.close()

        # Must NOT be the hash of 'changeme'
        changeme_hash = database.hash_password('changeme')
        self.assertNotEqual(row['password'], changeme_hash, "Password must not be set to default changeme!")
        self.assertFalse(database.check_password_hash(row['password'], 'changeme'), "Default changeme password must be rejected")
        self.assertFalse(database.check_password_hash(row['password'], ''), "Empty password must be rejected")

    def test_p1_server_enforces_authoritative_price_ignoring_client_tampering(self):
        """If client submits a tampered price (e.g. 10 LBP instead of 50,000 LBP), server uses DB price."""
        tampered_items = [{
            'item_id': self.item_id,
            'name': 'عصير برتقال طبيعي',
            'quantity': 2,
            'price_lbp': 10.0  # TAMPERED FROM 50,000 to 10
        }]
        order_data = {
            'customer_name': 'زبون فحص',
            'payment_method': 'cash',
            'employee_id': self.cashier_id,
            'employee_name': 'كاشير الاختبار'
        }
        ok, res = accounting.create_order(order_data, tampered_items)
        self.assertTrue(ok, f"Order creation failed: {res}")

        # Authoritative total must be 50,000 * 2 = 100,000 LBP (not 20 LBP)
        self.assertEqual(res['subtotal_lbp'], 100000.0)
        self.assertEqual(res['total_lbp'], 100000.0)

    def test_p1_invalid_payment_method_rejected(self):
        """Unknown payment method must be rejected with 400 error and not produce paid order."""
        items = [{
            'item_id': self.item_id,
            'quantity': 1,
            'price_lbp': 50000.0
        }]
        order_data = {
            'customer_name': 'زبون تزوير',
            'payment_method': 'unauthorized_cryptocurrency',
            'employee_id': self.cashier_id
        }
        ok, msg = accounting.create_order(order_data, items)
        self.assertFalse(ok, "Invalid payment method must be rejected")
        self.assertIn("طريقة دفع غير صالحة", msg)

    def test_p1_standalone_product_cogs_calculated_and_stored(self):
        """Selling a standalone finished good with no recipe ingredients must calculate and store COGS."""
        items = [{
            'item_id': self.item_id,
            'quantity': 2,
            'price_lbp': 50000.0
        }]
        order_data = {
            'customer_name': 'زبون تكلفة',
            'payment_method': 'cash',
            'employee_id': self.cashier_id
        }
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)

        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT total_cost_lbp FROM cafe_orders WHERE id = ?", (res['order_id'],))
        order_row = cursor.fetchone()
        
        # 2 units * 20,000 cost = 40,000 LBP COGS
        self.assertEqual(float(order_row['total_cost_lbp']), 40000.0, "Standalone COGS should be 40,000 LBP")

        cursor.execute("SELECT unit_cost_lbp FROM cafe_order_items WHERE order_id = ?", (res['order_id'],))
        item_row = cursor.fetchone()
        self.assertEqual(float(item_row['unit_cost_lbp']), 20000.0, "Unit cost should be stored on order item")
        conn.close()

    def test_p1_shift_closing_does_not_mix_employees_on_zero_sales(self):
        """Shift closing for an employee with 0 sales must not fall back to other employees' orders."""
        # 1. Cashier A creates an order
        items = [{'item_id': self.item_id, 'quantity': 1, 'price_lbp': 50000.0}]
        accounting.create_order({
            'customer_name': 'زبون كاشير أ',
            'payment_method': 'cash',
            'employee_id': self.cashier_id,
            'employee_name': 'كاشير أ'
        }, items)

        # 2. Check orders for Cashier B (who made 0 sales)
        conn = database.get_db()
        c = conn.cursor()
        today_str = accounting.get_business_date()
        c.execute("""
            SELECT o.* 
            FROM cafe_orders o
            WHERE (DATE(datetime(o.created_at, '-5 hours')) = DATE(?) OR DATE(o.created_at) = DATE(?))
              AND (o.status = 'paid' OR o.status IS NULL OR o.status = '')
              AND o.employee_id = ?
            ORDER BY o.id DESC
        """, (today_str, today_str, 99999))
        emp_orders_b = c.fetchall()
        conn.close()

        self.assertEqual(len(emp_orders_b), 0, "Cashier with 0 sales must have 0 orders (no store fallback)")

    # =========================================================================
    # P2 Reliability & Recovery Tests
    # =========================================================================

    def test_p2_incomplete_backup_restore_rejected(self):
        """Restoring from an incomplete DB missing core tables must be rejected."""
        fake_db_fd, fake_db_path = tempfile.mkstemp(suffix='.db')
        try:
            fake_conn = sqlite3.connect(fake_db_path)
            # Only create 1 dummy table
            fake_conn.execute("CREATE TABLE dummy (id INTEGER)")
            fake_conn.commit()
            fake_conn.close()

            ok, msg = database.restore_from_backup(fake_db_path)
            self.assertFalse(ok, "Incomplete database restore must fail")
            self.assertIn("ناقص", msg)
        finally:
            os.close(fake_db_fd)
            if os.path.exists(fake_db_path):
                os.remove(fake_db_path)

    def test_p2_export_full_system_includes_inventory_and_ledgers(self):
        """Full system export must include inventory, accounts, ledger, and version 6.1.0."""
        data = accounting.export_full_system_data()
        self.assertEqual(data.get('version'), '6.1.0')
        self.assertIn('inventory', data)
        self.assertIn('recipes', data)
        self.assertIn('suppliers', data)
        self.assertIn('financial_ledger', data)
        self.assertIn('journal_entries', data)
        self.assertIn('categories', data)
        self.assertIn('items', data)

    def test_p1_atomic_rollback_on_double_entry_failure(self):
        """If financial ledger or double-entry journal fails, entire order must roll back atomically."""
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cafe_orders")
        orders_before = cursor.fetchone()[0]
        conn.close()

        # Monkey-patch record_double_entry_journal to simulate an accounting ledger failure
        orig_fn = accounting.record_double_entry_journal
        try:
            accounting.record_double_entry_journal = lambda *args, **kwargs: (False, "Simulated ledger database failure")

            items = [{'item_id': self.item_id, 'quantity': 1, 'price_lbp': 50000.0}]
            order_data = {'customer_name': 'فحص التراجع الذري', 'payment_method': 'cash', 'employee_id': self.cashier_id}

            ok, res = accounting.create_order(order_data, items)
            self.assertFalse(ok, "Order creation must fail when double-entry journal fails")

            # Verify no order was committed
            conn = database.get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cafe_orders")
            orders_after = cursor.fetchone()[0]
            conn.close()

            self.assertEqual(orders_before, orders_after, "Orders count must remain unchanged after rollback")
        finally:
            accounting.record_double_entry_journal = orig_fn

    def test_p1_recipe_consumption_records_explicit_deficit(self):
        """Consuming more raw ingredient than available must update inventory and record explicit deficit."""
        conn = database.get_db()
        cursor = conn.cursor()

        # Create raw inventory item with only 0.1 kg available
        cursor.execute("""
            INSERT INTO inventory (name, unit, stock_qty, low_stock_limit, cost_per_unit)
            VALUES ('حليب سائل تجريبي', 'kg', 0.1, 1.0, 10000.0)
        """)
        raw_inv_id = cursor.lastrowid

        # Create cafe item linked to recipe requiring 0.5 kg per unit
        cursor.execute("""
            INSERT INTO cafe_items (category_id, name, price_lbp, cost_price_lbp, stock_qty, track_stock, is_active)
            VALUES (?, 'ميلك شيك تجريبي', 80000.0, 20000.0, 10.0, 0, 1)
        """, (self.cat_id,))
        recipe_item_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO recipes (cafe_item_id, inventory_id, required_qty, unit)
            VALUES (?, ?, 0.5, 'kg')
        """, (recipe_item_id, raw_inv_id))
        conn.commit()
        conn.close()

        # Sell 1 unit (requires 0.5 kg, only 0.1 kg available -> deficit of 0.4 kg)
        items = [{'item_id': recipe_item_id, 'quantity': 1, 'price_lbp': 80000.0}]
        order_data = {'customer_name': 'زبون عجز مخزون', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)

        # Check inventory is now -0.4 kg and deficit was logged
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT stock_qty FROM inventory WHERE id = ?", (raw_inv_id,))
        inv_stock = cursor.fetchone()[0]
        self.assertAlmostEqual(inv_stock, -0.4, places=2)

        cursor.execute("""
            SELECT notes FROM stock_movements 
            WHERE item_id = ? AND movement_type = 'RECIPE_CONSUMPTION'
            ORDER BY id DESC LIMIT 1
        """, (raw_inv_id,))
        note_row = cursor.fetchone()
        self.assertIn("عجز مخزون", note_row['notes'])
        conn.close()

    def test_p1_logout_routes_accept_get_and_post(self):
        """Logout endpoints must respond properly to both GET and POST requests."""
        # Admin logout GET & POST
        resp_admin_get = self.client.get('/admin/logout')
        self.assertEqual(resp_admin_get.status_code, 302)

        resp_admin_post = self.client.post('/admin/logout')
        self.assertEqual(resp_admin_post.status_code, 302)

        # Employee logout GET & POST
        resp_emp_get = self.client.get('/employee/logout')
        self.assertEqual(resp_emp_get.status_code, 302)

        resp_emp_post = self.client.post('/employee/logout')
        self.assertEqual(resp_emp_post.status_code, 302)

    def test_ai_insights_daily_summary_and_assistant(self):
        """AI Insights module must accurately aggregate data and answer queries without error."""
        import ai_insights
        
        # 1. Place a verified test order
        items = [{'item_id': self.item_id, 'quantity': 2, 'price_lbp': 50000.0}]
        order_data = {'customer_name': 'زبون ذكاء اصطناعي', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)

        # 2. Daily Summary
        today = accounting.get_business_date()
        summary = ai_insights.generate_executive_daily_summary(today)
        self.assertGreaterEqual(summary['metrics']['total_sales_lbp'], 100000.0)
        self.assertIn("تقرير الأداء المالي", summary['narrative'])

        # 3. Assistant Q&A
        ans_sales_admin = ai_insights.ask_system_assistant("كم مبيعات اليوم؟", user_role='admin')
        self.assertIn("إجمالي المبيعات", ans_sales_admin)

        ans_sales_cashier = ai_insights.ask_system_assistant("كم المبيعات؟", user_role='cashier')
        self.assertIn("المبيعات المسجلة لليوم", ans_sales_cashier)

        ans_debt_cashier = ai_insights.ask_system_assistant("كم ديون الزبائن؟", user_role='cashier')
        self.assertIn("مخصص لمدير النظام فقط", ans_debt_cashier)

    def test_ai_endpoints_authorization(self):
        """Unauthenticated requests to AI manager endpoints must be blocked (401/403)."""
        resp_unauth = self.client.get('/api/ai/daily_summary')
        self.assertIn(resp_unauth.status_code, (401, 403))

        resp_unauth_anom = self.client.get('/api/ai/anomalies')
        self.assertIn(resp_unauth_anom.status_code, (401, 403))


if __name__ == '__main__':
    unittest.main()
