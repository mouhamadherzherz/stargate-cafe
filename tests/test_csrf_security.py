# -*- coding: utf-8 -*-
"""
STARGATE CAFE — Operational CSRF & Session Security Test Suite
Thoroughly tests CSRF token handling, validation, and attack defense across:
1. Initial login forms (exempt to establish session)
2. Valid Form Token submission (Accepted)
3. Valid Header Token ('X-CSRFToken' & 'X-CSRF-Token') (Accepted)
4. Valid JSON Body Token (Accepted)
5. Cross-Origin Forgery (Origin: http://evil.com) (403 Forbidden)
6. API JSON endpoint with forged/mismatched token (JSON 403 Forbidden)
7. Desktop WebView same-origin loopback handling (Accepted)
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
from app import app


class StargateCSRFSecurityTests(unittest.TestCase):
    """Operational verification of CSRF defenses and session integrity."""

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-audit-security-secret-key-12345'
        cls.client = app.test_client()

    def setUp(self):
        self.test_db_fd, self.test_db_path = tempfile.mkstemp(suffix='_csrf_test.db')
        database.DB_PATH = self.test_db_path
        database.DB_DIR = os.path.dirname(self.test_db_path)
        database.init_db(seed_items=False)

        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET setup_complete = 1 WHERE id = 1")
        cursor.execute("""
            INSERT INTO employees (name, role, password, pin, password_is_hashed, is_active)
            VALUES ('مدير الأمان', 'admin', ?, ?, 1, 1)
        """, (database.hash_password('adminpass'), database.hash_password('9999')))
        self.admin_id = cursor.lastrowid
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            if hasattr(self, 'test_db_path') and os.path.exists(self.test_db_path):
                os.close(self.test_db_fd)
                os.remove(self.test_db_path)
        except Exception:
            pass

    def test_login_endpoints_accessible_without_prior_csrf_token(self):
        """Initial authentication requests must be permitted to establish user session."""
        resp = self.client.post('/login', data={'pin': '9999'}, follow_redirects=False)
        # Login endpoint must process PIN and not block on CSRF (status 200 or 302 redirect)
        self.assertIn(resp.status_code, (200, 302))

    def test_post_with_valid_form_csrf_token_accepted(self):
        """Form POST with valid CSRF token in form data must be accepted."""
        token = secrets.token_hex(24)
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = token
            sess['employee_id'] = self.admin_id
            sess['employee_name'] = 'مدير الأمان'
            sess['employee_role'] = 'admin'
            sess['is_admin'] = True

        resp = self.client.post(
            '/menu/category/add',
            data={'name': 'قسم تجريبي للـ CSRF', 'csrf_token': token},
            headers={'Origin': 'http://localhost'},
            follow_redirects=False
        )
        # Should succeed (redirect 302 to categories list), NOT 403 Forbidden
        self.assertNotEqual(resp.status_code, 403)
        self.assertEqual(resp.status_code, 302)

    def test_post_with_valid_header_csrf_token_accepted(self):
        """AJAX/Fetch POST with valid X-CSRFToken header must be accepted."""
        token = secrets.token_hex(24)
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = token
            sess['employee_id'] = self.admin_id
            sess['is_admin'] = True

        resp = self.client.post(
            '/api/ai/chat',
            json={'message': 'كم المبيعات؟'},
            headers={
                'X-CSRFToken': token,
                'Origin': 'http://localhost'
            }
        )
        self.assertNotEqual(resp.status_code, 403)
        self.assertEqual(resp.status_code, 200)

    def test_post_json_with_valid_body_csrf_token_accepted(self):
        """JSON POST with valid csrf_token in JSON payload must be accepted."""
        token = secrets.token_hex(24)
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = token
            sess['employee_id'] = self.admin_id
            sess['is_admin'] = True

        resp = self.client.post(
            '/api/ai/chat',
            json={'message': 'تقرير اليوم', 'csrf_token': token},
            headers={'Origin': 'http://localhost'}
        )
        self.assertNotEqual(resp.status_code, 403)
        self.assertEqual(resp.status_code, 200)

    def test_forged_cross_origin_post_rejected_with_403(self):
        """POST from malicious external origin with invalid/missing token must return 403."""
        token = secrets.token_hex(24)
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = token
            sess['employee_id'] = self.admin_id
            sess['is_admin'] = True

        # Malicious site forged request with fake token
        resp = self.client.post(
            '/api/ai/chat',
            json={'message': 'سرقة بيانات'},
            headers={
                'Origin': 'http://malicious-hacker-site.org',
                'Referer': 'http://malicious-hacker-site.org/attack.html',
                'X-CSRFToken': 'fake-tampered-token-xyz'
            }
        )
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertIn('CSRF', data.get('error', ''))

    def test_desktop_webview_same_origin_token_flow(self):
        """Desktop WebView running on localhost with matching origin and token must succeed."""
        token = secrets.token_hex(24)
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = token
            sess['employee_id'] = self.admin_id
            sess['is_admin'] = True

        resp = self.client.post(
            '/api/ai/chat',
            json={'message': 'حالة النظام'},
            headers={
                'Origin': 'http://localhost',
                'X-CSRFToken': token
            }
        )
        self.assertEqual(resp.status_code, 200)


if __name__ == '__main__':
    unittest.main()
