import unittest
import os
import sqlite3
import tempfile
import shutil
import database
import accounting

class TestSafeTransferGamingAndCafe(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.orig_db_path = database.DB_PATH
        self.test_db_path = os.path.join(self.test_dir, 'test_cafe_safe.db')
        database.DB_PATH = self.test_db_path
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.orig_db_path
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_safe_transfer_full_drawer_zeros_gaming_and_cafe(self):
        # 1. Create a cafe order (Cash: 120,000 LBP)
        cafe_order_data = {'customer_name': 'زبون كافيه', 'payment_method': 'cash', 'employee_name': 'الكاشير'}
        cafe_items = [{'name': 'اسبريسو ☕', 'price_lbp': 120000.0, 'quantity': 1, 'item_type': 'cafe'}]
        ok1, res1 = accounting.create_order(cafe_order_data, cafe_items)
        self.assertTrue(ok1)

        # 2. Create a gaming order (Cash: 150,000 LBP - 1.5 hours)
        gaming_order_data = {'customer_name': 'لاعب كمبيوتر', 'payment_method': 'cash', 'employee_name': 'الكاشير'}
        gaming_items = [{'name': 'كمبيوتر 💻', 'price_lbp': 100000.0, 'quantity': 1.5, 'item_type': 'computer'}]
        ok2, res2 = accounting.create_order(gaming_order_data, gaming_items)
        self.assertTrue(ok2)

        # 3. Check drawer status before safe transfer
        drawer_before = accounting.get_drawer_cash_status()
        self.assertEqual(drawer_before['total_untransferred_lbp'], 270000.0)
        self.assertEqual(drawer_before['today_gaming_cash_lbp'], 150000.0)
        self.assertEqual(drawer_before['today_cafe_cash_lbp'], 120000.0)
        self.assertEqual(drawer_before['untransferred_pc_lbp'], 150000.0)
        self.assertEqual(drawer_before['untransferred_cafe_lbp'], 120000.0)
        self.assertFalse(drawer_before['is_gaming_transferred'])
        self.assertFalse(drawer_before['is_cafe_transferred'])

        # 4. Perform full drawer transfer to safe
        transfer_res = accounting.transfer_drawer_total_to_safe(transferred_by='المدير', note='ترحيل كامل كاش الدرج')
        self.assertEqual(transfer_res['amount_lbp'], 270000.0)

        # 5. Check drawer status after safe transfer
        drawer_after = accounting.get_drawer_cash_status()
        self.assertEqual(drawer_after['total_untransferred_lbp'], 0.0)
        self.assertEqual(drawer_after['untransferred_pc_lbp'], 0.0)
        self.assertEqual(drawer_after['untransferred_cafe_lbp'], 0.0)
        self.assertTrue(drawer_after['is_gaming_transferred'], 'Gaming cash must be marked as transferred')
        self.assertTrue(drawer_after['is_cafe_transferred'], 'Cafe cash must be marked as transferred')

        # 6. Verify Safe balance
        safe_bal = accounting.get_safe_balance()
        self.assertEqual(safe_bal['total_lbp'], 270000.0)

    def test_safe_transfer_gaming_only(self):
        # 1. Create a cafe order (Cash: 100,000 LBP)
        accounting.create_order({'customer_name': 'زبون', 'payment_method': 'cash'}, [{'name': 'شاي', 'price_lbp': 100000.0, 'quantity': 1, 'item_type': 'cafe'}])
        # 2. Create a gaming order (Cash: 200,000 LBP)
        accounting.create_order({'customer_name': 'لاعب', 'payment_method': 'cash'}, [{'name': 'كمبيوتر 💻', 'price_lbp': 100000.0, 'quantity': 2.0, 'item_type': 'computer'}])

        # Transfer specifically the gaming cash (200,000 LBP)
        accounting.add_safe_transfer(amount_lbp=200000.0, note='ترحيل كاش الألعاب فقط', transferred_by='الكاشير')

        # Verify drawer status
        drawer = accounting.get_drawer_cash_status()
        self.assertEqual(drawer['total_untransferred_lbp'], 100000.0)
        self.assertEqual(drawer['all_transferred_to_safe_lbp'], 200000.0)

if __name__ == '__main__':
    unittest.main()
