# -*- coding: utf-8 -*-
import unittest
import os
import sqlite3
import database
import accounting

class TestCoffeeAndSafeRestoration(unittest.TestCase):
    def setUp(self):
        # Initialize database
        database.init_db()
        self.conn = database.get_db()

    def tearDown(self):
        self.conn.close()

    def test_coffee_cup_restored_on_order_cancel(self):
        """التحقق الحاسم من عودة فنجان القهوة للكيس المفتوح والإنتاجية عند إلغاء الفاتورة"""
        # 1. Ensure an active coffee bag batch exists
        ok_bag, bag_info = accounting.open_coffee_bag(
            cost_kg_lbp=1163500.0,
            cost_kg_usd=13.0,
            employee_name='فاحص الجودة',
            notes='كيس فحص استرجاع القهوة',
            auto_close_previous=True
        )
        self.assertTrue(ok_bag, "فشل فتح كيس القهوة")
        active_b = accounting.get_active_coffee_batch()
        self.assertIsNotNone(active_b, "لا يوجد كيس قهوة نشط")
        batch_id = active_b['id']
        initial_sold = int(active_b.get('cups_sold') or 0)

        # 2. Get or create a Turkish coffee item
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name FROM cafe_items WHERE name LIKE '%قهوة تركي%' LIMIT 1")
        row = cursor.fetchone()
        if not row:
            cursor.execute("""
                INSERT INTO cafe_items (name, price_lbp, price_usd, is_coffee_bean_linked, track_stock, stock_qty)
                VALUES ('قهوة تركي مخصوص فحص', 60000.0, 0.67, 1, 1, 50.0)
            """)
            self.conn.commit()
            item_id = cursor.lastrowid
            item_name = 'قهوة تركي مخصوص فحص'
        else:
            item_id = row['id']
            item_name = row['name']

        # 3. Create an order with 3 cups of coffee
        order_data = {
            'customer_name': 'زبون تجربة القهوة',
            'payment_method': 'cash',
            'employee_name': 'الكاشير'
        }
        items = [
            {
                'item_id': item_id,
                'name': item_name,
                'price_lbp': 60000.0,
                'price_usd': 0.67,
                'quantity': 3,
                'item_type': 'cafe'
            }
        ]
        ok_order, order_res = accounting.create_order(order_data, items)
        self.assertTrue(ok_order, f"فشل إنشاء الطلب: {order_res}")
        order_id = order_res if isinstance(order_res, int) else order_res.get('order_id')

        # 4. Verify coffee bag cups_sold increased by 3
        active_after_sale = accounting.get_active_coffee_batch()
        self.assertEqual(int(active_after_sale['cups_sold']), initial_sold + 3, "لم يتم خصم فناجين القهوة عند البيع")

        # 5. Cancel the order
        canc_ok, canc_msg = accounting.cancel_order(order_id, cancelled_by='المدير', reason='تجربة استرجاع فنجان القهوة')
        self.assertTrue(canc_ok, f"فشل إلغاء الطلب: {canc_msg}")

        # 6. Verify coffee bag cups_sold is restored back to initial_sold!
        active_after_cancel = accounting.get_active_coffee_batch()
        self.assertEqual(int(active_after_cancel['cups_sold']), initial_sold, "فنجان القهوة لم يعد إلى مكانه في الكيس بعد الإلغاء!")

    def test_drawer_cash_instant_deduction_on_safe_transfer(self):
        """التحقق من أن ترحيل الكاش للخزنة يخصم فورياً من كاش الدرج دون تعليق"""
        # 1. Get initial drawer status
        initial_status = accounting.get_drawer_cash_status()
        initial_untransferred = float(initial_status.get('total_untransferred_lbp') or 0.0)

        # 2. Perform a safe transfer of 100,000 LBP from drawer to safe
        transfer_amount = 100000.0
        tid = accounting.add_safe_transfer(
            amount_lbp=transfer_amount,
            note='فحص الترحيل الفوري للخزنة',
            transferred_by='كاشير الفحص',
            source='drawer',
            target='safe',
            operation_type='deposit'
        )
        self.assertIsNotNone(tid, "فشل تسجيل حركة الترحيل للخزنة")

        # 3. Check drawer status immediately after transfer
        new_status = accounting.get_drawer_cash_status()
        new_untransferred = float(new_status.get('total_untransferred_lbp') or 0.0)

        # The drawer cash MUST decrease by transfer_amount
        expected_cash = max(0.0, initial_untransferred - transfer_amount)
        self.assertEqual(new_untransferred, expected_cash, "كاش الدرج لم يخصم فوراً وبقي معلقاً بعد الترحيل!")

if __name__ == '__main__':
    unittest.main()
