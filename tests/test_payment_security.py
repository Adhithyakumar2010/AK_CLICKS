import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db, db_connection

class TestPaymentSecurity(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        with app.app_context():
            init_db()
        with db_connection() as conn:
            conn.execute("DELETE FROM bookings")
            conn.execute("DELETE FROM customers")
            conn.commit()

    def tearDown(self):
        app.config['WTF_CSRF_ENABLED'] = False

    def test_01_invalid_payment_method(self):
        """Verify invalid payment method is rejected by server"""
        app.config['WTF_CSRF_ENABLED'] = False
        client = app.test_client()
        client.get('/')

        with client.session_transaction() as sess:
            sess['pending_booking'] = {
                'name': 'Test User',
                'email': 'test_pay01@example.com',
                'phone': '1234567890',
                'service': 'Wedding Photography',
                'package': 'Essential',
                'location': 'Coimbatore',
                'message': 'Test',
                'booking_date': '2032-01-01'
            }

        res = client.post('/booking/payment/confirm', data={'method': 'fake_hack_method'})
        self.assertEqual(res.status_code, 302)
        self.assertIn('/booking/payment', res.headers.get('Location'))

    def test_02_amount_tampering_ignored(self):
        """Verify price/amount supplied by client forms is completely ignored by server"""
        app.config['WTF_CSRF_ENABLED'] = False
        client = app.test_client()
        client.get('/')

        with client.session_transaction() as sess:
            sess['pending_booking'] = {
                'name': 'Tamper Test',
                'email': 'tamper_pay02@example.com',
                'phone': '1234567890',
                'service': 'Wedding Photography',
                'package': 'Premium',
                'location': 'Coimbatore',
                'message': 'Test',
                'booking_date': '2032-01-02'
            }

        # Attempt amount tampering via form payload (sending amount=1 instead of Premium price 18000)
        res = client.post('/booking/payment/confirm', data={
            'method': 'upi',
            'amount': '1',
            'total': '1',
            'price': '1'
        })
        self.assertEqual(res.status_code, 200)

        # Verify in DB that booking record package is preserved as Premium and payment_status submitted
        with db_connection() as conn:
            booking = conn.execute("SELECT * FROM bookings WHERE email='tamper_pay02@example.com'").fetchone()
            self.assertIsNotNone(booking)
            self.assertIn("Premium", booking["service"])
            self.assertEqual(booking["payment_status"], "Payment submitted (test)")

    def test_03_fake_payment_status_injection(self):
        """Verify browser cannot inject payment_status='Paid' or status='Approved'"""
        app.config['WTF_CSRF_ENABLED'] = False
        client = app.test_client()
        client.get('/')

        with client.session_transaction() as sess:
            sess['pending_booking'] = {
                'name': 'Status Injection Test',
                'email': 'inject_pay03@example.com',
                'phone': '1234567890',
                'service': 'Portrait Session',
                'package': 'Signature',
                'location': 'Coimbatore',
                'message': 'Test',
                'booking_date': '2032-01-03'
            }

        # Attempt to inject payment_status='Paid' and status='Approved'
        res = client.post('/booking/payment/confirm', data={
            'method': 'card',
            'payment_status': 'Paid',
            'status': 'Approved'
        })
        self.assertEqual(res.status_code, 200)

        with db_connection() as conn:
            booking = conn.execute("SELECT * FROM bookings WHERE email='inject_pay03@example.com'").fetchone()
            self.assertIsNotNone(booking)
            self.assertEqual(booking["payment_status"], "Payment submitted (test)")
            self.assertEqual(booking["status"], "Pending")

    def test_04_duplicate_payment_submission_protection(self):
        """Verify resubmitting payment confirm request fails gracefully once session is cleared"""
        app.config['WTF_CSRF_ENABLED'] = False
        client = app.test_client()
        client.get('/')

        with client.session_transaction() as sess:
            sess['pending_booking'] = {
                'name': 'Dup Test',
                'email': 'dup_pay04@example.com',
                'phone': '1234567890',
                'service': 'Portrait Session',
                'package': 'Essential',
                'location': 'Coimbatore',
                'message': 'Test',
                'booking_date': '2032-01-04'
            }

        # First submission succeeds
        res1 = client.post('/booking/payment/confirm', data={'method': 'upi'})
        self.assertEqual(res1.status_code, 200)

        # Second submission fails because session['pending_booking'] was popped
        res2 = client.post('/booking/payment/confirm', data={'method': 'upi'})
        self.assertEqual(res2.status_code, 302)

        # Verify only 1 booking record was created in database
        with db_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM bookings WHERE email='dup_pay04@example.com'").fetchone()[0]
            self.assertEqual(count, 1)

    def test_05_invalid_payment_record_id(self):
        """Verify accessing payment flow or receipt with non-existent ID returns 404"""
        app.config['WTF_CSRF_ENABLED'] = False
        client = app.test_client()

        res_pay = client.get('/payment/booking/999999')
        self.assertEqual(res_pay.status_code, 404)

        res_qr = client.get('/payment/booking/999999/qr')
        self.assertEqual(res_qr.status_code, 404)

    def test_06_unauthorized_payment_detail_access(self):
        """Verify Customer B cannot view Customer A's booking confirmation / payment details"""
        app.config['WTF_CSRF_ENABLED'] = False
        with db_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('custA_pay06@test.com', 'CustA', 'hash')")
            conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('custB_pay06@test.com', 'CustB', 'hash')")
            cust_b_id = conn.execute("SELECT id FROM customers WHERE email='custB_pay06@test.com'").fetchone()['id']
            conn.execute("INSERT INTO bookings (name, email, phone, service, booking_date, status, payment_status) VALUES ('CustA', 'custA_pay06@test.com', '123', 'Wedding — Essential', '2032-01-06', 'Pending', 'Unpaid')")
            b_id = conn.execute("SELECT id FROM bookings WHERE booking_date='2032-01-06'").fetchone()['id']
            conn.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['customer_id'] = cust_b_id

        res = client.get(f'/customer/booking/{b_id}')
        self.assertEqual(res.status_code, 403)

    def test_07_unauthorized_receipt_download_access(self):
        """Verify Customer B cannot download Customer A's receipt PDF"""
        app.config['WTF_CSRF_ENABLED'] = False
        with db_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('custA2_pay07@test.com', 'CustA2', 'hash')")
            conn.execute("INSERT OR IGNORE INTO customers (email, name, password_hash) VALUES ('custB2_pay07@test.com', 'CustB2', 'hash')")
            cust_b_id = conn.execute("SELECT id FROM customers WHERE email='custB2_pay07@test.com'").fetchone()['id']
            conn.execute("INSERT INTO bookings (name, email, phone, service, booking_date, status, payment_status) VALUES ('CustA2', 'custA2_pay07@test.com', '123', 'Wedding — Essential', '2032-01-07', 'Pending', 'Payment submitted (test)')")
            b_id = conn.execute("SELECT id FROM bookings WHERE booking_date='2032-01-07'").fetchone()['id']
            conn.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['customer_id'] = cust_b_id

        res = client.get(f'/receipt/booking/{b_id}.pdf')
        self.assertIn(res.status_code, (403, 404))

    def test_08_payment_confirm_existing_booking_idor(self):
        """Verify POST /payment/booking/<id>/confirm validates existing booking and IDOR"""
        app.config['WTF_CSRF_ENABLED'] = False
        client = app.test_client()

        res = client.post('/payment/booking/999999/confirm', data={'method': 'upi'})
        self.assertEqual(res.status_code, 404)

if __name__ == '__main__':
    unittest.main()
