# 🧠 Session Memory — Paymob Ticketing & Reservations Backend

> **Purpose:** This file preserves the FULL context from the planning conversation so the next agent session starts with zero quality loss. Read this ENTIRELY before writing any code.

---

## 1. Project Identity

| Field | Value |
|---|---|
| **Project** | Event Management Backend — Ticketing & Reservations |
| **Company** | Paymob (payment company, Egypt) |
| **Developer** | Adham (intern) — learning Django/Postgres/Celery along the way |
| **Stakes** | This project determines whether Adham works on production Paymob code |
| **Timeline** | 10 days with AI assistance |
| **Workspace** | `c:\Users\adham\Desktop\Paymob\PaymobTask` |
| **Stack manifest** | `aas-stack.json` in workspace root — defines Django, Postgres, Celery |

---

## 2. User Preferences & Behavioral Rules

These are non-negotiable. The user was explicit about each:

1. **No overengineering.** Every entity, field, and abstraction must justify its existence against the brief. If you can't point to a sentence in the brief that requires it, don't add it.
2. **Sparring partner role.** Challenge bad decisions — don't be a yes-man. If the user proposes cutting something that should stay, push back with reasoning. If the user proposes adding something unnecessary, say so.
3. **Learning mode.** Add instruction tips for concepts Adham is learning. He's new to Django/Postgres/Celery but is evaluated on production-quality thinking.
4. **Rationale transparency.** Every major design decision must have a visible rationale. If the rationale is "it's best practice" without a brief requirement, it's probably overkill.
5. **AAS Skills.** Use `@mcp:agentic-awesome-skills` to load relevant skills per phase. Don't load all at once. Skills are annotated in the implementation plan under each phase.

---

## 3. Architecture Summary

```
Django 5.x monolith → DRF API → PostgreSQL 16 + Redis 7
                    → Celery worker (purchase processing, expiry sweep)
                    → Celery Beat (periodic sweep every 60s, daily reconciliation at 2 AM)
```

**Key patterns:**
- **Service layer:** All business logic in `services/` modules, NOT in views. Views are thin (validate, enqueue, respond).
- **Concurrency:** `SELECT FOR UPDATE` (2-statement pattern in `transaction.atomic()`). This is the core of the project.
- **Inventory:** `held` + `sold` counters on TicketType. Reconciliation as daily safety net.
- **Sync/Async split:** Reservation is synchronous (instant hold). Purchase is async (Celery task).
- **Payment:** Strategy pattern with `PaymentProvider` ABC. `FakePaymentProvider` for dev (90% success rate). `PaymobPaymentProvider` stub for Paymob Accept API.
- **Idempotency:** `Order.idempotency_key` unique field — checked directly in the purchase view. No separate table, no middleware.
- **DLQ:** `FailedTask` model populated by Celery's `task_failure` signal. Custom fields: `resolution`, `resolved_by`.
- **Audit:** `AuditLog` with `entity_type`, `entity_id`, `action`, `actor`, `changes` (JSON), `reason` (text).

---

## 4. Database Schema (9 Entities — FINAL)

These 9 entities were validated through a brutal entity audit. Each one earns its spot.

### User
- `id` (UUID PK), `email` (unique), `first_name`, `last_name`
- `AbstractUser` with `AUTH_USER_MODEL` set. UUID PK.

### Event
- `id`, `title`, `description`, `start_date`, `end_date`, `venue`, `status` (draft|published|cancelled|completed), `organizer_id` (FK to User), `hold_duration_minutes` (default 10), `created_at`, `updated_at`

### TicketType
- `id`, `event_id` (FK), `name`, `total_capacity` (immutable), `sold` (default 0), `held` (default 0), `price_cents`, `status` (active|paused|sold_out), `created_at`, `updated_at`
- **No service_fee_cents, no tax_cents** — just price. Not a billing system.
- `computed_available` property: `total_capacity - sold - held`
- CHECK constraints: `sold >= 0`, `held >= 0`, `sold + held <= total_capacity`, `price_cents >= 0`

