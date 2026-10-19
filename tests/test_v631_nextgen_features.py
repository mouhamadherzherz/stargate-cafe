# -*- coding: utf-8 -*-
"""
Tests for STARGATE CAFE v6.3.1 Next-Generation Features:
- Role-Based Access Control (RBAC 7 roles)
- Periodic Physical Stocktaking & Variance Tracking
- Product Price History Tracking
- Barcode Lookup
- AI Business Intelligence & Anomaly Query Engine
- 20 Core Comprehensive Reports Hub
"""

import unittest
import os
import json
import sqlite3
from unittest.mock import patch

# Configure testing environment
os.environ['TESTING'] = '1'
import app
import accounting
import permissions
import database

class TestV631NextGenFeatures(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.app.config['TESTING'] = True
        app.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.app.test_client()

    def setUp(self):
        # Create fresh test session
        with self.client.session_transaction() as sess:
            sess.clear()

    def test_01_rbac_permissions_matrix(self):
        """Verify 7 distinct roles and their permission assignments."""
        roles = permissions.get_all_roles()
        self.assertEqual(len(roles), 7)
        self.assertIn('owner', roles)
        self.assertIn('admin', roles)
        self.assertIn('shift_manager', roles)
        self.assertIn('accountant', roles)
        self.assertIn('cashier', roles)
        self.assertIn('inventory_keeper', roles)
        self.assertIn('auditor', roles)

        # Admin and Owner have all permissions
        self.assertTrue(permissions.has_permission('owner', 'stocktaking.approve'))
        self.assertTrue(permissions.has_permission('admin', 'safe.transfer'))

        # Cashier only has POS & Shift permissions, blocked from stocktaking approval and safe transfer
        self.assertTrue(permissions.has_permission('cashier', 'pos.access'))
        self.assertFalse(permissions.has_permission('cashier', 'stocktaking.approve'))
        self.assertFalse(permissions.has_permission('cashier', 'safe.transfer'))
        self.assertFalse(permissions.has_permission('cashier', 'audit.view'))

        # Inventory keeper can conduct stocktaking but cannot transfer safe cash
        self.assertTrue(permissions.has_permission('inventory_keeper', 'stocktaking.conduct'))
        self.assertFalse(permissions.has_permission('inventory_keeper', 'safe.transfer'))

        # Auditor is read-only
        self.assertTrue(permissions.has_permission('auditor', 'reports.view'))
        self.assertFalse(permissions.has_permission('auditor', 'orders.create'))
        self.assertFalse(permissions.has_permission('auditor', 'safe.transfer'))

    def test_02_stocktaking_session_lifecycle(self):
        """Verify end-to-end stocktaking: creation, count update, variance calc, and finalization."""
        # 1. Create a stocktaking session
        res = accounting.create_stocktaking_session(notes='اختبار الجرد الفعلي', employee_id=1, employee_name='مدير الجرد')
        self.assertTrue(res['success'])
        session_id = res['session_id']
        session_code = res['session_code']
        self.assertTrue(session_code.startswith('STK-'))

        # 2. Get details
        details = accounting.get_stocktaking_session_details(session_id)
        self.assertIsNotNone(details)
        self.assertEqual(details['status'], 'draft')
        self.assertGreater(len(details['items']), 0)

        # Pick the first item
        target_item = details['items'][0]
        it_id = target_item['item_id']
        it_type = target_item['item_type']
        theo_qty = target_item['theoretical_qty']

        # 3. Record counted quantity with a deficit of 2 units
        new_counted = max(0.0, theo_qty - 2.0)
        ok, msg = accounting.update_stocktaking_item_count(
            session_id=session_id,
            item_id=it_id,
            item_type=it_type,
            counted_qty=new_counted,
            reason='عجز تجريبي معتمد'
        )
        self.assertTrue(ok)

        # Verify variance calculation
        updated_details = accounting.get_stocktaking_session_details(session_id)
        updated_item = [i for i in updated_details['items'] if i['item_id'] == it_id and i['item_type'] == it_type][0]
        self.assertEqual(updated_item['actual_counted_qty'], new_counted)
        self.assertEqual(updated_item['difference_qty'], new_counted - theo_qty)

        # 4. Finalize stocktaking session
        fin_ok, fin_msg = accounting.finalize_stocktaking_session(session_id, approved_by_id=1, approved_by_name='المدير العام')
        self.assertTrue(fin_ok)

        # Verify finalized status and cannot finalize again
        again_ok, again_msg = accounting.finalize_stocktaking_session(session_id, approved_by_id=1, approved_by_name='المدير العام')
        self.assertFalse(again_ok)

        # Verify stock movement was recorded
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM stock_movements 
            WHERE reference_type = 'stocktaking_session' AND reference_id = ?
        """, (session_id,))
        movements = cursor.fetchall()
        conn.close()
        self.assertGreaterEqual(len(movements), 1)

    def test_03_price_change_logging(self):
        """Verify product price change is logged with previous and updated figures."""
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, price_lbp, price_usd FROM cafe_items LIMIT 1")
        item = cursor.fetchone()
        conn.close()
        if not item:
            self.skipTest("No items found in cafe_items")

        it_id = item['id']
        it_name = item['name']
        old_lbp = item['price_lbp'] or 100000.0
        new_lbp = old_lbp + 25000.0

        accounting.log_price_change(
            item_id=it_id,
            item_name=it_name,
            old_lbp=old_lbp,
            new_lbp=new_lbp,
            old_usd=1.0,
            new_usd=1.25,
            changed_by='مسؤول التسعير',
            reason='زيادة تكلفة المواد الخام'
        )

        history = accounting.get_price_change_history(item_id=it_id, limit=5)
        self.assertGreaterEqual(len(history), 1)
        latest = history[0]
        self.assertEqual(latest['item_id'], it_id)
        self.assertEqual(latest['old_price_lbp'], old_lbp)
        self.assertEqual(latest['new_price_lbp'], new_lbp)
        self.assertEqual(latest['changed_by'], 'مسؤول التسعير')

    def test_04_ai_business_assistant_queries(self):
        """Verify AI Business Assistant answers top selling, low stock, and shift discrepancies."""
        # Top selling query
        res1 = accounting.ai_business_assistant_query("ما هي المنتجات الأكثر مبيعاً؟")
        self.assertTrue(res1['success'])
        self.assertEqual(res1['topic'], 'top_selling')

        # Low stock query
        res2 = accounting.ai_business_assistant_query("ما الأصناف التي تحتاج إلى إعادة طلب؟")
        self.assertTrue(res2['success'])
        self.assertIn(res2['topic'], ['inventory_health', 'low_stock_alerts'])

        # Debts query
        res3 = accounting.ai_business_assistant_query("ما الديون غير المسددة للزبائن؟")
        self.assertTrue(res3['success'])
        self.assertEqual(res3['topic'], 'debts_overview')

        # Anomalies query
        res4 = accounting.ai_business_assistant_query("فحص العمليات غير المعتادة")
        self.assertTrue(res4['success'])
        self.assertEqual(res4['topic'], 'anomaly_detection')

    def test_05_comprehensive_reports_hub(self):
        """Verify 20 core reports hub aggregates sales, payment methods, cancellations, and P&L."""
        hub = accounting.get_comprehensive_reports_hub()
        self.assertIn('sales_overview', hub)
        self.assertIn('payment_methods', hub)
        self.assertIn('cancellations', hub)
        self.assertIn('expenses_by_cat', hub)
        self.assertIn('pnl_summary', hub)
        self.assertIn('gross_profit_lbp', hub['pnl_summary'])
        self.assertIn('net_profit_lbp', hub['pnl_summary'])

    def test_06_barcode_lookup_api(self):
        """Verify barcode and SKU lookup returns 404 for non-existent and item for matching barcode."""
        with self.client.session_transaction() as sess:
            sess['employee_id'] = 1
            sess['employee_name'] = 'Admin'
            sess['employee_role'] = 'admin'

        # Non existent
        resp = self.client.get('/api/items/barcode-lookup?code=NONEXISTENT_BARCODE_999999')
        self.assertEqual(resp.status_code, 404)

        # Set barcode on an existing item and lookup
        conn = database.get_db()
        cursor = conn.cursor()
        first_item = cursor.execute("SELECT id FROM cafe_items LIMIT 1").fetchone()
        self.assertIsNotNone(first_item)
        target_id = first_item['id']
        cursor.execute("UPDATE cafe_items SET barcode = '1234567890123' WHERE id = ?", (target_id,))
        conn.commit()
        conn.close()

        resp2 = self.client.get('/api/items/barcode-lookup?code=1234567890123')
        self.assertEqual(resp2.status_code, 200)
        data = json.loads(resp2.data.decode('utf-8'))
        self.assertTrue(data['success'])
        self.assertEqual(data['item']['id'], target_id)

if __name__ == '__main__':
    unittest.main()
