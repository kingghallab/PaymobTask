import concurrent.futures
import json
import statistics
import time
import os
import urllib.request
import uuid

BASE_URL = os.environ.get("LOAD_TEST_BASE_URL", "http://localhost:8000/api")

# Brief §4 Performance AC:
#   "Typical checkout latency target: < 500 ms for reservation creation;
#    < 2 s for enqueueing confirm."
RESERVATION_LATENCY_TARGET_SECONDS = 0.5
PURCHASE_ENQUEUE_LATENCY_TARGET_SECONDS = 2.0


def _register_and_login(user_index):
    """
    Registers and logs in one dedicated user per virtual checkout, rather
    than sharing a single token across all concurrent requests - the
    reserve/purchase endpoints are rate-limited per-user (10/min, 5/min), so
    a shared user would mostly measure 429s at any real concurrency instead
    of actual checkout latency.
    """
    user_email = f"loadtest_{uuid.uuid4().hex[:8]}_{user_index}@example.com"
    reg_data = json.dumps({
        "email": user_email,
        "username": f"user_{uuid.uuid4().hex[:8]}_{user_index}",
        "first_name": "Load",
        "last_name": "Test",
        "password": "Password123!",
        "confirm_password": "Password123!"
    }).encode('utf-8')

    req = urllib.request.Request(f"{BASE_URL}/users/register/", data=reg_data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        pass

    login_data = json.dumps({"email": user_email, "password": "Password123!"}).encode('utf-8')
    req = urllib.request.Request(f"{BASE_URL}/users/login/", data=login_data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        tokens = json.loads(resp.read().decode('utf-8'))
        return tokens['access']


def load_test_reservations_and_purchases(num_users=20):
    """
    Simulates `num_users` concurrent user checkouts, each with its own
    account, and measures per-request latency against the brief's targets.
    """
    print(f"Starting load test with {num_users} concurrent users against {BASE_URL}...")

    try:
        admin_token = _register_and_login('probe')
    except Exception as e:
        print(f"Setup failed: {e}")
        return

    req = urllib.request.Request(f"{BASE_URL}/events/", headers={'Authorization': f'Bearer {admin_token}'})
    with urllib.request.urlopen(req) as resp:
        events = json.loads(resp.read().decode('utf-8'))
        if not events or not events[0].get('ticket_types'):
            print("No events/ticket types found. Run 'python manage.py seed_data' first!")
            return
        ticket_type_id = events[0]['ticket_types'][0]['id']

    print(f"Targeting TicketType ID: {ticket_type_id}")

    successes = 0
    failures = 0
    reservation_latencies = []
    purchase_latencies = []
    start_time = time.time()

    def user_checkout_flow(index):
        nonlocal successes, failures
        try:
            access_token = _register_and_login(index)
            headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}

            res_payload = json.dumps({"ticket_type_id": ticket_type_id, "quantity": 1}).encode('utf-8')
            res_req = urllib.request.Request(f"{BASE_URL}/reservations/", data=res_payload, headers=headers)
            t0 = time.time()
            with urllib.request.urlopen(res_req) as res_resp:
                reservation_latencies.append(time.time() - t0)
                res_data = json.loads(res_resp.read().decode('utf-8'))
                reservation_id = res_data['id']

            idem_key = f"load_{uuid.uuid4().hex}"
            p_headers = dict(headers)
            p_headers['Idempotency-Key'] = idem_key
            p_payload = json.dumps({"reservation_id": reservation_id}).encode('utf-8')

            p_req = urllib.request.Request(f"{BASE_URL}/purchases/", data=p_payload, headers=p_headers)
            t1 = time.time()
            with urllib.request.urlopen(p_req) as p_resp:
                purchase_latencies.append(time.time() - t1)
                if p_resp.status in (200, 202):
                    successes += 1
        except Exception:
            failures += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_users) as executor:
        futures = [executor.submit(user_checkout_flow, i) for i in range(num_users)]
        concurrent.futures.wait(futures)

    duration = time.time() - start_time
    print(f"\n--- Load Test Results ---")
    print(f"Total Requests: {num_users}")
    print(f"Successes: {successes}")
    print(f"Failures: {failures}")
    print(f"Duration: {duration:.2f} seconds ({num_users / duration:.2f} req/sec)")

    _report_latency("Reservation creation", reservation_latencies, RESERVATION_LATENCY_TARGET_SECONDS)
    _report_latency("Purchase enqueue", purchase_latencies, PURCHASE_ENQUEUE_LATENCY_TARGET_SECONDS)


def _report_latency(label, samples, target_seconds):
    if not samples:
        print(f"{label}: no samples collected")
        return
    samples_sorted = sorted(samples)
    avg = statistics.mean(samples_sorted)
    p95_index = min(len(samples_sorted) - 1, int(len(samples_sorted) * 0.95))
    p95 = samples_sorted[p95_index]
    verdict = "PASS" if p95 <= target_seconds else "FAIL"
    print(
        f"{label}: avg={avg * 1000:.0f}ms  p95={p95 * 1000:.0f}ms  "
        f"target={target_seconds * 1000:.0f}ms  [{verdict}]"
    )


if __name__ == '__main__':
    # Expected throughput for this project: ~5-10 confirmed purchases/sec on
    # a single dev-mode Celery worker (CELERY_WORKER_PREFETCH_MULTIPLIER=1,
    # single default queue). This isn't a hard SLA - it's the number the
    # brief asks interns to state, sized to the reservation endpoint's own
    # 10/min per-user throttle rather than raw worker capacity, since a
    # realistic user base is many accounts each well under that limit, not
    # one account hammering the API.
    load_test_reservations_and_purchases(num_users=20)
