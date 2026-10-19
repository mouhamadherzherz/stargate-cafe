import unittest
import os
import sqlite3
import tempfile
import shutil
from decimal import Decimal
import database
import accounting

class TestFractionalPlayerBilling(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.orig_db_path = database.DB_PATH
        self.test_db_path = os.path.join(self.test_dir, 'test_cafe.db')
        database.DB_PATH = self.test_db_path
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.orig_db_path
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_calculate_order_totals_fractional(self):
        rate = 89500.0
        # 0.5 hour
        items_half = [{'name': 'كمبيوتر 💻', 'price_lbp': 100000.0, 'quantity': 0.5, 'item_type': 'computer'}]
        res_half = accounting.calculate_order_totals(items_half, rate)
        self.assertEqual(res_half['total_lbp'], 50000.0)
        self.assertEqual(res_half['items'][0]['quantity'], 0.5)

        # 1.5 hours
        items_1_5 = [{'name': 'كمبيوتر 💻', 'price_lbp': 100000.0, 'quantity': 1.5, 'item_type': 'computer'}]
        res_1_5 = accounting.calculate_order_totals(items_1_5, rate)
        self.assertEqual(res_1_5['total_lbp'], 150000.0)
        self.assertEqual(res_1_5['items'][0]['quantity'], 1.5)

        # 2.5 hours
        items_2_5 = [{'name': 'كمبيوتر 💻', 'price_lbp': 100000.0, 'quantity': 2.5, 'item_type': 'computer'}]
        res_2_5 = accounting.calculate_order_totals(items_2_5, rate)
        self.assertEqual(res_2_5['total_lbp'], 250000.0)
        self.assertEqual(res_2_5['items'][0]['quantity'], 2.5)

    def test_create_and_cancel_order_half_hour(self):
        # 0.5 hour session
        order_data = {
            'customer_name': 'خالد - نصف ساعة',
            'order_type': 'takeaway',
            'payment_method': 'cash',
            'employee_name': 'كاشير'
        }
        items = [{'name': 'كمبيوتر 💻', 'price_lbp': 100000.0, 'quantity': 0.5, 'item_type': 'computer'}]
        success, res = accounting.create_order(order_data, items)
        self.assertTrue(success)
        order_id = res['order_id']
        self.assertEqual(res['total_lbp'], 50000.0)

        # Cancel order
        c_ok, c_msg = accounting.cancel_order(order_id, reason='غادر الزبون مبكراً', cancelled_by='مدير')
        self.assertTrue(c_ok, f'Cancel failed: {c_msg}')

    def test_create_order_2_and_half_hours(self):
        # 2.5 hours session
        order_data = {
            'customer_name': 'سامر - ساعتين ونصف',
            'order_type': 'takeaway',
            'payment_method': 'cash',
            'employee_name': 'كاشير'
        }
        items = [{'name': 'كمبيوتر 💻', 'price_lbp': 100000.0, 'quantity': 2.5, 'item_type': 'computer'}]
        success, res = accounting.create_order(order_data, items)
        self.assertTrue(success)
        order_id = res['order_id']
        self.assertEqual(res['total_lbp'], 250000.0)

        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT quantity, unit_price_lbp, subtotal_lbp FROM cafe_order_items WHERE order_id = ?', (order_id,))
        item_row = cursor.fetchone()
        self.assertEqual(float(item_row['quantity']), 2.5)
        self.assertEqual(float(item_row['subtotal_lbp']), 250000.0)
        conn.close()

if __name__ == '__main__':
    unittest.main()
