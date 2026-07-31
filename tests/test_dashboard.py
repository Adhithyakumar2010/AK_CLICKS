import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db

class TestDashboard(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_story_customer_dashboard_and_pages(self):
        """Test Story Customer Dashboard, profile update, settings, change password"""
        email = f"reader_{os.urandom(4).hex()}@example.com"
        self.client.post('/story-store/signup', data={'name': 'Reader', 'email': email, 'password': 'password123'}, follow_redirects=True)

        res_dash = self.client.get('/story-store/dashboard')
        self.assertEqual(res_dash.status_code, 200)

        res_prof = self.client.get('/story-store/profile')
        self.assertEqual(res_prof.status_code, 200)

        res_set = self.client.get('/story-store/settings')
        self.assertEqual(res_set.status_code, 200)

        res_pwd = self.client.get('/story-store/change-password')
        self.assertEqual(res_pwd.status_code, 200)

if __name__ == '__main__':
    unittest.main()
