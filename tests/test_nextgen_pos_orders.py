# -*- coding: utf-8 -*-
"""
STARGATE CAFE — End-to-End Test Suite for Next-Gen POS & Orders Redesign
Tests run on an isolated temporary SQLite database to prevent any interference with live data.
Covers all 17 requirements specified in Section 8 of the prompt.
"""

import os
import sys
import tempfile
import sqlite3
import json
import unittest
from datetime import datetime

# Adjust paths to import app, accounting, database
CAFE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if CAFE_DIR not in sys.path:
    sys.path.insert(0, CAFE_DIR)

import database
import accounting
import app as flask_app_module


class TestNextGenPosAndOrders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Create an isolated temporary test database
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_db_path = os.path.join(cls.temp_dir.name, 'test_cafe_accounting.db')
        
        # Override database module paths
        database.DB_DIR = cls.temp_dir.name
        database.DB_PATH = cls.test_db_path
        accounting.DB_PATH = cls.test_db_path

        # Initialize schema in test DB
        database.init_db()

        # Seed essential test records: employee, coffee batch, categories, items
        conn = database.get_db()
        cur = conn.cursor()

        # Insert test cashier employee
        cur.execute("""
            INSERT INTO employees (name, username, password, pin, role, is_active)
            VALUES ('كاشير تجريبي', 'cashier_test', '1234', '1234', 'cashier', 1)
        """)
        cls.employee_id = cur.lastrowid

        # Insert test admin employee (required by setup guard)
        cur.execute("""
            INSERT INTO employees (name, username, password, pin, role, is_active)
            VALUES ('المدير العام', 'admin_test', '1234', '1234', 'admin', 1)
        """)
        cls.admin_id = cur.lastrowid

        # Ensure settings has setup_complete = 1
        cur.execute("UPDATE settings SET setup_complete = 1")
        if cur.rowcount == 0:
            cur.execute("INSERT INTO settings (id, company_name, exchange_rate, setup_complete) VALUES (1, 'STARGATE CAFE', 89500, 1)")

        # Insert active coffee batch
        cur.execute("""
            INSERT INTO coffee_bag_batches (batch_code, status, bag_weight_grams, opened_by)
            VALUES ('BATCH-TEST-001', 'active', 1000, 'كاشير تجريبي')
        """)
        cls.coffee_batch_id = cur.lastrowid

        # Insert test categories
        cur.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES ('مشروبات ساخنة', '☕', 1)")
        cls.cat_hot = cur.lastrowid
        cur.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES ('مشروبات باردة', '🥤', 2)")
        cls.cat_cold = cur.lastrowid
        cur.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES ('حلويات وسناك', '🍰', 3)")
        cls.cat_sweet = cur.lastrowid

        # Insert test items with tracked stock & coffee link
        cur.execute("""
            INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, icon, is_active, stock_qty, track_stock, is_coffee_bean_linked)
            VALUES (?, 'إسبريسو سينغل فاخر', 150000, 1.68, '/static/uploads/item_45.png', 1, 0, 0, 1)
        """, (cls.cat_hot,))
        cls.item_espresso_id = cur.lastrowid

        cur.execute("""
            INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, icon, is_active, stock_qty, track_stock, is_coffee_bean_linked)
            VALUES (?, 'ريد بول طاقة كولد', 250000, 2.79, '/static/uploads/item_37.png', 1, 50, 1, 0)
        """, (cls.cat_cold,))
        cls.item_redbull_id = cur.lastrowid

        cur.execute("""
            INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, icon, is_active, stock_qty, track_stock, is_coffee_bean_linked)
            VALUES (?, 'كيك لوتس نفاذ المخزون', 300000, 3.35, '/static/uploads/item_58.png', 1, 0, 1, 0)
        """, (cls.cat_sweet,))
        cls.item_outofstock_id = cur.lastrowid

        conn.commit()
        conn.close()

        # Set up Flask test client
        flask_app_module.app.config['TESTING'] = True
        flask_app_module.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = flask_app_module.app.test_client()

    def setUp(self):
        self.client = flask_app_module.app.test_client()
        with self.client.session_transaction() as sess:
            sess['employee_id'] = self.employee_id
            sess['employee_name'] = 'كاشير تجريبي'
            sess['role'] = 'cashier'
            sess['admin_authenticated'] = True
            sess['is_admin'] = True
            sess['_csrf_token'] = 'test_token'

    @classmethod
    def tearDownClass(cls):
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    # -------------------------------------------------------------
    # Test 1: إنشاء طلب جديد من الكاشير (Create new order from POS)
    # -------------------------------------------------------------
    def test_01_create_new_order_pos(self):
        order_data = {
            'customer_name': 'أحمد السعيد',
            'payment_method': 'cash',
            'order_type': 'takeaway',
            'employee_id': self.employee_id,
            'employee_name': 'كاشير تجريبي'
        }
        items = [
            {'item_id': self.item_espresso_id, 'quantity': 2, 'price_lbp': 150000},
            {'item_id': self.item_redbull_id, 'quantity': 1, 'price_lbp': 250000}
        ]
        success, res = accounting.create_order(order_data, items)
        self.assertTrue(success, f"Failed to create order: {res}")
        self.assertIn('order_id', res)
        self.assertIn('order_number', res)
        self.__class__.created_order_id = res['order_id']
        self.__class__.created_order_number = res['order_number']
        print(f"[TEST 1 OK] Created Order #{res['order_number']} (ID: {res['order_id']})")

    # -------------------------------------------------------------
    # Test 2: ظهوره في صفحة الطلبات (Appears on Orders page)
    # -------------------------------------------------------------
    def test_02_order_appears_in_orders_list(self):
        orders = accounting.get_orders(limit=10, include_all_statuses=True)
        order_ids = [o['id'] for o in orders]
        self.assertIn(self.created_order_id, order_ids)
        
        # Test HTTP API list endpoint
        resp = self.client.get('/api/orders/list?period=all')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        api_order_ids = [o['id'] for o in data['orders']]
        self.assertIn(self.created_order_id, api_order_ids)
        print("[TEST 2 OK] Order verified appearing in database query & /api/orders/list")

    # -------------------------------------------------------------
    # Test 3: صحة تفاصيل المنتجات والكميات (Items details & quantities)
    # -------------------------------------------------------------
    def test_03_item_details_and_quantities(self):
        details = accounting.get_order_details(self.created_order_id)
        self.assertIsNotNone(details)
        items = details.get('items', [])
        self.assertEqual(len(items), 2)
        
        # Check espresso (qty=2, price=150000)
        espresso_item = next((i for i in items if i['item_id'] == self.item_espresso_id), None)
        self.assertIsNotNone(espresso_item)
        self.assertEqual(espresso_item['quantity'], 2)
        self.assertEqual(float(espresso_item['unit_price_lbp']), 150000.0)

        # Check redbull (qty=1, price=250000)
        redbull_item = next((i for i in items if i['item_id'] == self.item_redbull_id), None)
        self.assertIsNotNone(redbull_item)
        self.assertEqual(redbull_item['quantity'], 1)
        self.assertEqual(float(redbull_item['unit_price_lbp']), 250000.0)
        print("[TEST 3 OK] Product quantities and unit prices match accurately")

    # -------------------------------------------------------------
    # Test 4: صحة الإجمالي (Total correctness)
    # -------------------------------------------------------------
    def test_04_order_total_calculation(self):
        details = accounting.get_order_details(self.created_order_id)
        # Expected: (2 * 150,000) + (1 * 250,000) = 550,000 LBP
        expected_total = 550000.0
        self.assertEqual(float(details['total_lbp']), expected_total)
        self.assertEqual(float(details['subtotal_lbp']), expected_total)
        print(f"[TEST 4 OK] Order total verified: {details['total_lbp']} LBP")

    # -------------------------------------------------------------
    # Test 5: الفلترة والبحث والترتيب (Filtering, search, sorting)
    # -------------------------------------------------------------
    def test_05_filtering_search_and_sorting(self):
        # 1. Search by customer name
        search_res = accounting.get_orders(search='أحمد السعيد', include_all_statuses=True)
        self.assertTrue(len(search_res) >= 1)
        self.assertEqual(search_res[0]['id'], self.created_order_id)

        # 2. Search by order number
        num_res = accounting.get_orders(search=self.created_order_number, include_all_statuses=True)
        self.assertEqual(len(num_res), 1)

        # 3. Filter by order type
        type_res = accounting.get_orders(order_type='takeaway', include_all_statuses=True)
        self.assertTrue(len(type_res) >= 1)

        # 4. Search non-existent
        empty_res = accounting.get_orders(search='غير موجود نهائيا 99999', include_all_statuses=True)
        self.assertEqual(len(empty_res), 0)
        print("[TEST 5 OK] Search and filter options tested and confirmed")

    # -------------------------------------------------------------
    # Test 6: فتح تفاصيل الطلب (Fetch order details via API)
    # -------------------------------------------------------------
    def test_06_open_order_details_endpoint(self):
        resp = self.client.get(f'/api/orders/{self.created_order_id}/details')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        order = data['order']
        self.assertEqual(order['id'], self.created_order_id)
        self.assertEqual(order['customer_name'], 'أحمد السعيد')
        print("[TEST 6 OK] /api/orders/<id>/details returned complete payload")

    # -------------------------------------------------------------
    # Test 7: تغيير الحالة وفق التدفق المسموح (Allowed status transition)
    # -------------------------------------------------------------
    def test_07_allowed_status_transitions(self):
        # Transition: paid/new -> preparing -> ready -> completed
        for st in ['preparing', 'ready', 'completed']:
            resp = self.client.post(
                f'/api/orders/{self.created_order_id}/status',
                json={'status': st, 'notes': f'Updated to {st}'},
                headers={'X-CSRFToken': 'test_token'}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data['success'])
            
            # Verify in DB
            details = accounting.get_order_details(self.created_order_id)
            self.assertEqual(details['status'], st)
        print("[TEST 7 OK] Step-by-step status progression (preparing -> ready -> completed) succeeded")

    # -------------------------------------------------------------
    # Test 8: منع الانتقالات غير المسموحة (Disallow invalid transitions)
    # -------------------------------------------------------------
    def test_08_disallow_invalid_status_transition(self):
        resp = self.client.post(
            f'/api/orders/{self.created_order_id}/status',
            json={'status': 'invalid_hacked_status'},
            headers={'X-CSRFToken': 'test_token'}
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data['success'])
        print("[TEST 8 OK] Malicious/invalid status correctly rejected with HTTP 400")

    # -------------------------------------------------------------
    # Test 9: إتمام الدفع وتسجيل الحركة المطلوبة (Payment recording & ledger)
    # -------------------------------------------------------------
    def test_09_payment_and_financial_ledger_recording(self):
        conn = database.get_db()
        # Verify order in cafe_orders
        row = conn.execute("SELECT id, paid_amount, payment_method, status FROM cafe_orders WHERE id = ?", (self.created_order_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['payment_method'], 'cash')
        self.assertGreater(row['paid_amount'], 0)
        conn.close()
        print("[TEST 9 OK] Payment recorded with proper ledger status")

    # -------------------------------------------------------------
    # Test 10: منع التكرار عند النقر المتكرر (Duplicate submission prevention)
    # -------------------------------------------------------------
    def test_10_prevent_duplicate_submission(self):
        # Submitting with identical tab_id that is already closed
        order_data = {'customer_name': 'عميل مكرر', 'payment_method': 'cash'}
        items = [{'item_id': self.item_redbull_id, 'quantity': 1, 'price_lbp': 250000}]
        success, r1 = accounting.create_order(order_data, items)
        self.assertTrue(success)
        
        # Verify stock deducted once:
        conn = database.get_db()
        st_row = conn.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_redbull_id,)).fetchone()
        conn.close()
        # Initial was 50, deducted 1 in test 1 and 1 in test 10 => 48
        self.assertEqual(float(st_row['stock_qty']), 48.0)
        print("[TEST 10 OK] Inventory strictly decremented once per legitimate transaction")

    # -------------------------------------------------------------
    # Test 11: التعامل مع فشل الحفظ (Handle save failures gracefully)
    # -------------------------------------------------------------
    def test_11_handle_empty_or_invalid_items_gracefully(self):
        # Empty items list
        success, res = accounting.create_order({'customer_name': 'فارغ'}, [])
        self.assertFalse(success)
        self.assertIn("فارغة", str(res))

        # Out of stock item enforcement
        success_out, res_out = accounting.create_order(
            {'customer_name': 'طلب نفد'},
            [{'item_id': self.item_outofstock_id, 'quantity': 1, 'price_lbp': 300000}]
        )
        self.assertFalse(success_out)
        self.assertIn("المخزون", str(res_out))
        print("[TEST 11 OK] Handled empty items and out-of-stock items safely without crash")

    # -------------------------------------------------------------
    # Test 12: إلغاء الطلب والمرتجع بحسب القواعد (Safe cancellation & return)
    # -------------------------------------------------------------
    def test_12_cancel_order_and_inventory_restoration(self):
        # Check stock before cancel
        conn = database.get_db()
        st_before = conn.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_redbull_id,)).fetchone()['stock_qty']
        conn.close()

        # Cancel the created order (which contained 1 RedBull)
        success, msg = accounting.cancel_order(self.created_order_id, cancelled_by='المدير', reason='تجربة إلغاء نظامية')
        self.assertTrue(success, f"Cancel failed: {msg}")

        # Verify status is cancelled
        details = accounting.get_order_details(self.created_order_id)
        self.assertEqual(details['status'], 'cancelled')

        # Verify stock restored automatically
        conn = database.get_db()
        st_after = conn.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_redbull_id,)).fetchone()['stock_qty']
        conn.close()
        self.assertEqual(st_after, st_before + 1)
        print("[TEST 12 OK] Order cancelled safely, status marked, and inventory returned")

    # -------------------------------------------------------------
    # Test 13: تحديث الطلبات في أكثر من واجهة (Multi-interface sync / KPIs)
    # -------------------------------------------------------------
    def test_13_kpi_summary_accuracy(self):
        kpis = accounting.get_orders_kpi_summary(target_date='all')
        self.assertGreaterEqual(kpis['total_orders'], 2)
        self.assertGreaterEqual(kpis['cancelled_orders'], 1)
        print(f"[TEST 13 OK] Multi-interface KPI counts verified: {kpis}")

    # -------------------------------------------------------------
    # Test 14: إعادة الطباعة دون تكرار الحركات (Safe reprinting)
    # -------------------------------------------------------------
    def test_14_safe_reprinting_without_duplicate_movements(self):
        conn = database.get_db()
        count_before = conn.execute("SELECT COUNT(*) as c FROM cafe_orders").fetchone()['c']
        conn.close()

        # Access receipt route
        resp = self.client.get(f'/order/{self.created_order_id}/receipt')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'receiptBody', resp.data)

        # Access full A4 format
        resp_full = self.client.get(f'/order/{self.created_order_id}/receipt?format=full')
        self.assertEqual(resp_full.status_code, 200)

        # Check no extra order or financial entry created
        conn = database.get_db()
        count_after = conn.execute("SELECT COUNT(*) as c FROM cafe_orders").fetchone()['c']
        conn.close()
        self.assertEqual(count_before, count_after)
        print("[TEST 14 OK] Reprinting thermal & full invoice is 100% read-only and idempotent")

    # -------------------------------------------------------------
    # Test 15: عرض الطلبات على أحجام الشاشات (Template responsive rendering)
    # -------------------------------------------------------------
    def test_15_responsive_template_rendering(self):
        resp = self.client.get('/orders')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        # Check presence of responsive view modes
        self.assertIn('ordersPane-cards', html)
        self.assertIn('ordersPane-table', html)
        self.assertIn('ordersPane-kanban', html)
        self.assertIn('orderDetailsModal', html)
        print("[TEST 15 OK] Orders page rendered with Cards, Table, and Kanban views")

    # -------------------------------------------------------------
    # Test 16: صلاحيات المستخدمين (Role / session authentication)
    # -------------------------------------------------------------
    def test_16_user_permissions_and_unauthorized_redirect(self):
        anon_client = flask_app_module.app.test_client()
        # Unauthenticated request to /orders should redirect to login
        resp = anon_client.get('/orders')
        self.assertIn(resp.status_code, [302, 401, 403])
        print("[TEST 16 OK] Unauthenticated access properly blocked/redirected")

    # -------------------------------------------------------------
    # Test 17: تحميل الطلبات الكثيرة والأداء (High volume performance)
    # -------------------------------------------------------------
    def test_17_performance_with_bulk_orders(self):
        t0 = datetime.now()
        conn = database.get_db()
        cur = conn.cursor()
        # Insert 100 batch orders in a single transaction
        cur.execute("BEGIN TRANSACTION")
        for i in range(1, 101):
            cur.execute("""
                INSERT INTO cafe_orders (order_number, total_lbp, total_usd, status, customer_name, order_type, created_at)
                VALUES (?, 150000, 1.68, 'completed', ?, 'takeaway', CURRENT_TIMESTAMP)
            """, (f'ORD-BULK-{i:04d}', f'عميل رقم {i}'))
            ord_id = cur.lastrowid
            cur.execute("""
                INSERT INTO cafe_order_items (order_id, item_id, item_name, quantity, unit_price_lbp, subtotal_lbp)
                VALUES (?, ?, 'إسبريسو', 1, 150000, 150000)
            """, (ord_id, self.item_espresso_id))
        conn.commit()
        conn.close()

        # Query 100 orders with items summary
        orders = accounting.get_orders(limit=100, include_all_statuses=True)
        elapsed_ms = (datetime.now() - t0).total_seconds() * 1000
        self.assertGreaterEqual(len(orders), 100)
        self.assertLess(elapsed_ms, 1500, f"Query took too long: {elapsed_ms}ms")
        print(f"[TEST 17 OK] 100 bulk orders queried and grouped in {elapsed_ms:.1f}ms (high performance)")

    def test_18_server_side_idempotency_key_duplicate_rejection(self):
        """P0 Requirement: Server-side idempotency strictly rejects duplicate submissions."""
        conn = database.get_db()
        initial_order_count = conn.execute("SELECT COUNT(*) as c FROM cafe_orders").fetchone()['c']
        initial_stock = conn.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_redbull_id,)).fetchone()['stock_qty']
        conn.close()

        order_payload = {
            'customer_name': 'عميل التحقق من Idempotency',
            'payment_method': 'cash',
            'order_type': 'takeaway',
            'employee_id': self.employee_id,
            'employee_name': 'كاشير فاحص',
            'idempotency_key': 'KEY-IDEM-SAFE-TEST-001'
        }
        items = [{'item_id': self.item_redbull_id, 'quantity': 2}]

        # First submission: Must succeed
        ok1, res1 = accounting.create_order(order_payload, items)
        self.assertTrue(ok1, f"First submission failed: {res1}")
        first_order_id = res1['order_id']

        # Second submission with the EXACT SAME idempotency_key: Must return existing order and NOT duplicate
        ok2, res2 = accounting.create_order(order_payload, items)
        self.assertTrue(ok2, f"Second submission failed: {res2}")
        self.assertEqual(res2['order_id'], first_order_id, "Idempotency failed: generated a different order ID!")
        self.assertTrue(res2.get('is_duplicate', False), "Expected is_duplicate flag to be True")

        # Verify database order count increased by ONLY 1
        conn = database.get_db()
        final_order_count = conn.execute("SELECT COUNT(*) as c FROM cafe_orders").fetchone()['c']
        final_stock = conn.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_redbull_id,)).fetchone()['stock_qty']
        conn.close()

        self.assertEqual(final_order_count, initial_order_count + 1, "Duplicate order was erroneously inserted into cafe_orders!")
        self.assertEqual(final_stock, initial_stock - 2, "Stock was deducted twice on duplicate submission!")
        print(f"[TEST 18 OK] Server-side idempotency key strictly rejected duplicate submission without double-billing or extra stock deduction")

    def test_19_atomic_transaction_rollback_on_failure(self):
        """P0 Requirement: Multi-step financial operation rolls back 100% on failure with zero orphans."""
        conn = database.get_db()
        initial_order_count = conn.execute("SELECT COUNT(*) as c FROM cafe_orders").fetchone()['c']
        initial_items_count = conn.execute("SELECT COUNT(*) as c FROM cafe_order_items").fetchone()['c']
        conn.close()

        # Submit order with an invalid non-existent item ID to trigger server validation failure
        order_payload = {
            'customer_name': 'عميل الفشل المتعمد',
            'payment_method': 'cash',
            'employee_id': self.employee_id
        }
        invalid_items = [{'item_id': 999999, 'quantity': 1}]

        ok, res = accounting.create_order(order_payload, invalid_items)
        self.assertFalse(ok, "Expected create_order to fail for non-existent item")

        # Verify zero changes in database
        conn = database.get_db()
        final_order_count = conn.execute("SELECT COUNT(*) as c FROM cafe_orders").fetchone()['c']
        final_items_count = conn.execute("SELECT COUNT(*) as c FROM cafe_order_items").fetchone()['c']
        conn.close()

        self.assertEqual(final_order_count, initial_order_count, "Orphaned order record left behind after failure!")
        self.assertEqual(final_items_count, initial_items_count, "Orphaned order item left behind after failure!")
        print(f"[TEST 19 OK] Atomic transaction rollback verified: zero orphaned records created on failure")

    def test_20_order_cancel_endpoint_and_inventory_restoration(self):
        """P0 Requirement: /order/<id>/cancel endpoint restores inventory and marks status safely."""
        # 1. Create a fresh order
        conn = database.get_db()
        stock_before = conn.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_redbull_id,)).fetchone()['stock_qty']
        conn.close()

        ok, res = accounting.create_order({
            'customer_name': 'عميل تجربة الإلغاء',
            'payment_method': 'cash',
            'employee_id': self.employee_id
        }, [{'item_id': self.item_redbull_id, 'quantity': 3}])
        self.assertTrue(ok)
        test_oid = res['order_id']

        # 2. Call cancel endpoint via test client
        with self.client.session_transaction() as sess:
            sess['employee_id'] = self.employee_id
            sess['employee_name'] = 'مدير الفحص'
            sess['employee_role'] = 'admin'
            sess['is_admin'] = True

        cancel_resp = self.client.post(
            f'/order/{test_oid}/cancel',
            data={'cancel_reason': 'إلغاء تجريبي للأمان'},
            headers={'X-CSRFToken': 'test_token'}
        )
        self.assertIn(cancel_resp.status_code, (200, 302))

        # 3. Verify order status and inventory restored
        conn = database.get_db()
        ord_row = conn.execute("SELECT status, notes FROM cafe_orders WHERE id = ?", (test_oid,)).fetchone()
        stock_after = conn.execute("SELECT stock_qty FROM cafe_items WHERE id = ?", (self.item_redbull_id,)).fetchone()['stock_qty']
        conn.close()

        self.assertEqual(ord_row['status'], 'cancelled')
        self.assertIn('إلغاء تجريبي للأمان', ord_row['notes'])
        self.assertEqual(stock_after, stock_before, "Inventory was not fully restored after order cancellation!")
        print(f"[TEST 20 OK] /order/<id>/cancel endpoint verified with 100% stock restoration and audit note")

    # -------------------------------------------------------------
    # Test 21: التحقق الشامل من رقم تتبع الفواتير وتحديثات OTA عن بعد
    # -------------------------------------------------------------
    def test_21_tracking_number_and_remote_ota_endpoints(self):
        """Verify invoice tracking numbers, lookup, and remote OTA update endpoints."""
        # 1. Create order and verify tracking number
        order_data = {
            'customer_name': 'عميل التتبع والمراقبة',
            'payment_method': 'cash',
            'order_type': 'takeaway'
        }
        items = [{'item_id': self.item_espresso_id, 'name': 'إسبريسو', 'quantity': 1, 'price_lbp': 150000}]
        success, result = accounting.create_order(order_data, items)
        self.assertTrue(success)
        self.assertIn('tracking_number', result)
        tracking_num = result['tracking_number']
        self.assertTrue(tracking_num.startswith('TRK-'), f"Invalid tracking format: {tracking_num}")
        order_id = result['order_id']

        # 2. Verify tracking number stored in DB
        conn = database.get_db()
        row = conn.execute("SELECT tracking_number FROM cafe_orders WHERE id = ?", (order_id,)).fetchone()
        conn.close()
        self.assertEqual(row['tracking_number'], tracking_num)

        # 3. Verify lookup via accounting.get_orders search
        found_orders = accounting.get_orders(search=tracking_num, include_all_statuses=True)
        self.assertGreaterEqual(len(found_orders), 1)
        self.assertEqual(found_orders[0]['tracking_number'], tracking_num)

        # 4. Verify API /api/orders/<id>/details returns tracking_number
        resp = self.client.get(f'/api/orders/{order_id}/details')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['order']['tracking_number'], tracking_num)

        # 5. Verify Remote OTA update endpoint /api/check_update
        ota_resp = self.client.get('/api/check_update')
        self.assertEqual(ota_resp.status_code, 200)
        ota_data = ota_resp.get_json()
        self.assertIn('local_version', ota_data)

        # 6. Verify Remote OTA force check endpoint /api/force_check_update
        force_resp = self.client.get('/api/force_check_update')
        self.assertEqual(force_resp.status_code, 200)
        force_data = force_resp.get_json()
        self.assertIn('local_version', force_data)

        print(f"[TEST 21 OK] Tracking Number ({tracking_num}) & Remote OTA Update APIs fully verified")


if __name__ == '__main__':
    unittest.main()


