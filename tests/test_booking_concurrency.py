import os
import sys
import tempfile
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db, generate_csrf_token

class TestBookingConcurrencyAndHardening(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_filename = tempfile.mkstemp(suffix='.db')
        os.close(self.db_fd)
        
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SECRET_KEY'] = 'test-secret-key-123'
        
        # Override db_connection to use temporary test database
        def temp_db_connection():
            conn = sqlite3.connect(self.db_filename, timeout=30.0)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA foreign_keys = ON;")
            except Exception:
                pass
            return conn
            
        import app as app_module
        self.original_db_connection = app_module.db_connection
        app_module.db_connection = temp_db_connection
        
        with app.app_context():
            init_db()

    def tearDown(self):
        import app as app_module
        app_module.db_connection = self.original_db_connection
        try:
            if os.path.exists(self.db_filename):
                os.remove(self.db_filename)
        except Exception:
            pass

    def test_01_concurrent_booking_requests_same_slot(self):
        """Test 10 concurrent booking requests for the exact same date."""
        target_date = "2026-10-15"
        
        def attempt_booking(user_idx):
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['pending_booking'] = {
                        'name': f'User {user_idx}',
                        'email': f'user{user_idx}@example.com',
                        'phone': '9876543210',
                        'service': 'Wedding Photography — Signature',
                        'package': 'Signature',
                        'location': 'Chennai Studio',
                        'message': 'Test enquiry',
                        'booking_date': target_date
                    }
                    sess['csrf_token'] = f'test-token-{user_idx}'
                
                res = client.post('/booking/payment/confirm', data={
                    'method': 'upi',
                    'csrf_token': f'test-token-{user_idx}'
                }, follow_redirects=True)
                return res.status_code, res.data.decode('utf-8')

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(attempt_booking, i) for i in range(10)]
            results = [f.result() for f in futures]
            
        import app as app_module
        conn = app_module.db_connection()
        active_bookings = conn.execute(
            "SELECT * FROM bookings WHERE booking_date=? AND status NOT IN ('Declined', 'Cancelled')",
            (target_date,)
        ).fetchall()
        conn.close()

        # Exactly 1 booking MUST succeed and be stored in database
        self.assertEqual(len(active_bookings), 1, "Exactly one active booking must exist for the date")
        
        # Verify success responses vs error redirects
        successes = sum(1 for status, body in results if "receipt" in body.lower() or "reference" in body.lower() or "confirmed" in body.lower() or "thank" in body.lower() or "confirmation" in body.lower() or "test mode" in body.lower())
        self.assertGreaterEqual(successes, 1)

    def test_02_past_date_and_invalid_date_validation(self):
        """Test rejection of past dates and malformed date strings."""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['pending_booking'] = {
                    'name': 'Test User',
                    'email': 'testuser@example.com',
                    'phone': '9876543210',
                    'service': 'Wedding Photography — Signature',
                    'package': 'Signature',
                    'location': 'Studio',
                    'message': 'Test enquiry',
                    'booking_date': '2020-01-01' # Past date
                }
                sess['csrf_token'] = 'token-123'

            res_past = client.post('/booking/select-date', data={'booking_date': '2020-01-01', 'csrf_token': 'token-123'}, follow_redirects=True)
            self.assertIn("future event date", res_past.data.decode('utf-8').lower())

            res_invalid = client.post('/booking/select-date', data={'booking_date': 'invalid-date', 'csrf_token': 'token-123'}, follow_redirects=True)
            self.assertIn("valid event date", res_invalid.data.decode('utf-8').lower())

    def test_03_customer_cancellation_workflow_and_date_reuse(self):
        """Test cancellation workflow, IDOR protection, and cancelled date reusability."""
        import app as app_module
        from werkzeug.security import generate_password_hash

        conn = app_module.db_connection()
        conn.execute("INSERT INTO customers (name, email, password_hash) VALUES ('Owner', 'owner@example.com', ?)", (generate_password_hash('pass123'),))
        conn.execute("INSERT INTO customers (name, email, password_hash) VALUES ('Attacker', 'attacker@example.com', ?)", (generate_password_hash('pass123'),))
        conn.execute("INSERT INTO bookings (name, email, phone, service, booking_date, status) VALUES ('Owner', 'owner@example.com', '123', 'Wedding', '2026-11-20', 'Pending')")
        booking_id = conn.execute("SELECT id FROM bookings WHERE booking_date='2026-11-20'").fetchone()['id']
        conn.commit()
        conn.close()

        # 1. Unauthenticated cancellation -> redirect to account/login
        with app.test_client() as client:
            res_unauth = client.post(f'/customer/booking/{booking_id}/cancel', data={'csrf_token': 'dummy'}, follow_redirects=False)
            self.assertEqual(res_unauth.status_code, 302)
            self.assertIn("account", res_unauth.location.lower())

        # 2. Attacker IDOR cancellation attempt -> 403 Forbidden
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['customer_id'] = 2 # Attacker ID
                sess['csrf_token'] = 'attacker-csrf'
            res_idor = client.post(f'/customer/booking/{booking_id}/cancel', data={'csrf_token': 'attacker-csrf'})
            self.assertEqual(res_idor.status_code, 403)

        # 3. Owner cancellation -> Success
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['customer_id'] = 1 # Owner ID
                sess['csrf_token'] = 'owner-csrf'
            res_cancel = client.post(f'/customer/booking/{booking_id}/cancel', data={'csrf_token': 'owner-csrf'}, follow_redirects=True)
            self.assertIn("cancelled successfully", res_cancel.data.decode('utf-8').lower())

        # 4. Verify status is 'Cancelled' and date '2026-11-20' is now reusable
        conn = app_module.db_connection()
        status = conn.execute("SELECT status FROM bookings WHERE id=?", (booking_id,)).fetchone()['status']
        self.assertEqual(status, 'Cancelled')

        # Re-booking the cancelled date by another customer MUST succeed
        conn.execute("INSERT INTO bookings (name, email, phone, service, booking_date, status) VALUES ('New Customer', 'new@example.com', '999', 'Birthday', '2026-11-20', 'Pending')")
        conn.commit()
        conn.close()

    def test_04_customer_rescheduling_workflow_and_conflict_prevention(self):
        """Test customer rescheduling, occupied date conflict prevention, and IDOR."""
        import app as app_module
        from werkzeug.security import generate_password_hash

        conn = app_module.db_connection()
        conn.execute("INSERT INTO customers (name, email, password_hash) VALUES ('UserA', 'usera@example.com', ?)", (generate_password_hash('pass123'),))
        conn.execute("INSERT INTO bookings (name, email, phone, service, booking_date, status) VALUES ('UserA', 'usera@example.com', '123', 'Wedding', '2026-12-01', 'Pending')")
        conn.execute("INSERT INTO bookings (name, email, phone, service, booking_date, status) VALUES ('UserB', 'userb@example.com', '456', 'Portrait', '2026-12-05', 'Approved')")
        booking_a_id = conn.execute("SELECT id FROM bookings WHERE booking_date='2026-12-01'").fetchone()['id']
        conn.commit()
        conn.close()

        # Reschedule UserA booking to occupied date '2026-12-05' -> Conflict Error
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['customer_id'] = 1
                sess['csrf_token'] = 'user-csrf'
            res_conflict = client.post(f'/customer/booking/{booking_a_id}/reschedule', data={'new_date': '2026-12-05', 'csrf_token': 'user-csrf'}, follow_redirects=True)
            self.assertIn("already reserved", res_conflict.data.decode('utf-8').lower())

        # Reschedule UserA booking to available date '2026-12-10' -> Success
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['customer_id'] = 1
                sess['csrf_token'] = 'user-csrf'
            res_success = client.post(f'/customer/booking/{booking_a_id}/reschedule', data={'new_date': '2026-12-10', 'csrf_token': 'user-csrf'}, follow_redirects=True)
            self.assertIn("rescheduled to 2026-12-10", res_success.data.decode('utf-8').lower())

        conn = app_module.db_connection()
        updated_date = conn.execute("SELECT booking_date FROM bookings WHERE id=?", (booking_a_id,)).fetchone()['booking_date']
        conn.close()
        self.assertEqual(updated_date, '2026-12-10')

    def test_05_booking_state_machine_enforcement(self):
        """Test state machine rules for admin and customer status updates."""
        import app as app_module

        conn = app_module.db_connection()
        conn.execute("INSERT INTO bookings (name, email, phone, service, booking_date, status) VALUES ('Completed User', 'completed@example.com', '123', 'Wedding', '2026-05-01', 'Completed')")
        booking_id = conn.execute("SELECT id FROM bookings WHERE booking_date='2026-05-01'").fetchone()['id']
        conn.commit()
        conn.close()

        # Admin attempting invalid transition: Completed -> Pending -> Rejected
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['admin'] = True
            res_invalid = client.post(f'/booking/{booking_id}/status', data={'status': 'Pending'}, follow_redirects=True)
            self.assertIn("invalid status transition", res_invalid.data.decode('utf-8').lower())

        conn = app_module.db_connection()
        status = conn.execute("SELECT status FROM bookings WHERE id=?", (booking_id,)).fetchone()['status']
        conn.close()
        self.assertEqual(status, 'Completed')

if __name__ == '__main__':
    unittest.main()