### Reservation
- `id`, `user_id` (FK), `ticket_type_id` (FK), `quantity`, `status` (active|confirmed|expired|cancelled), `expires_at`, `created_at`
- Partial index on `(expires_at) WHERE status = 'active'` for the sweep

### Order
- `id`, `user_id` (FK), `event_id` (FK), `reservation_id` (FK), `ticket_type_id` (FK), `idempotency_key` (unique), `quantity`, `unit_price_cents` (snapshot), `total_cents`, `status` (processing|confirmed|partially_refunded|refunded|failed), `payment_id`, `payment_provider` (fake|paymob), `confirmed_at`, `created_at`
- **No OrderLineItem table** — 1 reservation = 1 order = 1 ticket type. Fields absorbed into Order.
- **No IdempotencyKey table** — `idempotency_key` unique field handles dedup.

### Ticket
- `id`, `order_id` (FK), `status` (active|refunded|cancelled), `created_at`
- **Minimal.** No attendee fields (derived from Order.user). No QR code field (UUID PK *is* the QR content — rendered client-side). No check_in fields (status can transition to `checked_in` later if needed).
- Individual rows needed for partial refund tracking.

### Refund
- `id`, `order_id` (FK), `ticket_id` (FK, nullable for partial), `amount_cents`, `reason`, `status` (pending|processed|failed), `initiated_by` (kept — financial docs must be self-contained), `payment_refund_id`, `processed_at`, `created_at`

### AuditLog
- `id`, `entity_type`, `entity_id`, `action`, `actor`, `changes` (JSON), `reason` (text — answers WHY, not just WHAT), `created_at`

### FailedTask
- `id`, `task_id` (unique), `task_name`, `args` (JSON), `kwargs` (JSON), `exception_message`, `retry_count`, `resolution` (null|retried|refunded|manual), `resolved_by`, `resolved_at`, `created_at`
- **No traceback field** — exception message is enough, full traceback in Celery logs.

### What Was Cut (and Why)

| Cut | Reason |
|---|---|
| OrderLineItem table | 1 reservation = 1 order = 1 ticket type. No multi-type cart. |
| IdempotencyKey table | `Order.idempotency_key` unique field already handles dedup. |
| WaitlistEntry table | Zero code touches it. Replaced with a comment. |
| TicketType fees/tax | Not a billing system. Just price_cents. |
| Ticket.qr_code | UUID PK *is* the QR content. Presentation concern. |
| Ticket.attendee_* | Derived from Order.user. General admission. |
| Ticket.check_in_* | Merged into Ticket.status. |
| FailedTask.traceback | In Celery logs already. |

### What Was Kept After Pushback

| Kept | Why |
|---|---|
| Refund.initiated_by | Financial docs must be self-contained. One field. |
| AuditLog.reason | Answers "why" which action+changes don't. One field. |
| Event.organizer_id | Event ownership. Needed for permissions if ever added. One FK. |

---

## 5. Core Flows (Behavioral Spec)

### Reservation Flow
1. User POSTs to `/api/reservations/` with `ticket_type_id` + `quantity`
2. View validates, calls `reservation_service.create_reservation()`
3. Service: `SELECT FOR UPDATE` on TicketType -> check availability -> increment `held` -> create Reservation with `expires_at` -> audit log
4. Return Reservation to user (synchronous, < 50ms under lock)

### Purchase Flow
1. User POSTs to `/api/purchases/` with `reservation_id` + `Idempotency-Key` header
2. View checks `Order.idempotency_key` for dedup -> enqueues `process_purchase_task` -> returns 202
3. Celery task: `SELECT FOR UPDATE` on Reservation -> check status/expiry -> call PaymentProvider.capture() -> decrement `held`, increment `sold` -> create Order + N Tickets -> set Reservation.status = 'confirmed' -> audit log

### Expiry Sweep
1. Celery Beat fires `sweep_expired_reservations` every 60s
2. Query: `Reservation.filter(status='active', expires_at__lt=now()).select_for_update(skip_locked=True)`
3. For each: decrement `held` on TicketType -> set status = 'expired' -> audit log

