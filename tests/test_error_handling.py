import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db, db_connection

class TestErrorHandling(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        with app.app_context():
            init_db()

    def test_01_error_404_page(self):
        """Verify non-existent URL returns clean custom 404 page without tracebacks"""
        client = app.test_client()
        res = client.get('/non-existent-page-12345')
        self.assertEqual(res.status_code, 404)
        self.assertIn('404', res.data.decode('utf-8'))
        self.assertNotIn('Traceback', res.data.decode('utf-8'))
        self.assertNotIn('sqlite3', res.data.decode('utf-8'))

    def test_02_error_403_page(self):
        """Verify forbidden action returns clean custom 403 page without tracebacks"""
        client = app.test_client()
        res = client.get('/admin') # Unauthenticated admin access
        self.assertEqual(res.status_code, 302) # Redirects to login with flash

        # Direct 403 verification via unauthorized customer receipt request
        with db_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('owner_err@test.com', 'Owner', 'hash')")
            conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('attacker_err@test.com', 'Attacker', 'hash')")
            attacker_id = conn.execute("SELECT id FROM customers WHERE email='attacker_err@test.com'").fetchone()['id']
            conn.execute("INSERT INTO bookings (name, email, phone, service, booking_date, status, payment_status) VALUES ('Owner', 'owner_err@test.com', '123', 'Wedding — Essential', '2033-01-01', 'Pending', 'Paid')")
            b_id = conn.execute("SELECT id FROM bookings WHERE booking_date='2033-01-01'").fetchone()['id']
            conn.commit()

        with client.session_transaction() as sess:
            sess['customer_id'] = attacker_id

        res_403 = client.get(f'/receipt/booking/{b_id}.pdf')
        self.assertEqual(res_403.status_code, 403)
        self.assertNotIn('Traceback', res_403.data.decode('utf-8'))

    def test_03_booking_validation_errors(self):
        """Verify booking with missing/invalid fields returns clean flash error messages"""
        client = app.test_client()
        # Invalid package
        res = client.post('/book', data={
            'name': 'Test',
            'email': 'test@test.com',
            'phone': '1234567890',
            'service': 'Wedding Photography',
            'package': 'NonExistentPackage',
            'location': 'Coimbatore'
        })
        self.assertEqual(res.status_code, 302)
        self.assertIn('/#booking', res.headers.get('Location'))

        # Past date selection
        with client.session_transaction() as sess:
            sess['pending_booking'] = {
                'name': 'Test',
                'email': 'test@test.com',
                'phone': '1234567890',
                'service': 'Wedding Photography — Essential',
                'package': 'Essential',
                'location': 'Coimbatore'
            }
        res_past = client.post('/booking/select-date', data={'booking_date': '2020-01-01'})
        self.assertEqual(res_past.status_code, 302)
        self.assertIn('/booking-calendar', res_past.headers.get('Location'))

    def test_04_payment_errors(self):
        """Verify payment errors do not crash server with HTTP 500"""
        client = app.test_client()
        # Invalid method
        with client.session_transaction() as sess:
            sess['pending_booking'] = {
                'name': 'Test',
                'email': 'test_pay_err@test.com',
                'phone': '1234567890',
                'service': 'Wedding Photography',
                'package': 'Essential',
                'location': 'Coimbatore',
                'booking_date': '2033-02-01'
            }
        res_pay = client.post('/booking/payment/confirm', data={'method': 'invalid_method'})
        self.assertEqual(res_pay.status_code, 302)
        self.assertIn('/booking/payment', res_pay.headers.get('Location'))

        # Non-existent booking ID payment page
        res_404 = client.get('/payment/booking/999999')
        self.assertEqual(res_404.status_code, 404)

    def test_05_authentication_error_messages(self):
        """Verify invalid customer login handles errors cleanly without exposing sensitive info"""
        client = app.test_client()
        res = client.post('/account', data={'email': 'nonexistent@test.com', 'password': 'wrongpassword'})
        self.assertIn(res.status_code, (200, 302)) # Clean redirect or render with flash message
        self.assertNotIn('Traceback', res.data.decode('utf-8'))
        self.assertNotIn('SELECT', res.data.decode('utf-8'))

    def test_06_csrf_error_responses(self):
        """Verify missing or invalid CSRF tokens return clean HTTP 403 Forbidden"""
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            client = app.test_client()
            res_missing = client.post('/booking/select-date', data={'booking_date': '2033-03-01'})
            self.assertEqual(res_missing.status_code, 403)

            res_invalid = client.post('/booking/select-date', data={'booking_date': '2033-03-01', 'csrf_token': 'fake_token_123'})
            self.assertEqual(res_invalid.status_code, 403)
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

if __name__ == '__main__':
    unittest.main()
