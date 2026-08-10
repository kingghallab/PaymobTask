import concurrent.futures
import json
import random
import time
import urllib.request
import uuid

BASE_URL = "http://localhost:8000/api"


def load_test_reservations_and_purchases(num_users=50):
    """
    Simulates concurrent user checkouts hitting the API endpoints.
    """
    print(f"Starting load test with {num_users} concurrent users against {BASE_URL}...")

    # 1. Register & login test user
    user_email = f"loadtest_{uuid.uuid4().hex[:8]}@example.com"
    reg_data = json.dumps({
        "email": user_email,
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "first_name": "Load",
        "last_name": "Test",
        "password": "Password123!",
        "confirm_password": "Password123!"
    }).encode('utf-8')

    req = urllib.request.Request(f"{BASE_URL}/users/register/", data=reg_data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as resp:
            print("Registered load test user.")
    except Exception as e:
        print(f"Registration failed: {e}")
        return

    # Login
    login_data = json.dumps({"email": user_email, "password": "Password123!"}).encode('utf-8')
    req = urllib.request.Request(f"{BASE_URL}/users/login/", data=login_data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        tokens = json.loads(resp.read().decode('utf-8'))
        access_token = tokens['access']

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    # Fetch events
    req = urllib.request.Request(f"{BASE_URL}/events/", headers=headers)
    with urllib.request.urlopen(req) as resp:
        events = json.loads(resp.read().decode('utf-8'))
        if not events or not events[0].get('ticket_types'):
            print("No events/ticket types found. Run 'python manage.py seed_data' first!")
            return
        ticket_type_id = events[0]['ticket_types'][0]['id']

    print(f"Targeting TicketType ID: {ticket_type_id}")

    successes = 0
    failures = 0
    start_time = time.time()

    def user_checkout_flow():
        nonlocal successes, failures
        try:
            # 1. Reserve ticket
            res_payload = json.dumps({"ticket_type_id": ticket_type_id, "quantity": 1}).encode('utf-8')
            res_req = urllib.request.Request(f"{BASE_URL}/reservations/", data=res_payload, headers=headers)
            with urllib.request.urlopen(res_req) as res_resp:
                res_data = json.loads(res_resp.read().decode('utf-8'))
                reservation_id = res_data['id']

            # 2. Purchase ticket
            idem_key = f"load_{uuid.uuid4().hex}"
            p_headers = dict(headers)
            p_headers['Idempotency-Key'] = idem_key
            p_payload = json.dumps({"reservation_id": reservation_id}).encode('utf-8')

            p_req = urllib.request.Request(f"{BASE_URL}/purchases/", data=p_payload, headers=p_headers)
            with urllib.request.urlopen(p_req) as p_resp:
                if p_resp.status in (200, 202):
                    successes += 1
        except Exception:
            failures += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(user_checkout_flow) for _ in range(num_users)]
        concurrent.futures.wait(futures)

    duration = time.time() - start_time
    print(f"\n--- Load Test Results ---")
    print(f"Total Requests: {num_users}")
    print(f"Successes: {successes}")
    print(f"Failures: {failures}")
    print(f"Duration: {duration:.2f} seconds ({num_users / duration:.2f} req/sec)")


if __name__ == '__main__':
    load_test_reservations_and_purchases(num_users=20)