### Refund Flow
1. POST `/api/refunds/` with `order_id`, optional `ticket_ids`, `reason`
2. Service: `SELECT FOR UPDATE` on Order -> find active tickets -> calculate refund amount -> call PaymentProvider.refund() -> create Refund record -> mark tickets as refunded -> restore `sold` counter -> update Order status -> audit log

---

## 6. Critical Technical Details

### Concurrency Test (Crown Jewel)
- **Must use `TransactionTestCase`**, not `TestCase`. Django's `TestCase` wraps in a single transaction so threads can't see each other's writes.
- Setup: 50 remaining tickets, 100 concurrent threads each trying to reserve 1.
- Expected: exactly 50 successes, exactly 50 `InsufficientCapacityError`.

### Critical Day 4 Milestone
- If the concurrency test doesn't pass by Day 4, stop everything and fix it.

### Redis Configuration
- `appendonly yes` + data volume for persistence
- Used for: Celery broker (queue), DRF rate limiting cache
- NOT used for: reservation state (that's in Postgres)
- If Redis dies: reservations still work (sync), only async tasks pause. Sweep catches up on recovery.

### Price Handling
- All money in cents (integers). Never floats.

---

## 7. Project Structure

```
PaymobTask/
├── docker-compose.yml
├── Dockerfile
├── requirements/{base.txt, dev.txt}
├── manage.py
├── config/{__init__, celery, urls, wsgi, settings/{__init__, base, dev}}
├── users/{models, serializers, views, admin}
├── events/{models, serializers, views, services, admin}
├── orders/{models, serializers, views, services/{reservation, purchase, refund}, tasks, exporters, admin}
├── payments/{__init__, providers}
├── core/{models, signals, management/commands/{seed_data, run_reconciliation}}
└── tests/{conftest, factories, test_reservations, test_purchases, test_concurrency, test_refunds, test_reconciliation}
```

---

## 8. API Endpoints

| Method | Path | Throttle | Auth | Purpose |
|---|---|---|---|---|
| POST | `/api/users/register/` | — | No | Register |
| POST | `/api/users/login/` | — | No | JWT token pair |
| POST | `/api/users/token/refresh/` | — | No | Refresh JWT |
| GET | `/api/events/` | events_list (60/min) | No | List events |
| GET | `/api/events/{id}/` | events_list | No | Event detail + ticket types |
| POST | `/api/reservations/` | reserve (10/min) | Yes | Create reservation |
| DELETE | `/api/reservations/{id}/` | — | Yes | Cancel reservation |
| POST | `/api/purchases/` | purchase (5/min) | Yes | Purchase (async, needs Idempotency-Key) |
| GET | `/api/orders/{id}/` | — | Yes | Order detail + tickets |
| POST | `/api/refunds/` | refund (3/min) | Yes | Refund (partial or full) |
| GET | `/api/reports/sales/` | — | Admin | Sales CSV |
| GET | `/api/reports/attendees/` | — | Admin | Attendee CSV |
| GET | `/api/metrics/` | — | Admin | KPIs JSON |

---

## 9. 10-Day Phase Summary

| Phase | Days | Deliverables | Skills to Load |
|---|---|---|---|
| 1: Foundation | 1 | Docker, Django scaffold, User, JWT, DRF, Celery config | django-pro, container-security-hardening, andrej-karpathy |
| 2: Events | 2 | Event + TicketType models, admin, CRUD API, constraints | postgres-best-practices, api-design-principles, api-endpoint-builder |
| 3: Reservations | 3-4 | Reservation, SELECT FOR UPDATE, sweep, concurrency test | django-pro, postgres-best-practices, django-perf-review, 007 |
| 4: Purchases | 5 | Order, Ticket, Celery task, payment strategy, DLQ | django-pro, api-security-best-practices, async-python-patterns |
| 5: Refunds | 6-7 | Refund (full + partial), audit logging everywhere | django-pro, postgres-best-practices, api-design-principles |
| 6: Reports | 8 | CSV exports, reconciliation, metrics, seed data | django-perf-review, postgres-best-practices |
| 7: Testing | 9 | Full test suite, load test, security tests | django-perf-review, 007, api-security-best-practices |
| 8: Polish | 10 | README, runbooks, Paymob stub, cleanup | andrej-karpathy, plan-writing, api-design-principles |

---

## 10. Artifacts From Planning

| File | What It Contains |
|---|---|
| implementation_plan.md | THE source of truth. Final plan with 9 entities, all code flows, Docker Compose, Celery config, runbooks, phases with skill annotations. |
| design_rationale.md | Honest audit of every design decision. |
| entity_audit.md | Entity necessity audit. 12 to 9 entities. |
| gap_analysis.md | Cross-reference with senior Ticketmaster system design. |
| memory.md (this file) | Full context for next session. |

All artifacts are in: `C:\Users\adham\.gemini\antigravity-ide\brain\ebf50d27-88cb-45c0-8985-04aa4abd3712\`

---

## 11. Key Decisions Log (Chronological)

1. **Grill-me interview:** Established general admission (not assigned seating), email-only notifications (deferred), no multi-tenant, no fraud middleware.
2. **Design rationale:** Cut fraud middleware, 5 named queues. Simplified from 6 apps to 3-4.
3. **Entity audit:** Cut OrderLineItem, IdempotencyKey, WaitlistEntry. Merged fields into Order.
4. **Pushback (session 2):** Restored `Refund.initiated_by`, `AuditLog.reason`, `Event.organizer_id` after sparring. Cut `Ticket.qr_code` confirmed valid (UUID is QR content).
5. **Gap analysis:** Compared with senior system design interview. Added Redis persistence, Redis failure runbook. Virtual waiting queue noted as production consideration only.
6. **Field cuts (session 2):** Removed fees/tax from TicketType and Order. Removed attendee fields and check-in from Ticket. Removed traceback from FailedTask.

---

## 12. Paymob Integration Notes

- **API docs:** https://developers.paymob.com/paymob-docs/
- **API keys:** User has test keys in a `.env` file in a separate folder. No AI has access.
- **Implementation:** `PaymobPaymentProvider` class stub in `payments/providers.py`. Implement if time permits (Day 10).
- **Dev default:** `FakePaymentProvider` with 90% success rate.
- **Config:** `PAYMENT_PROVIDER_CLASS` in settings, loaded via `import_string()`.

---

## 13. Docker Services

| Service | Image | Port | Notes |
|---|---|---|---|
| db | postgres:16-alpine | 5432 | `pgdata` volume, healthcheck |
| redis | redis:7-alpine | 6379 | `appendonly yes`, `redisdata` volume |
| web | Custom Dockerfile | 8000 | Django dev server |
| celery_worker | Same Dockerfile | — | `celery -A config worker -l info` |
| celery_beat | Same Dockerfile | — | `celery -A config beat -l info` |

---

## 14. Dependencies

```
# base.txt
Django>=5.1,<5.2
djangorestframework>=3.15
djangorestframework-simplejwt>=5.3
django-redis>=5.4
celery[redis]>=5.4
django-celery-beat>=2.6
django-celery-results>=2.5
psycopg[binary]>=3.2
python-decouple>=3.8
gunicorn>=22.0

# dev.txt
-r base.txt
factory-boy>=3.3
pytest>=8.0
pytest-django>=4.8
```

---

## 15. Things the Next Agent MUST NOT Do

1. **Don't add entities** without checking this memory file first. The 9-entity count is final.
2. **Don't add fees/tax fields.** This was an explicit cut. Price is price.
3. **Don't add QR code fields.** UUID is the QR content.
4. **Don't create an IdempotencyKey table.** Use `Order.idempotency_key`.
5. **Don't create a WaitlistEntry model.** Use a comment.
6. **Don't use Django's `TestCase` for concurrency tests.** Use `TransactionTestCase`.
7. **Don't put business logic in views.** Views are thin, services do the work.
8. **Don't use floats for money.** Integer cents everywhere.
9. **Don't add microservices, API gateways, or Elasticsearch.** This is a Django monolith.
10. **Don't skip the concurrency test.** It's the entire project's credibility.
