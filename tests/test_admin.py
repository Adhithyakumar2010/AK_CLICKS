import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db

class TestAdmin(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_story_admin_dashboard_and_security(self):
        """Test Story Admin login, dashboard, and Security Suite routes"""
        with self.client.session_transaction() as sess:
            sess['story_admin'] = True

        res_dash = self.client.get('/story-store/admin')
        self.assertEqual(res_dash.status_code, 200)

        res_sec = self.client.get('/story-store/admin/security')
        self.assertEqual(res_sec.status_code, 200)

        res_audit = self.client.get('/story-store/admin/security/audit')
        self.assertEqual(res_audit.status_code, 200)

        res_sess = self.client.get('/story-store/admin/security/sessions')
        self.assertEqual(res_sess.status_code, 200)

        res_pwd = self.client.get('/story-store/admin/security/password')
        self.assertEqual(res_pwd.status_code, 200)

        res_set = self.client.get('/story-store/admin/security/settings')
        self.assertEqual(res_set.status_code, 200)

if __name__ == '__main__':
    unittest.main()
