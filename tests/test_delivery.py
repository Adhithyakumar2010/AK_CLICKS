import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db

class TestDelivery(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_delivery_tracking_routes(self):
        """Test Story Admin Delivery tracking dashboard"""
        with self.client.session_transaction() as sess:
            sess['story_admin'] = True

        res_del = self.client.get('/story-store/admin/delivery')
        self.assertEqual(res_del.status_code, 200)

if __name__ == '__main__':
    unittest.main()
