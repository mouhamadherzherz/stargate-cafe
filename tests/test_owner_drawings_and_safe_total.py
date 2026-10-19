import unittest
import os
import sqlite3
import tempfile
import database
import accounting
import app

class TestOwnerDrawingsAndSafeTotal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_db_path = os.path.join(cls.temp_dir.name, 'test_drawings_safe.db')
        cls.orig_db_dir = database.DB_DIR
        cls.orig_db_path = database.DB_PATH
        cls.orig_acct_path = getattr(accounting, 'DB_PATH', None)

        database.DB_DIR = cls.temp_dir.name
        database.DB_PATH = cls.test_db_path
        accounting.DB_PATH = cls.test_db_path
        database.init_db()

        accounting.update_settings({'setup_complete': '1', 'exchange_rate': 89500.0})

        conn = database.get_db()
        cur = conn.cursor()
        cur.execute("UPDATE settings SET setup_complete = '1' WHERE id = 1")
        cur.execute("INSERT OR IGNORE INTO employees (id, name, username, password, pin, role, is_active) VALUES (1, 'المدير العام', 'admin', '1234', '1234', 'admin', 1)")
        conn.commit()
        conn.close()

        app.app.config['TESTING'] = True
        app.app.config['SECRET_KEY'] = 'test-secret'
        app.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        database.DB_DIR = cls.orig_db_dir
        database.DB_PATH = cls.orig_db_path
        if cls.orig_acct_path:
            accounting.DB_PATH = cls.orig_acct_path
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def setUp(self):
        self.conn = database.get_db()

    def tearDown(self):
        self.conn.close()

    def _add_cash_to_drawer(self, amount_lbp=2000000.0):
        items = [{'item_name': 'قهوة تركي', 'quantity': 10, 'price_lbp': amount_lbp / 10.0, 'subtotal_lbp': amount_lbp, 'item_type': 'cafe'}]
        order_data = {
            'order_type': 'dine_in',
            'payment_method': 'cash',
            'subtotal_lbp': amount_lbp,
            'total_lbp': amount_lbp,
            'cashier_name': 'المدير العام',
            'employee_id': 1
        }
        ok, res = accounting.create_order(order_data, items)
        self.assertTrue(ok, f"فشل إنشاء الطلب: {res}")
        return res['order_id']

    def test_01_owner_drawing_deducts_from_drawer_immediately(self):
        """التحقق من أن سحب أرباح المالك من الدرج يخصم فوراً من كاش الدرج دون التأثير على مصاريف التشغيل"""
        self._add_cash_to_drawer(2000000.0)

        status_before = accounting.get_drawer_cash_status()
        self.assertGreaterEqual(status_before['total_untransferred_lbp'], 2000000.0)
        drawer_before = status_before['total_untransferred_lbp']

        # سحب أرباح نهاية الشهر بقيمة 500,000 ل.ل من الدرج
        draw_res = accounting.record_owner_drawing(
            amount_lbp=500000.0,
            source='drawer',
            drawing_type='monthly_profit',
            month_period='2026-10',
            drawn_by='المدير العام',
            notes='سحب أرباح نهاية شهر أكتوبر'
        )
        self.assertTrue(draw_res['success'])
        self.assertEqual(draw_res['amount_lbp'], 500000.0)

        # التحقق من أن رصيد الدرج نزل بالتمام 500,000 ل.ل فوراً
        status_after = accounting.get_drawer_cash_status()
        self.assertEqual(status_after['total_untransferred_lbp'], drawer_before - 500000.0)

        # التحقق من أن مصاريف التشغيل لم تتأثر إطلاقاً
        expenses = accounting.get_expenses()
        self.assertEqual(len(expenses), 0, "يجب ألا تسجل مسحوبات المالك كمصروف تشغيلي")

    def test_02_owner_drawing_double_entry_and_equity(self):
        """التحقق من القيد المزدوج المحاسبي لحساب 3030 (مسحوبات المالك)"""
        drawings = accounting.get_owner_drawings(month_period='2026-10')
        self.assertGreaterEqual(len(drawings), 1)

        conn = database.get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT SUM(debit_lbp), SUM(credit_lbp)
            FROM journal_entry_lines
            WHERE account_code = '3030'
        """)
        row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertGreaterEqual(row[0], 500000.0)

    def test_03_cancel_owner_drawing_reverses_balance(self):
        """التحقق من أن إلغاء سحب الأرباح يعيد الرصيد فوراً إلى الدرج"""
        status_before = accounting.get_drawer_cash_status()
        bal_before = status_before['total_untransferred_lbp']
        self.assertGreaterEqual(bal_before, 200000.0)

        # سحب 200,000 ل.ل
        draw_res = accounting.record_owner_drawing(
            amount_lbp=200000.0,
            source='drawer',
            drawing_type='personal',
            drawn_by='المدير العام',
            notes='سحب تجريبي للإلغاء'
        )
        drawing_id = draw_res['drawing_id']
        self.assertEqual(accounting.get_drawer_cash_status()['total_untransferred_lbp'], bal_before - 200000.0)

        # إلغاء السحب
        ok = accounting.cancel_owner_drawing(drawing_id=drawing_id, cancelled_by='المدير العام', reason='إلغاء تجريبي')
        self.assertTrue(ok)

        # التحقق من عودة الرصيد كاملاً
        status_restored = accounting.get_drawer_cash_status()
        self.assertEqual(status_restored['total_untransferred_lbp'], bal_before)

    def test_04_safe_transfer_100_percent_zeros_drawer_cleanly(self):
        """التحقق من أن نقل 100% من كاش الدرج للخزنة يصفر الدرج تماماً وبدقة 0 ل.ل دون أي باقي"""
        drawer_stat = accounting.get_drawer_cash_status()
        avail_lbp = drawer_stat['total_untransferred_lbp']
        self.assertGreater(avail_lbp, 0.0)

        # ترحيل كامل الكاش المتراكم
        transfer_res = accounting.transfer_drawer_total_to_safe(transferred_by='المدير العام')
        self.assertTrue(transfer_res['success'])
        self.assertEqual(transfer_res['amount_lbp'], avail_lbp)

        # فحص رصيد الدرج بعد الترحيل الكامل: يجب أن يكون 0.0 ل.ل بالتمام
        drawer_after = accounting.get_drawer_cash_status()
        self.assertEqual(drawer_after['total_untransferred_lbp'], 0.0, "رصيد الدرج يجب أن يكون مصفراً 0 ل.ل بعد نقل 100%")

    def test_05_live_summary_api(self):
        """التحقق من استجابة API الملخص اللحظي الشامل"""
        with self.client.session_transaction() as sess:
            sess['employee_id'] = 1
            sess['employee_name'] = 'المدير العام'
            sess['employee_role'] = 'admin'
            sess['is_admin'] = True
            sess['admin_authenticated'] = True

        resp = self.client.get('/api/reports/live_summary')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertIn('money', data)
        self.assertIn('sales', data)
        self.assertIn('inventory', data)
        self.assertIn('drawer_cash_lbp', data['money'])
        self.assertIn('safe_balance_lbp', data['money'])
        self.assertEqual(data['money']['drawer_cash_lbp'], 0.0)

    def test_06_transfer_and_zero_all(self):
        """التحقق من ترحيل وتصفير جميع الأموال ونقلها للخزنة وتصفير كافة العدادات"""
        self._add_cash_to_drawer(1800000.0)
        drawer_before = accounting.get_drawer_cash_status()
        self.assertGreater(drawer_before['total_untransferred_lbp'], 0.0)

        with self.client.session_transaction() as sess:
            sess['employee_id'] = 1
            sess['employee_name'] = 'المدير العام'
            sess['employee_role'] = 'admin'
            sess['is_admin'] = True
            sess['admin_authenticated'] = True

        resp = self.client.post('/safe/transfer_and_zero_all', json={'note': 'اختبار ترحيل وتصفير كل شيء'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['drawer_remaining_lbp'], 0.0)

        # التحقق من أن جميع عدادات الكاش بالدرج أصبحت 0
        drawer_after = accounting.get_drawer_cash_status()
        self.assertEqual(drawer_after['total_untransferred_lbp'], 0.0)
        self.assertEqual(drawer_after['untransferred_cafe_lbp'], 0.0)
        self.assertEqual(drawer_after['untransferred_pc_lbp'], 0.0)

if __name__ == '__main__':
    unittest.main()
