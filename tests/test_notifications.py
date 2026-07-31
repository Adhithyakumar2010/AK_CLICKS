import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db

class TestNotifications(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_notifications_page(self):
        """Test Story Store notifications rendering"""
        res_notif = self.client.get('/story-store/notifications')
        self.assertEqual(res_notif.status_code, 200)

if __name__ == '__main__':
    unittest.main()
