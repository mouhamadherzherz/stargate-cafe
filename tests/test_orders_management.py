# -*- coding: utf-8 -*-
"""
STARGATE CAFE - Comprehensive Next-Gen POS & Orders Management Test Suite
Empirical validation of the 17 core requirements:
1. Order creation from Cashier POS
2. Instant appearance in orders management hub
3. Products and quantities detail verification
4. Subtotal, discount, and totals accuracy
5. KPI summary calculation without duplication
6. Multi-criteria filtering (status, period, order_type) and search
7. JSON API endpoint for order details modal
8. Status progression flow (new -> preparing -> ready -> completed)
9. Rejection of invalid status transitions
10. API endpoint for status change with CSRF handling
11. Safe non-destructive cancellation and automatic stock return
12. Protection against modifying cancelled orders
13. Live Polling API endpoint (/api/orders/list)
14. Full HTML rendering of Cards, Table, and Kanban views
15. Thermal 80mm & A4 Formal reprint without financial duplication
16. Authentication and access control protection
"""

import unittest
import os
import sys
import tempfile
import secrets
import json

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import database
import accounting
from app import app


class TestOrdersManagementSuite(unittest.TestCase):

    def setUp(self):
        self.test_db_fd, self.test_db_path = tempfile.mkstemp(suffix='_orders_mgmt.db')
        database.DB_PATH = self.test_db_path
        database.DB_DIR = os.path.dirname(self.test_db_path)
        accounting.DB_PATH = self.test_db_path

        database.init_db(seed_items=False)

        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET setup_complete = 1, exchange_rate = 89500.0, company_name = 'STARGATE CAFE' WHERE id = 1")

        # Create Admin employee (required for setup_complete verification)
        cursor.execute("""
            INSERT INTO employees (name, role, password, pin, password_is_hashed, is_active)
            VALUES ('المدير العام', 'admin', ?, ?, 1, 1)
        """, (database.hash_password('admin123'), database.hash_password('1111')))
        self.admin_id = cursor.lastrowid

        # Create Cashier employee
        cursor.execute("""
            INSERT INTO employees (name, role, password, pin, password_is_hashed, is_active)
            VALUES ('كاشير الطلبات', 'cashier', ?, ?, 1, 1)
        """, (database.hash_password('cashier123'), database.hash_password('2222')))
        self.cashier_id = cursor.lastrowid

        # Create categories
        cursor.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES ('مشروبات ساخنة', '☕', 1)")
        self.cat_id = cursor.lastrowid

        # Create items with stock
        cursor.execute("""
            INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, cost_price_lbp, cost_price_usd, track_stock, stock_qty, low_stock_limit, is_active)
            VALUES (?, 'اسبريسو سنجل فاخر', 90000.0, 1.0, 30000.0, 0.33, 1, 50.0, 5.0, 1)
        """, (self.cat_id,))
        self.item_id = cursor.lastrowid

        conn.commit()
        conn.close()

        app.config['TESTING'] = True
        self.client = app.test_client()

    def tearDown(self):
        try:
            os.close(self.test_db_fd)
            if os.path.exists(self.test_db_path):
                os.remove(self.test_db_path)
        except Exception:
            pass

    def _login(self, role='cashier'):
        with self.client.session_transaction() as sess:
            sess['employee_id'] = self.cashier_id
            sess['employee_name'] = 'كاشير الطلبات'
            sess['employee_role'] = role
            sess['is_admin'] = (role == 'admin')
            sess['_csrf_token'] = secrets.token_hex(24)

    def _post_csrf(self, url, json_data):
        token = secrets.token_hex(24)
        with self.client.session_transaction() as sess:
            sess['employee_id'] = self.cashier_id
            sess['employee_name'] = 'كاشير الطلبات'
            sess['employee_role'] = 'cashier'
            sess['_csrf_token'] = token

        return self.client.post(
            url,
            data=json.dumps(json_data),
            content_type='application/json',
            headers={'X-CSRFToken': token, 'Origin': 'http://localhost'}
        )

    def test_01_order_creation_from_cashier(self):
        """1. Create a new cafe order from cashier POS and verify creation."""
        order_data = {
            'customer_name': 'عميل فحص الطلبات',
            'notes': 'طاولة VIP رقم 5',
            'payment_method': 'cash',
            'order_type': 'dine_in',
            'table_number': '5',
            'employee_id': self.cashier_id,
            'employee_name': 'كاشير الطلبات',
            'discount_percent': 0.0,
            'discount_lbp': 0.0,
            'discount_usd': 0.0
        }
        items = [
            {'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 2, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 180000.0, 'subtotal_usd': 2.0}
        ]
        success, res = accounting.create_order(order_data, items)
        self.assertTrue(success, f"Failed to create order: {res}")
        self.assertIn('order_id', res)
        self.assertIn('order_number', res)

    def test_02_order_appearance_in_orders_list(self):
        """2. Verify that the created order immediately appears in orders list."""
        order_data = {'customer_name': 'عميل 2', 'payment_method': 'cash', 'order_type': 'takeaway', 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 1, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 90000.0, 'subtotal_usd': 1.0}]
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)
        oid = res['order_id']

        orders = accounting.get_orders(include_all_statuses=True, limit=10)
        ord_ids = [o['id'] for o in orders]
        self.assertIn(oid, ord_ids, "Created order should be present in orders list")

    def test_03_order_items_and_quantities_details(self):
        """3. Verify correct item details, quantities, and summary."""
        order_data = {'customer_name': 'عميل 3', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 3, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 270000.0, 'subtotal_usd': 3.0}]
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)
        oid = res['order_id']

        details = accounting.get_order_details(oid)
        self.assertIsNotNone(details)
        self.assertEqual(len(details['items']), 1)
        self.assertEqual(details['items'][0]['quantity'], 3)
        self.assertEqual(details['items'][0]['item_name'], 'اسبريسو سنجل فاخر')

    def test_04_totals_correctness_and_discounts(self):
        """4. Verify subtotal, discounts, and final totals in LBP and USD."""
        order_data = {'customer_name': 'عميل 4', 'payment_method': 'cash', 'discount_lbp': 20000.0, 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 2, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 180000.0, 'subtotal_usd': 2.0}]
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)
        oid = res['order_id']

        details = accounting.get_order_details(oid)
        self.assertEqual(float(details['total_lbp']), 160000.0)
        self.assertEqual(float(details['discount_lbp']), 20000.0)

    def test_05_kpi_summary_accuracy(self):
        """5. Verify KPI summary counts correctly without duplications."""
        order_data = {'customer_name': 'عميل 5', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 1, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 90000.0, 'subtotal_usd': 1.0}]
        accounting.create_order(order_data, items)

        kpis = accounting.get_orders_kpi_summary()
        self.assertGreaterEqual(kpis['total_orders'], 1)
        self.assertGreaterEqual(kpis['completed_orders'], 1)
        self.assertEqual(kpis['cancelled_orders'], 0)
        self.assertGreater(kpis['revenue_lbp'], 0)

    def test_06_filter_and_search_logic(self):
        """6. Filter by search query, status, and order type."""
        order_data = {'customer_name': 'أحمد السريع', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 1, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 90000.0, 'subtotal_usd': 1.0}]
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)

        # By order number
        res_search = accounting.get_orders(search=res['order_number'], include_all_statuses=True)
        self.assertEqual(len(res_search), 1)

        # By customer name
        res_cust = accounting.get_orders(search='أحمد السريع', include_all_statuses=True)
        self.assertEqual(len(res_cust), 1)

        # Non-existent search
        res_none = accounting.get_orders(search='اسم_غير_موجود_نهائيا_9999', include_all_statuses=True)
        self.assertEqual(len(res_none), 0)

    def test_07_api_order_details_endpoint(self):
        """7. Test JSON API endpoint for order details modal."""
        order_data = {'customer_name': 'عميل 7', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 1, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 90000.0, 'subtotal_usd': 1.0}]
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)
        oid = res['order_id']

        self._login()
        resp = self.client.get(f"/api/orders/{oid}/details")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['order']['id'], oid)

    def test_08_order_status_update_flow(self):
        """8. Test order status transitions: new -> preparing -> ready -> completed."""
        order_data = {
            'customer_name': 'عميل كانبان',
            'notes': 'طلب جديد للتتبع',
            'payment_method': 'cash',
            'order_type': 'takeaway',
            'status': 'new',
            'employee_id': self.cashier_id
        }
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 1, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 90000.0, 'subtotal_usd': 1.0}]
        success, res = accounting.create_order(order_data, items)
        self.assertTrue(success)
        test_oid = res['order_id']

        # Transition to preparing
        ok, msg = accounting.update_order_status(test_oid, 'preparing', updated_by='كاشير')
        self.assertTrue(ok, msg)
        det = accounting.get_order_details(test_oid)
        self.assertEqual(det['status'], 'preparing')

        # Transition to ready
        ok, msg = accounting.update_order_status(test_oid, 'ready', updated_by='كاشير')
        self.assertTrue(ok, msg)
        det = accounting.get_order_details(test_oid)
        self.assertEqual(det['status'], 'ready')

        # Transition to completed
        ok, msg = accounting.update_order_status(test_oid, 'completed', updated_by='كاشير')
        self.assertTrue(ok, msg)
        det = accounting.get_order_details(test_oid)
        self.assertEqual(det['status'], 'completed')

    def test_09_invalid_status_transition_guard(self):
        """9. Prevent transitioning to an invalid status."""
        order_data = {'customer_name': 'عميل 9', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 1, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 90000.0, 'subtotal_usd': 1.0}]
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)

        ok_bad, msg = accounting.update_order_status(res['order_id'], 'invalid_status_xyz')
        self.assertFalse(ok_bad)
        self.assertIn("غير صحيحة", msg)

    def test_10_api_status_update_route(self):
        """10. Test POST /api/orders/<id>/status endpoint."""
        order_data = {'customer_name': 'عميل 10', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 1, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 90000.0, 'subtotal_usd': 1.0}]
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)
        oid = res['order_id']

        resp = self._post_csrf(f"/api/orders/{oid}/status", {'status': 'completed', 'notes': 'فحص عبر API'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

    def test_11_order_cancellation_and_inventory_restoration(self):
        """11. Cancel order, verify non-destructive cancellation and stock return."""
        conn = database.get_db()
        conn.execute("UPDATE cafe_items SET stock_qty = 50, track_stock = 1 WHERE id = ?", (self.item_id,))
        conn.commit()
        conn.close()

        order_data = {'customer_name': 'عميل الإلغاء', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 5, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 450000.0, 'subtotal_usd': 5.0}]
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok)
        cancel_oid = res['order_id']

        # Verify stock decreased by 5
        conn = database.get_db()
        st_after_sale = conn.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_id,)).fetchone()['stock_qty']
        self.assertEqual(float(st_after_sale), 45.0)
        conn.close()

        # Cancel the order
        cancel_ok, cancel_msg = accounting.cancel_order(cancel_oid, cancelled_by='المدير', reason='فحص استعادة المخزون')
        self.assertTrue(cancel_ok, cancel_msg)

        # Verify stock restored to 50
        conn = database.get_db()
        st_after_cancel = conn.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_id,)).fetchone()['stock_qty']
        self.assertEqual(float(st_after_cancel), 50.0)

        # Verify order marked as cancelled
        ord_status = conn.execute("SELECT status FROM cafe_orders WHERE id = ?", (cancel_oid,)).fetchone()['status']
        self.assertEqual(ord_status, 'cancelled')
        conn.close()

    def test_12_cannot_modify_cancelled_order(self):
        """12. Prevent changing status of an already cancelled order."""
        order_data = {'customer_name': 'عميل 12', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 1, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 90000.0, 'subtotal_usd': 1.0}]
        ok, res = accounting.create_order(order_data, items)
        oid = res['order_id']
        accounting.cancel_order(oid, cancelled_by='المدير', reason='إلغاء أولي')

        ok_mod, msg = accounting.update_order_status(oid, 'preparing')
        self.assertFalse(ok_mod)
        self.assertIn("ملغي مسبقاً", msg)

    def test_13_live_polling_api(self):
        """13. Test GET /api/orders/list for live polling sync."""
        self._login()
        resp = self.client.get('/api/orders/list?period=today')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertIn('orders', data)
        self.assertIn('kpis', data)
        self.assertIn('timestamp', data)

    def test_14_orders_page_html_rendering(self):
        """14. Test GET /orders renders 200 and contains Cards, Table, and Kanban views."""
        self._login()
        resp = self.client.get('/orders')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8', errors='ignore')
        self.assertIn('إدارة ومتابعة الطلبات المباشرة', html)
        self.assertIn('ordersPane-cards', html)
        self.assertIn('ordersPane-table', html)
        self.assertIn('ordersPane-kanban', html)
        self.assertIn('orderDetailsModal', html)

    def test_15_receipt_reprinting_no_financial_duplication(self):
        """15. Test thermal receipt and full A4 invoice reprint without duplicating sales."""
        order_data = {'customer_name': 'عميل 15', 'payment_method': 'cash', 'employee_id': self.cashier_id}
        items = [{'item_id': self.item_id, 'name': 'اسبريسو سنجل فاخر', 'quantity': 1, 'price_lbp': 90000.0, 'price_usd': 1.0, 'subtotal_lbp': 90000.0, 'subtotal_usd': 1.0}]
        ok, res = accounting.create_order(order_data, items)
        oid = res['order_id']

        conn = database.get_db()
        initial_order_count = conn.execute("SELECT COUNT(*) as c FROM cafe_orders").fetchone()['c']
        conn.close()

        self._login()
        # Thermal 80mm
        resp1 = self.client.get(f"/order/{oid}/receipt")
        self.assertEqual(resp1.status_code, 200)

        # A4 Formal invoice
        resp2 = self.client.get(f"/order/{oid}/receipt?format=full")
        self.assertEqual(resp2.status_code, 200)

        # Verify no new orders were inserted by reprinting
        conn = database.get_db()
        final_order_count = conn.execute("SELECT COUNT(*) as c FROM cafe_orders").fetchone()['c']
        conn.close()
        self.assertEqual(initial_order_count, final_order_count)

    def test_16_auth_guard_on_orders_routes(self):
        """16. Unauthenticated requests to /orders must redirect to login."""
        with self.client.session_transaction() as sess:
            sess.clear()

        resp = self.client.get('/orders')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/employee/login', resp.headers.get('Location', ''))


if __name__ == '__main__':
    unittest.main()
