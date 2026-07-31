import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db, validate_password_strength, is_rate_limited

class TestSecurity(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_01_security_headers(self):
        """Verify essential security headers are attached to responses"""
        res = self.client.get('/story-store')
        self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("Content-Security-Policy", res.headers)
        # CSP should allow Google Fonts and CDNs
        csp = res.headers.get("Content-Security-Policy")
        self.assertIn("https://fonts.googleapis.com", csp)

    def test_02_password_strength_validator(self):
        """Test password strength rules (min 8 chars, upper, lower, digit, special)"""
        valid, msg = validate_password_strength("Short1!")
        self.assertFalse(valid)

        valid, msg = validate_password_strength("alllowercase1!")
        self.assertFalse(valid)

        valid, msg = validate_password_strength("ALLUPPERCASE1!")
        self.assertFalse(valid)

        valid, msg = validate_password_strength("NoDigitsHere!")
        self.assertFalse(valid)

        valid, msg = validate_password_strength("NoSpecial1234")
        self.assertFalse(valid)

        valid, msg = validate_password_strength("StrongP@ssw0rd")
        self.assertTrue(valid)

    def test_03_rate_limiter(self):
        """Verify sensible rate limiter blocks excessive requests"""
        test_ip = "192.168.1.99"
        endpoint = "login_test"
        # Send 30 requests (allowed)
        for _ in range(30):
            self.assertFalse(is_rate_limited(test_ip, endpoint, max_requests=30, window_seconds=60))
        # 31st request should be rate limited
        self.assertTrue(is_rate_limited(test_ip, endpoint, max_requests=30, window_seconds=60))

    def test_04_session_cookie_security(self):
        """Verify HttpOnly and SameSite cookie configurations"""
        self.assertTrue(app.config.get("SESSION_COOKIE_HTTPONLY"))
        self.assertEqual(app.config.get("SESSION_COOKIE_SAMESITE"), "Lax")

    def test_05_xss_content_escaping(self):
        """Verify user inputs in search or reviews are safely escaped"""
        xss_input = "<script>alert('xss')</script>"
        res = self.client.get(f"/story-store/books?q={xss_input}")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("<script>alert('xss')</script>", res.data.decode('utf-8'))

if __name__ == '__main__':
    unittest.main()
