import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db

class TestAccessibility(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_accessibility_markup_and_alt_tags(self):
        """Verify image alt attributes and semantic HTML tags in templates"""
        res_home = self.client.get('/')
        data = res_home.data.decode('utf-8')
        self.assertIn("alt=", data)
        self.assertIn("<header", data)
        self.assertIn("<footer", data)

if __name__ == '__main__':
    unittest.main()
