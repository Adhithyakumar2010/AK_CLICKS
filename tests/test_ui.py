import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db

class TestUI(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_custom_404_error_page(self):
        """Test 404 page rendering for Photography and Story Store"""
        res_photo = self.client.get('/nonexistent-page-1234')
        self.assertEqual(res_photo.status_code, 404)
        self.assertIn("Page Not Found", res_photo.data.decode('utf-8'))

        res_story = self.client.get('/story-store/nonexistent-book-9999')
        self.assertEqual(res_story.status_code, 404)
        self.assertIn("Page Not Found", res_story.data.decode('utf-8'))

    def test_02_skeleton_shimmer_and_micro_animations(self):
        """Verify CSS contains skeleton shimmer and micro animation classes"""
        res_css = self.client.get('/static/css/style.css')
        self.assertEqual(res_css.status_code, 200)
        data = res_css.data.decode('utf-8')
        self.assertIn(".skeleton-box", data)
        self.assertIn("@keyframes shimmer", data)
        self.assertIn(".hover-lift", data)
        self.assertIn(".fade-in-up", data)

    def test_03_accessibility_focus_styles(self):
        """Verify WCAG focus indicator styles exist in CSS"""
        res_css = self.client.get('/static/css/style.css')
        data = res_css.data.decode('utf-8')
        self.assertIn("focus-visible", data)

if __name__ == '__main__':
    unittest.main()
