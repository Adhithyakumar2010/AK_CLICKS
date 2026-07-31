import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db

class TestPayments(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_payment_page_rendering(self):
        """Test Story Store payment gateway rendering"""
        with self.client.session_transaction() as sess:
            sess['pending_story_order'] = {
                'customer_name': 'Test Buyer',
                'email': 'buyer@example.com',
                'phone': '9876543210',
                'address': 'Coimbatore',
                'total': 999,
                'items': 'The Armor of Light x 1'
            }
        res_pay = self.client.get('/story-store/payment')
        self.assertEqual(res_pay.status_code, 200)

if __name__ == '__main__':
    unittest.main()
