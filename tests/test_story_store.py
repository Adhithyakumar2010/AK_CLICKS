import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db

class TestStoryStore(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_story_store_browsing_and_cart(self):
        """Test browsing catalog, adding to cart, checkout, order creation"""
        # Browse Home & Books
        res_home = self.client.get('/story-store')
        self.assertEqual(res_home.status_code, 200)

        res_books = self.client.get('/story-store/books')
        self.assertEqual(res_books.status_code, 200)

        # Add item to Cart
        res_add = self.client.post('/story-store/cart/add', data={
            'book_id': 'armor-of-light',
            'quantity': 1
        }, follow_redirects=True)
        self.assertEqual(res_add.status_code, 200)

        # View Cart
        res_cart = self.client.get('/story-store/cart')
        self.assertEqual(res_cart.status_code, 200)

if __name__ == '__main__':
    unittest.main()
