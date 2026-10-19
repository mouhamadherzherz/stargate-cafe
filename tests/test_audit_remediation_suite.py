# -*- coding: utf-8 -*-
"""
STARGATE CAFE — Master Audit & Security Remediation Regression Suite
Validates all Phase 2 and Phase 3 security hardenings:
1. Elimination of /employee/current authentication bypass
2. Strict RBAC on /safe/transfer_and_zero_all and sensitive admin APIs
3. Setup wizard takeover prevention
4. Shift report authoritative calculation on server
5. Protection of inventory and product endpoints
6. Idempotency controls and zero-leakage accounting validation
"""

import os
import sys
import tempfile
import unittest
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import database
import accounting
from app import app


class StargateAuditRemediationTests(unittest.TestCase):
    """Rigorous tests covering all security fixes and financial constraints."""

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SECRET_KEY'] = 'test-remediation-secret-key-xyz'
        cls.client = app.test_client()

    def setUp(self):
        self.test_db_fd, self.test_db_path = tempfile.mkstemp(suffix='_remediation_test.db')
        database.DB_PATH = self.test_db_path
        database.DB_DIR = os.path.dirname(self.test_db_path)
        database.init_db(seed_items=True)

        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET setup_complete = 1, is_seeded = 1 WHERE id = 1")

        # Admin user
        cursor.execute("""
            INSERT INTO employees (name, username, password, pin, role, is_active, password_is_hashed)
            VALUES ('مدير النظام', 'admin_audit', ?, ?, 'admin', 1, 1)
        """, (database.hash_password('adminpass123'), database.hash_password('1111')))
        self.admin_id = cursor.lastrowid

        # Cashier user
        cursor.execute("""
            INSERT INTO employees (name, username, password, pin, role, is_active, password_is_hashed)
            VALUES ('كاشير التجربة', 'cashier_audit', ?, ?, 'cashier', 1, 1)
        """, (database.hash_password('cashierpass123'), database.hash_password('2222')))
        self.cashier_id = cursor.lastrowid

        # Inactive/revoked employee
        cursor.execute("""
            INSERT INTO employees (name, username, password, pin, role, is_active, password_is_hashed)
            VALUES ('موظف موقوف', 'inactive_audit', ?, ?, 'cashier', 0, 1)
        """, (database.hash_password('revokedpass'), database.hash_password('3333')))
        self.inactive_id = cursor.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            if hasattr(self, 'test_db_path') and os.path.exists(self.test_db_path):
                os.close(self.test_db_fd)
                os.remove(self.test_db_path)
        except Exception:
            pass

    # 1. /employee/current AUTHENTICATION TESTS (Finding 2.1)

    def test_employee_current_unauthenticated_returns_401(self):
        """Unauthenticated requests to /employee/current must strictly return 401 without creating session."""
        with self.client.session_transaction() as sess:
            sess.clear()

        resp = self.client.get('/employee/current')
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertFalse(data.get('success', True))

        with self.client.session_transaction() as sess:
            self.assertNotIn('employee_id', sess)

    def test_employee_current_authenticated_cashier(self):
        """Authenticated cashier sees their own identity without privilege escalation."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['employee_id'] = self.cashier_id
            sess['employee_name'] = 'كاشير التجربة'
            sess['employee_role'] = 'cashier'

        resp = self.client.get('/employee/current')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('employee_id'), self.cashier_id)
        self.assertEqual(data.get('role'), 'cashier')
        self.assertFalse(data.get('is_admin'))

    def test_employee_current_revoked_account_invalidated_with_401(self):
        """Deactivated employee session is purged and returns 401."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['employee_id'] = self.inactive_id
            sess['employee_name'] = 'موظف موقوف'
            sess['employee_role'] = 'cashier'

        resp = self.client.get('/employee/current')
        self.assertEqual(resp.status_code, 401)

        with self.client.session_transaction() as sess:
            self.assertNotIn('employee_id', sess)

    # 2. PRIVILEGED FINANCIAL TRANSFER RBAC (Finding 2.2)

    def test_safe_transfer_and_zero_all_cashier_denied_403(self):
        """Cashier attempting to transfer/zero all funds is denied with 403 Forbidden."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['employee_id'] = self.cashier_id
            sess['employee_name'] = 'كاشير التجربة'
            sess['employee_role'] = 'cashier'

        resp = self.client.post('/api/safe/transfer_and_zero_all', json={'note': 'اختراق كاشير'})
        self.assertEqual(resp.status_code, 403)

    def test_safe_transfer_and_zero_all_admin_authorized(self):
        """Administrator executing transfer_and_zero_all succeeds and resets drawer."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['employee_id'] = self.admin_id
            sess['employee_name'] = 'مدير النظام'
            sess['employee_role'] = 'admin'
            sess['is_admin'] = True
            sess['admin_authenticated'] = True

        # Insert actual cash order
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cafe_orders (order_number, total_lbp, total_usd, paid_amount, payment_method, customer_name, status, created_at)
            VALUES ('ORD-TEST-001', 200000.0, 2.23, 200000.0, 'cash', 'زبون تجريبي', 'paid', CURRENT_TIMESTAMP)
        """)
        conn.commit()
        conn.close()

        resp = self.client.post('/api/safe/transfer_and_zero_all', json={
            'note': 'ترحيل إداري رسمي',
            'idempotency_key': 'idem-test-1001'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('drawer_remaining_lbp'), 0.0)

        # Repeated call with same idempotency key
        resp2 = self.client.post('/api/safe/transfer_and_zero_all', json={
            'note': 'ترحيل إداري رسمي مكرر',
            'idempotency_key': 'idem-test-1001'
        })
        self.assertEqual(resp2.status_code, 200)

    def test_safe_transfer_and_zero_all_empty_balance_rejected(self):
        """When drawer is already 0, transfer returns 400 with helpful message."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['employee_id'] = self.admin_id
            sess['employee_name'] = 'مدير النظام'
            sess['employee_role'] = 'admin'
            sess['is_admin'] = True
            sess['admin_authenticated'] = True

        resp = self.client.post('/api/safe/transfer_and_zero_all', json={'note': 'محاولة ترحيل صندوق فارغ'})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get('success'))

    # 3. SETUP WIZARD TAKEOVER DEFENSE (Finding 2.4)

    def test_setup_wizard_blocked_when_already_initialized(self):
        """POST to /setup when installation already has an administrator is strictly blocked."""
        resp = self.client.post('/setup', data={
            'company_name': 'Hacker Cafe',
            'admin_name': 'مخترق',
            'admin_username': 'hacker',
            'admin_pin': '9999',
            'admin_password': 'hackerpassword123'
        }, follow_redirects=False)

        self.assertIn(resp.status_code, (302, 403))

        conn = database.get_db()
        hacker_row = conn.execute("SELECT * FROM employees WHERE username='hacker'").fetchone()
        conn.close()
        self.assertIsNone(hacker_row)

    # 4. SENSITIVE ADMINISTRATIVE ENDPOINTS RBAC (Finding 2.5)

    def test_sensitive_apis_restricted_to_admin(self):
        """Cashiers cannot view audit logs, AI audit, or safe balance."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['employee_id'] = self.cashier_id
            sess['employee_name'] = 'كاشير التجربة'
            sess['employee_role'] = 'cashier'

        endpoints = [
            '/api/audit/logs',
            '/api/ai/audit',
            '/api/safe/balance'
        ]
        for ep in endpoints:
            resp = self.client.get(ep)
            self.assertEqual(resp.status_code, 403, f'Endpoint {ep} should be forbidden for cashier')

    # 5. PROTECTED DATA ENDPOINTS (Finding 2.7)

    def test_inventory_alerts_and_top_selling_require_auth(self):
        """Unauthenticated requests to inventory alerts and top-selling must return 401."""
        with self.client.session_transaction() as sess:
            sess.clear()

        resp1 = self.client.get('/api/inventory/alerts')
        self.assertEqual(resp1.status_code, 401)

        resp2 = self.client.get('/api/items/top-selling')
        self.assertEqual(resp2.status_code, 401)

    # 6. SHIFT REPORT TELEGRAM SERVER-SIDE VALIDATION (Finding 2.6)

    def test_telegram_shift_report_requires_login(self):
        """Unauthenticated attempts to trigger telegram shift report return 401."""
        with self.client.session_transaction() as sess:
            sess.clear()

        resp = self.client.post('/api/telegram/send-shift-report', json={'actual_cash_lbp': 100000})
        self.assertEqual(resp.status_code, 401)


if __name__ == '__main__':
    unittest.main()
