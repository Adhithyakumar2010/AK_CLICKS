import secrets
import os
import sys
import unittest
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db, db_connection, validate_password_strength, is_rate_limited

class TestSecurity(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()
        with db_connection() as conn:
            conn.execute("DELETE FROM bookings")
            conn.execute("DELETE FROM customers")
            conn.commit()

    def _get_csrf_token(self, client):
        res = client.get('/')
        match = re.search(r'name="csrf_token" value="([^"]+)"', res.data.decode('utf-8'))
        if match:
            return match.group(1)
        with client.session_transaction() as sess:
            return sess.get('csrf_token', '')

    def test_01_security_headers(self):
        """Verify essential security headers are attached to responses"""
        res = self.client.get('/')
        self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("Content-Security-Policy", res.headers)
        csp = res.headers.get("Content-Security-Policy")
        self.assertIn("https://fonts.googleapis.com", csp)

    def test_02_password_strength_validator(self):
        """Test password strength rules (min 8 chars, upper, lower, digit, special)"""
        valid, msg = validate_password_strength("Short1!")
        self.assertFalse(valid)

        valid, msg = validate_password_strength("alllowercase1!")
        self.assertFalse(valid)

        valid, msg = validate_password_strength("ALLUPPERCASE1!")
        self.assertFalse(valid)

        valid, msg = validate_password_strength("NoDigitsHere!")
        self.assertFalse(valid)

        valid, msg = validate_password_strength("NoSpecial1234")
        self.assertFalse(valid)

        valid, msg = validate_password_strength("StrongP@ssw0rd")
        self.assertTrue(valid)

    def test_03_rate_limiter(self):
        """Verify sensible rate limiter blocks excessive requests"""
        test_ip = "192.168.1.99"
        endpoint = "login_test"
        for _ in range(30):
            self.assertFalse(is_rate_limited(test_ip, endpoint, max_requests=30, window_seconds=60))
        self.assertTrue(is_rate_limited(test_ip, endpoint, max_requests=30, window_seconds=60))

    def test_04_session_cookie_security(self):
        """Verify HttpOnly and SameSite cookie configurations"""
        self.assertTrue(app.config.get("SESSION_COOKIE_HTTPONLY"))
        self.assertEqual(app.config.get("SESSION_COOKIE_SAMESITE"), "Lax")

    def test_05_xss_content_escaping(self):
        """Verify user inputs in search are safely escaped"""
        xss_input = "<script>alert('xss')</script>"
        with self.client.session_transaction() as sess:
            sess['admin'] = True
        res = self.client.get(f"/admin/customers?q={xss_input}")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("<script>alert('xss')</script>", res.data.decode('utf-8'))

    def test_06_csrf_protection_missing_token(self):
        """Verify missing CSRF token on state-changing POST requests returns 403"""
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            res = self.client.post('/booking/select-date', data={'booking_date': '2026-09-01'})
            self.assertEqual(res.status_code, 403)

            with self.client.session_transaction() as sess:
                sess['customer_id'] = 1

            res_cancel = self.client.post('/customer/booking/1/cancel')
            self.assertEqual(res_cancel.status_code, 403)
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

    def test_07_csrf_protection_invalid_token(self):
        """Verify invalid CSRF token on state-changing POST requests returns 403"""
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            token = self._get_csrf_token(self.client)
            with self.client.session_transaction() as sess:
                sess['customer_id'] = 1

            res = self.client.post('/customer/booking/1/cancel', data={'csrf_token': 'invalid_token_999'})
            self.assertEqual(res.status_code, 403)
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

    def test_08_csrf_protection_valid_token(self):
        """Verify valid CSRF token allows state-changing POST requests to succeed"""
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            client = app.test_client()
            client.get('/')

            with client.session_transaction() as sess:
                token = sess.get('csrf_token')

            res = client.post('/booking/select-date', data={'booking_date': '2029-11-20', 'csrf_token': token})
            self.assertIn(res.status_code, (200, 302))
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

    def test_09_idor_customer_access_other_booking(self):
        """Verify Customer B cannot access or view Customer A's booking or receipt"""
        conn = db_connection()
        conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('customerA@test.com', 'CustA', 'hash')")
        conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('customerB@test.com', 'CustB', 'hash')")
        cust_b_id = conn.execute("SELECT id FROM customers WHERE email='customerB@test.com'").fetchone()['id']
        conn.execute("INSERT OR REPLACE INTO bookings (name, email, phone, service, booking_date, status) VALUES ('CustA', 'customerA@test.com', '1111111111', 'Wedding', '2026-12-15', 'Approved')")
        b_id = conn.execute("SELECT id FROM bookings WHERE booking_date='2026-12-15'").fetchone()['id']
        conn.commit()
        conn.close()

        client1 = app.test_client()
        with client1.session_transaction() as sess:
            sess['customer_id'] = cust_b_id
            sess['customer_name'] = 'CustB'

        res_detail = client1.get(f'/customer/booking/{b_id}')
        self.assertEqual(res_detail.status_code, 403)

        client2 = app.test_client()
        with client2.session_transaction() as sess:
            sess['customer_id'] = cust_b_id
            sess['customer_name'] = 'CustB'

        res_receipt = client2.get(f'/receipt/booking/{b_id}.pdf')
        self.assertIn(res_receipt.status_code, (403, 404))

    def test_10_idor_customer_cancel_other_booking(self):
        """Verify Customer B cannot cancel Customer A's booking"""
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            client = app.test_client()
            token = self._get_csrf_token(client)

            conn = db_connection()
            conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('customerA@test.com', 'CustA', 'hash')")
            conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('customerB@test.com', 'CustB', 'hash')")
            cust_b_id = conn.execute("SELECT id FROM customers WHERE email='customerB@test.com'").fetchone()['id']
            conn.execute("INSERT OR REPLACE INTO bookings (name, email, phone, service, booking_date, status) VALUES ('CustA', 'customerA@test.com', '1111111111', 'Wedding', '2026-12-16', 'Approved')")
            b_id = conn.execute("SELECT id FROM bookings WHERE booking_date='2026-12-16'").fetchone()['id']
            conn.commit()
            conn.close()

            with client.session_transaction() as sess:
                sess['customer_id'] = cust_b_id

            res_cancel = client.post(f'/customer/booking/{b_id}/cancel', data={'csrf_token': token})
            self.assertEqual(res_cancel.status_code, 403)
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

    def test_11_idor_customer_reschedule_other_booking(self):
        """Verify Customer B cannot reschedule Customer A's booking"""
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            client = app.test_client()
            token = self._get_csrf_token(client)

            conn = db_connection()
            conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('customerA@test.com', 'CustA', 'hash')")
            conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('customerB@test.com', 'CustB', 'hash')")
            cust_b_id = conn.execute("SELECT id FROM customers WHERE email='customerB@test.com'").fetchone()['id']
            conn.execute("INSERT OR REPLACE INTO bookings (name, email, phone, service, booking_date, status) VALUES ('CustA', 'customerA@test.com', '1111111111', 'Wedding', '2026-12-17', 'Approved')")
            b_id = conn.execute("SELECT id FROM bookings WHERE booking_date='2026-12-17'").fetchone()['id']
            conn.commit()
            conn.close()

            with client.session_transaction() as sess:
                sess['customer_id'] = cust_b_id

            res_resched = client.post(f'/customer/booking/{b_id}/reschedule', data={'new_date': '2026-12-25', 'csrf_token': token})
            self.assertEqual(res_resched.status_code, 403)
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

    def test_12_customer_accessing_admin_denied(self):
        """Verify regular customer cannot access admin pages or admin POST actions"""
        with self.client.session_transaction() as sess:
            sess['customer_id'] = 1
            sess.pop('admin', None)

        res_admin = self.client.get('/admin')
        self.assertIn(res_admin.status_code, (302, 403))

        res_admin_cust = self.client.get('/admin/customers')
        self.assertIn(res_admin_cust.status_code, (302, 403))

        res_admin_action = self.client.post('/booking/1/status', data={'status': 'Approved'})
        self.assertEqual(res_admin_action.status_code, 403)

    def test_13_unauthenticated_access_denied(self):
        """Verify unauthenticated user cannot access customer or admin pages"""
        with self.client.session_transaction() as sess:
            sess.clear()

        res_cust = self.client.get('/customer')
        self.assertIn(res_cust.status_code, (302, 403))

        res_admin = self.client.get('/admin')
        self.assertIn(res_admin.status_code, (302, 403))

if __name__ == '__main__':
    unittest.main()
