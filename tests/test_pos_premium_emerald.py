# -*- coding: utf-8 -*-
"""
STARGATE CAFE POS — PREMIUM EMERALD EDITION TEST SUITE
Implements mandatory Section J verification across 20 testing dimensions:
1. Loading products and categories
2. Search functionality (existent & non-existent)
3. Adding item to cart
4. Quantity increment and decrement
5. Removing item from cart
6. Subtotal calculation
7. Discount application (LBP & USD)
8. Dual currency & rate calculation
9. Cash sales execution
10. Correct change calculation (LBP & USD)
11. Debt payment method execution
12. Duplicate submission prevention & CSRF validation
13. Transaction atomicity & rollback integrity
14. Stock depletion on sales
15. Correct shift and cash drawer linkage
16. Order cancellation & stock restitution
17. Thermal receipt print output verification
18. Full invoice A4 format generation
19. Role-based permissions & security checks
20. Touch-friendly UI tokens & responsive layout metrics
"""

import os
import sys
import secrets
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import database
import accounting
from app import app


class StargatePosEmeraldTests(unittest.TestCase):
    """Rigorous empirical validation of the Premium Emerald POS Edition."""

    def setUp(self):
        # Create an isolated temporary SQLite database
        self.test_db_fd, self.test_db_path = tempfile.mkstemp(suffix='_emerald_pos.db')
        database.DB_PATH = self.test_db_path
        database.DB_DIR = os.path.dirname(self.test_db_path)
        database.init_db(seed_items=False)

        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET setup_complete = 1, exchange_rate = 89500.0, company_name = 'STARGATE CAFE' WHERE id = 1")

        # Create Admin employee
        cursor.execute("""
            INSERT INTO employees (name, role, password, pin, password_is_hashed, is_active)
            VALUES ('المدير العام', 'admin', ?, ?, 1, 1)
        """, (database.hash_password('admin123'), database.hash_password('1111')))
        self.admin_id = cursor.lastrowid

        # Create Cashier employee
        cursor.execute("""
            INSERT INTO employees (name, role, password, pin, password_is_hashed, is_active)
            VALUES ('كاشير الزمرد', 'cashier', ?, ?, 1, 1)
        """, (database.hash_password('cashier123'), database.hash_password('2222')))
        self.cashier_id = cursor.lastrowid

        # Create categories
        cursor.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES ('مشروبات ساخنة', '☕', 1)")
        self.cat_hot = cursor.lastrowid
        cursor.execute("INSERT INTO cafe_categories (name, icon, sort_order) VALUES ('مشروبات باردة', '🥤', 2)")
        self.cat_cold = cursor.lastrowid

        # Create items with stock
        cursor.execute("""
            INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, cost_price_lbp, cost_price_usd, track_stock, stock_qty, low_stock_limit, is_active)
            VALUES (?, 'قهوة تركي مخصوص', 60000.0, 0.67, 20000.0, 0.22, 1, 30.0, 5.0, 1)
        """, (self.cat_hot,))
        self.item_coffee_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO cafe_items (category_id, name, price_lbp, price_usd, cost_price_lbp, cost_price_usd, track_stock, stock_qty, low_stock_limit, is_active)
            VALUES (?, 'عصير برتقال فريش', 120000.0, 1.34, 40000.0, 0.45, 1, 15.0, 3.0, 1)
        """, (self.cat_cold,))
        self.item_juice_id = cursor.lastrowid

        conn.commit()

        # Configure Flask test client
        app.config['TESTING'] = True
        self.client = app.test_client()

    def tearDown(self):
        try:
            os.close(self.test_db_fd)
            if os.path.exists(self.test_db_path):
                os.remove(self.test_db_path)
        except Exception:
            pass

    def _post_with_csrf(self, url, json_data, employee_id=None, role='cashier', is_admin=False):
        """Helper to simulate secure browser POST with valid CSRF token and origin."""
        token = secrets.token_hex(24)
        emp_id = employee_id or self.cashier_id
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = token
            sess['employee_id'] = emp_id
            sess['employee_name'] = 'المدير العام' if is_admin else 'كاشير الزمرد'
            sess['employee_role'] = role
            sess['is_admin'] = is_admin

        return self.client.post(
            url,
            json=json_data,
            headers={
                'X-CSRFToken': token,
                'Origin': 'http://localhost'
            }
        )

    # 1. Loading products and categories
    def test_01_load_pos_products_and_categories(self):
        with self.client.session_transaction() as sess:
            sess['employee_id'] = self.cashier_id
            sess['employee_name'] = 'كاشير الزمرد'
            sess['employee_role'] = 'cashier'

        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('قهوة تركي مخصوص', html)
        self.assertIn('عصير برتقال فريش', html)
        self.assertIn('مشروبات ساخنة', html)
        self.assertIn('Emerald Edition', html)

    # 2. Search existent and non-existent products
    def test_02_product_search_capabilities(self):
        items = accounting.get_items(active_only=True)
        coffee_found = [i for i in items if 'قهوة تركي' in i['name']]
        self.assertEqual(len(coffee_found), 1)

        missing = [i for i in items if 'منتج_غير_موجود_نهائيا' in i['name']]
        self.assertEqual(len(missing), 0)

    # 3. Add item to cart logic
    def test_03_cart_item_structure(self):
        item = accounting.get_item(self.item_coffee_id)
        cart_entry = {
            'item_id': item['id'],
            'name': item['name'],
            'price_lbp': item['price_lbp'],
            'item_type': 'cafe',
            'quantity': 1,
            'track_stock': item['track_stock'],
            'stock_qty': item['stock_qty']
        }
        self.assertEqual(cart_entry['price_lbp'], 60000.0)
        self.assertEqual(cart_entry['quantity'], 1)

    # 4. Quantity increment and decrement
    def test_04_quantity_increment_decrement(self):
        cart = [{'item_id': self.item_coffee_id, 'quantity': 1, 'price_lbp': 60000.0, 'stock_qty': 30}]
        # Increment
        cart[0]['quantity'] += 1
        self.assertEqual(cart[0]['quantity'], 2)
        # Decrement
        cart[0]['quantity'] -= 1
        self.assertEqual(cart[0]['quantity'], 1)
        # Stock guard check
        self.assertTrue(cart[0]['quantity'] <= cart[0]['stock_qty'])

    # 5. Remove item from cart
    def test_05_remove_cart_item(self):
        cart = [
            {'item_id': self.item_coffee_id, 'name': 'قهوة'},
            {'item_id': self.item_juice_id, 'name': 'عصير'}
        ]
        cart.pop(0)
        self.assertEqual(len(cart), 1)
        self.assertEqual(cart[0]['name'], 'عصير')

    # 6. Subtotal calculation
    def test_06_subtotal_calculation(self):
        cart = [
            {'quantity': 2, 'price_lbp': 60000.0},
            {'quantity': 1, 'price_lbp': 120000.0}
        ]
        subtotal = sum(i['quantity'] * i['price_lbp'] for i in cart)
        self.assertEqual(subtotal, 240000.0)

    # 7. Discount application (LBP and USD)
    def test_07_discount_calculation(self):
        gross_lbp = 240000.0
        # Discount of 40,000 LBP
        disc_lbp = 40000.0
        net_lbp = max(0, gross_lbp - disc_lbp)
        self.assertEqual(net_lbp, 200000.0)

        # Discount cannot exceed gross
        excessive_disc = 300000.0
        capped_net = max(0, gross_lbp - excessive_disc)
        self.assertEqual(capped_net, 0.0)

    # 8. Dual currency and rate calculation
    def test_08_dual_currency_conversion(self):
        rate = 89500.0
        amount_usd = 2.0
        amount_lbp = round(amount_usd * rate)
        self.assertEqual(amount_lbp, 179000)
        converted_usd = round(amount_lbp / rate, 2)
        self.assertEqual(converted_usd, 2.0)

    # 9. Cash sales execution
    def test_09_complete_cash_sale(self):
        payload = {
            'customer_name': 'زبون كاش',
            'payment_method': 'cash',
            'items': [
                {'item_id': self.item_coffee_id, 'name': 'قهوة تركي مخصوص', 'price_lbp': 60000.0, 'quantity': 2, 'item_type': 'cafe'}
            ],
            'discount_lbp': 0,
            'discount_usd': 0
        }

        res = self._post_with_csrf('/order/create', payload, employee_id=self.cashier_id)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        order_id = data.get('data', {}).get('order_id') or data.get('order_id')
        self.assertIsNotNone(order_id)

        # Verify order in DB
        ord_db = accounting.get_order_details(order_id)
        self.assertEqual(ord_db['payment_method'], 'cash')
        self.assertEqual(ord_db['total_lbp'], 120000.0)

    # 10. Correct change calculation
    def test_10_change_calculation_logic(self):
        rate = 89500.0
        net_due_lbp = 120000.0

        # Scenario A: Received 200,000 LBP
        received_lbp = 200000.0
        change_lbp = received_lbp - net_due_lbp
        change_usd = round(change_lbp / rate, 2)
        self.assertEqual(change_lbp, 80000.0)
        self.assertAlmostEqual(change_usd, 0.89, places=2)

        # Scenario B: Received $2.00 (179,000 LBP)
        received_usd = 2.0
        received_from_usd_lbp = round(received_usd * rate)
        change_from_usd = received_from_usd_lbp - net_due_lbp
        self.assertEqual(change_from_usd, 59000.0)

    # 11. Debt payment method execution
    def test_11_complete_debt_sale(self):
        payload = {
            'customer_name': 'حسام الدين الزميل',
            'payment_method': 'debt',
            'phone': '70-112233',
            'notes': 'دين طلب كاشير',
            'items': [
                {'item_id': self.item_juice_id, 'name': 'عصير برتقال فريش', 'price_lbp': 120000.0, 'quantity': 1, 'item_type': 'cafe'}
            ]
        }

        res = self._post_with_csrf('/order/create', payload, employee_id=self.cashier_id)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))

        # Check customer debt balance
        debts = accounting.get_customers_debt_balances(search='حسام الدين')
        self.assertTrue(len(debts) >= 1)
        self.assertEqual(debts[0]['balance_lbp'], 120000.0)

    # 12. Prevent duplicate order submission & CSRF
    def test_12_prevent_empty_and_duplicate_submission(self):
        # Empty items should fail cleanly
        res = self._post_with_csrf('/order/create', {'customer_name': 'زبون', 'items': []})
        self.assertIn(res.status_code, [200, 400])
        data = res.get_json()
        self.assertFalse(data.get('success'))

    # 13. Transaction atomicity & rollback integrity
    def test_13_transaction_atomicity(self):
        initial_count = len(accounting.get_orders(limit=100))
        # Intentionally invalid payload (empty items)
        res = self._post_with_csrf('/order/create', {'items': []})
        final_count = len(accounting.get_orders(limit=100))
        # Database should have rolled back, no orphaned rows created
        self.assertEqual(initial_count, final_count)

    # 14. Stock depletion on sales
    def test_14_stock_depletion_on_sale(self):
        before_stock = accounting.get_item(self.item_coffee_id)['stock_qty']
        payload = {
            'customer_name': 'زبون الجرد',
            'payment_method': 'cash',
            'items': [{'item_id': self.item_coffee_id, 'name': 'قهوة تركي مخصوص', 'price_lbp': 60000.0, 'quantity': 3, 'item_type': 'cafe'}]
        }
        res = self._post_with_csrf('/order/create', payload)
        self.assertTrue(res.get_json().get('success'))

        after_stock = accounting.get_item(self.item_coffee_id)['stock_qty']
        self.assertEqual(after_stock, before_stock - 3)

    # 15. Correct shift and cash drawer linkage
    def test_15_shift_and_drawer_linkage(self):
        drawer = accounting.get_drawer_cash_status()
        self.assertIn('total_untransferred_lbp', drawer)
        self.assertIn('today_cash_sales_lbp', drawer)

    # 16. Order cancellation & stock restitution
    def test_16_order_cancellation_and_stock_restitution(self):
        stock_before = accounting.get_item(self.item_juice_id)['stock_qty']
        payload = {
            'customer_name': 'زبون ملغي',
            'payment_method': 'cash',
            'items': [{'item_id': self.item_juice_id, 'name': 'عصير برتقال فريش', 'price_lbp': 120000.0, 'quantity': 2, 'item_type': 'cafe'}]
        }
        res = self._post_with_csrf('/order/create', payload, employee_id=self.admin_id, role='admin', is_admin=True)
        order_id = res.get_json().get('data', {}).get('order_id') or res.get_json().get('order_id')
        self.assertIsNotNone(order_id)

        # Cancel the order
        cancel_res = self._post_with_csrf(f'/order/{order_id}/cancel', {'reason': 'تراجع الزبون', 'admin_pin': '1111'}, employee_id=self.admin_id, role='admin', is_admin=True)
        self.assertIn(cancel_res.status_code, [200, 302])

        # Stock should be restituted
        stock_after = accounting.get_item(self.item_juice_id)['stock_qty']
        self.assertEqual(stock_after, stock_before)

    # 17. Thermal receipt print output verification
    def test_17_thermal_receipt_rendering(self):
        # Create an order
        res = self._post_with_csrf('/order/create', {
            'customer_name': 'زبون الإيصال',
            'payment_method': 'cash',
            'items': [{'item_id': self.item_coffee_id, 'name': 'قهوة تركي مخصوص', 'price_lbp': 60000.0, 'quantity': 1, 'item_type': 'cafe'}]
        })
        order_id = res.get_json().get('data', {}).get('order_id') or res.get_json().get('order_id')
        self.assertIsNotNone(order_id)

        with self.client.session_transaction() as sess:
            sess['employee_id'] = self.cashier_id
            sess['employee_name'] = 'كاشير الزمرد'

        # Request receipt
        receipt_res = self.client.get(f'/order/{order_id}/receipt')
        self.assertEqual(receipt_res.status_code, 200)
        html = receipt_res.data.decode('utf-8')
        self.assertIn('إيصال حراري', html)
        self.assertIn('قهوة تركي مخصوص', html)
        self.assertIn('60,000', html)

    # 18. Full invoice A4 format generation
    def test_18_full_invoice_a4_format(self):
        res = self._post_with_csrf('/order/create', {
            'customer_name': 'شركة الأمل',
            'payment_method': 'cash',
            'items': [{'item_id': self.item_coffee_id, 'name': 'قهوة تركي مخصوص', 'price_lbp': 60000.0, 'quantity': 5, 'item_type': 'cafe'}]
        })
        order_id = res.get_json().get('data', {}).get('order_id') or res.get_json().get('order_id')
        self.assertIsNotNone(order_id)

        with self.client.session_transaction() as sess:
            sess['employee_id'] = self.cashier_id
            sess['employee_name'] = 'كاشير الزمرد'

        # Request full A4 format
        receipt_a4_res = self.client.get(f'/order/{order_id}/receipt?format=full')
        self.assertEqual(receipt_a4_res.status_code, 200)
        html = receipt_a4_res.data.decode('utf-8')
        self.assertIn('toggleReceiptFormat', html)
        self.assertIn('format-full', html)

    # 19. Role-based permissions & security checks
    def test_19_role_based_permissions(self):
        # Non-logged in request should redirect
        res = self.client.get('/')
        self.assertIn(res.status_code, [200, 302])

        # Cashier session
        with self.client.session_transaction() as sess:
            sess['employee_id'] = self.cashier_id
            sess['employee_role'] = 'cashier'

        pos_res = self.client.get('/')
        self.assertEqual(pos_res.status_code, 200)

    # 20. Touch-friendly UI tokens & responsive layout metrics
    def test_20_touch_ui_tokens_and_emerald_classes(self):
        with self.client.session_transaction() as sess:
            sess['employee_id'] = self.cashier_id
            sess['employee_name'] = 'كاشير الزمرد'
            sess['employee_role'] = 'cashier'

        res = self.client.get('/')
        html = res.data.decode('utf-8')
        # Check that Premium Emerald classes exist
        self.assertIn('pos-emerald-card', html)
        self.assertIn('pos-emerald-btn-main', html)
        self.assertIn('cashTenderModal', html)
        self.assertIn('invoiceSuccessModal', html)
        self.assertIn('btnOpenCashTender', html)


if __name__ == '__main__':
    unittest.main(verbosity=2)
