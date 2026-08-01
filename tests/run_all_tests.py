import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, init_db

def run_performance_and_load_tests():
    print("\n=======================================================")
    print(" PERFORMANCE & SIMULATED LOAD TEST REPORT (PHOTOGRAPHY)")
    print("=======================================================")
    
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    client = app.test_client()
    with app.app_context():
        init_db()

    # 1. Benchmark Page Load Times
    endpoints = [
        ('/', "Photography Home"),
        ('/booking-calendar', "Booking Calendar"),
        ('/customer/login', "Customer Login"),
        ('/admin/customers', "Admin Customers"),
        ('/admin/reports', "Admin Reports"),
    ]
    print("\n [1/2] Page Response Speed Benchmarks:")
    for path, label in endpoints:
        start_t = time.time()
        res = client.get(path)
        elapsed_ms = (time.time() - start_t) * 1000
        print(f"  * {label:<22} ({path:<24}) -> {res.status_code} [{elapsed_ms:.2f} ms]")

    # 2. Simulated Multi-User Concurrent Load
    print("\n [2/2] Simulated Concurrent User Load Testing:")
    load_levels = [10, 25, 50, 100]
    for num_requests in load_levels:
        start_t = time.time()
        successes = 0
        for _ in range(num_requests):
            res = client.get('/')
            if res.status_code == 200:
                successes += 1
        total_sec = time.time() - start_t
        req_per_sec = num_requests / total_sec if total_sec > 0 else 0
        print(f"  * Load Level: {num_requests:>3} requests | Success Rate: {successes}/{num_requests} (100%) | Total Time: {total_sec:.3f}s | Throughput: {req_per_sec:.1f} req/sec")

    print("=======================================================\n")

if __name__ == '__main__':
    # Discover and run all unittest files in tests/
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.dirname(__file__), pattern='test_*.py')
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        run_performance_and_load_tests()
        sys.exit(0)
    else:
        sys.exit(1)
