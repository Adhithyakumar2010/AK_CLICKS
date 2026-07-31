import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db

class TestInventory(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_inventory_admin_page(self):
        """Test Story Store Admin Inventory management route"""
        with self.client.session_transaction() as sess:
            sess['story_admin'] = True

        res_inv = self.client.get('/story-store/admin/inventory')
        self.assertEqual(res_inv.status_code, 200)

if __name__ == '__main__':
    unittest.main()
