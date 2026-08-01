import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db, db_connection

class TestPhotographyAdminIsolation(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_photography_admin_customer_management(self):
        """Test Customer Management routes for Photography Admin"""
        with self.client.session_transaction() as sess:
            sess['admin'] = True

        res_list = self.client.get('/admin/customers')
        self.assertEqual(res_list.status_code, 200)
        self.assertIn("Customer Management", res_list.data.decode('utf-8'))

        res_export = self.client.get('/admin/customers/export')
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export.mimetype, 'text/csv')

    def test_02_photography_admin_reports_module(self):
        """Test Reports Dashboard and PDF/Excel export endpoints"""
        with self.client.session_transaction() as sess:
            sess['admin'] = True

        res_rep = self.client.get('/admin/reports')
        self.assertEqual(res_rep.status_code, 200)
        self.assertIn("Photography Analytics & Reports", res_rep.data.decode('utf-8'))

        res_pdf = self.client.get('/admin/reports/download/pdf')
        self.assertEqual(res_pdf.status_code, 200)
        self.assertEqual(res_pdf.mimetype, 'application/pdf')

        res_excel = self.client.get('/admin/reports/download/excel')
        self.assertEqual(res_excel.status_code, 200)
        self.assertEqual(res_excel.mimetype, 'text/csv')

    def test_03_dashboard_isolation_verify(self):
        """Verify Photography dashboards display only Photography items"""
        with self.client.session_transaction() as sess:
            sess['admin'] = True

        res_dash = self.client.get('/admin')
        self.assertEqual(res_dash.status_code, 200)
        data = res_dash.data.decode('utf-8')
        nav_html = data.split('<div class="main">')[0]
        self.assertNotIn("Story Store", nav_html)

    def test_04_story_store_non_regression(self):
        """Verify Story Store remains 100% functional and accessible"""
        res_story_home = self.client.get('/story-store')
        self.assertEqual(res_story_home.status_code, 200)

        res_story_books = self.client.get('/story-store/books')
        self.assertEqual(res_story_books.status_code, 200)

        with self.client.session_transaction() as sess:
            sess['story_admin'] = True

        res_story_admin = self.client.get('/story-store/admin')
        self.assertEqual(res_story_admin.status_code, 200)

if __name__ == '__main__':
    unittest.main()
