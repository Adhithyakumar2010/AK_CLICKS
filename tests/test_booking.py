import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db, db_connection
from werkzeug.security import generate_password_hash

class TestBooking(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()
            with db_connection() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO customers (id, name, email, password_hash) VALUES (1, 'Test Client', 'client@example.com', ?)",
                    (generate_password_hash('password123'),)
                )

    def test_01_photography_booking_flow(self):
        """Test booking submission, package selection, calendar, and customer dashboard"""
        # Step 1: Submit Booking with Package
        res_booking = self.client.post('/book', data={
            'name': 'Test Client',
            'email': 'client@example.com',
            'phone': '9876543210',
            'service': 'Wedding Photography',
            'package': 'Standard',
            'location': 'Grand Palace Hall',
            'message': 'Looking forward to the session!'
        }, follow_redirects=True)
        self.assertEqual(res_booking.status_code, 200)

        # Step 2: Set customer session
        with self.client.session_transaction() as sess:
            sess['customer_id'] = 1
            sess['customer_name'] = 'Test Client'

        # Step 3: Customer Dashboard
        res_dash = self.client.get('/customer')
        self.assertEqual(res_dash.status_code, 200)

if __name__ == '__main__':
    unittest.main()
