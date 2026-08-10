# Ticketing & Reservations Backend — Final Implementation Plan

> [!IMPORTANT]
> This plan incorporates all simplifications from the [design rationale](file:///C:/Users/adham/.gemini/antigravity-ide/brain/ebf50d27-88cb-45c0-8985-04aa4abd3712/design_rationale.md) and [entity audit](file:///C:/Users/adham/.gemini/antigravity-ide/brain/ebf50d27-88cb-45c0-8985-04aa4abd3712/entity_audit.md). **9 entities** (down from 12). Every table earns its spot.

---

## Skill Manifest (Full Reference)

> [!NOTE]
> **For the implementing LLM:** Before starting each phase, load the skills listed in that phase's skill table using `@mcp:agentic-awesome-skills get_skill`. Only load skills relevant to the current phase — don't load all at once.

| Skill ID | Category | Use For |
|---|---|---|
| `django-pro` | Framework | Django 5.x, DRF, Celery, async views, project architecture |
| `postgres-best-practices` | Database | Schema design, indexing, query optimization, constraints |
| `django-perf-review` | Backend | N+1 detection, queryset optimization, ORM performance |
| `api-security-best-practices` | Security | Auth, input validation, rate limiting, API vulnerabilities |
| `api-design-principles` | Backend | REST conventions, endpoint design, error responses |
| `api-endpoint-builder` | Development | Endpoint scaffolding with validation, error handling, docs |
| `007` | Security | Threat modeling, OWASP checks, incident response |
| `container-security-hardening` | Security | Dockerfile review, non-root users, image scanning |
| `plan-writing` | Planning | Structured task breakdowns, dependencies, verification |
| `andrej-karpathy` | Guidelines | Avoid overcomplication, surgical changes, simplicity |
| `async-python-patterns` | Development | Concurrent programming, asyncio, non-blocking patterns |

---

## Architecture Overview

```mermaid
graph TD
    Client["Client (Postman / curl)"]
    
    subgraph "Django Application"
        API["DRF API Layer<br/>Views + Serializers + Throttling"]
        SVC["Service Layer<br/>Business Logic + Audit Logging"]
    end
    
    subgraph "Background Processing"
        CW["Celery Worker<br/>Purchase Processing<br/>Expiry Sweep"]
        CB["Celery Beat<br/>Periodic Sweep (60s)<br/>Daily Reconciliation"]
    end
    
    subgraph "Data Stores"
        PG["PostgreSQL 16<br/>All Business Data + DLQ"]
        RD["Redis 7<br/>Celery Broker + DRF Cache"]
    end
    
    Client -->|"JWT"| API
    API --> SVC
    SVC -->|"Enqueue Tasks"| RD
    SVC -->|"Read/Write"| PG
    RD -->|"Deliver Tasks"| CW
    CB -->|"Schedule Tasks"| RD
    CW -->|"Read/Write"| PG
```

**Key Design Decisions (post-rationale + entity audit):**

| Decision | Choice | Why |
|---|---|---|
| Concurrency control | `SELECT FOR UPDATE` (2-statement, readable) | 🟢 Zero oversell — non-negotiable |
| Inventory model | `held` + `sold` counters on TicketType | 🟢 Performance + correctness |
| Sync/Async boundary | Sync reservation, async purchase (Celery) | 🟢 Hold is instant, payment is slow |
| Reservation expiry | Periodic sweep every 60s via Celery Beat | Simpler than hybrid approach |
| Primary keys | UUID everywhere | Non-guessable, single field |
| Idempotency | `idempotency_key` unique field on Order | No separate table needed |
| Django apps | 3 apps (events, orders, core) + payments module | Minimal |
| Celery queues | Single default queue | No queue separation needed |
| Entity count | **9 entities** | Cut OrderLineItem, IdempotencyKey, WaitlistEntry |
| Fees/Tax | **CUT** — just `price_cents` | Intern project, not a billing system |
| QR codes | **CUT** — ticket identified by UUID | Can be added later in 10 minutes |

---

## Project Structure

```
PaymobTask/
├── docker-compose.yml
├── Dockerfile
├── requirements/
│   ├── base.txt
│   └── dev.txt
├── manage.py
├── config/                          # Project config
│   ├── __init__.py
│   ├── celery.py
│   ├── urls.py
│   ├── wsgi.py
│   └── settings/
│       ├── __init__.py
│       ├── base.py
│       └── dev.py
├── users/                           # Custom User model
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   └── admin.py
├── events/                          # Event + TicketType
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   ├── services.py
│   └── admin.py
├── orders/                          # Reservation + Order + Ticket + Refund
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── reservation_service.py
│   │   ├── purchase_service.py
│   │   └── refund_service.py
│   ├── tasks.py
│   ├── exporters.py
│   └── admin.py
├── payments/                        # Payment provider abstraction
│   ├── __init__.py
│   └── providers.py
├── core/                            # Cross-cutting: AuditLog, FailedTask
│   ├── models.py
│   ├── signals.py
│   └── management/
│       └── commands/
│           ├── seed_data.py
│           └── run_reconciliation.py
└── tests/
    ├── conftest.py
    ├── factories.py
    ├── test_reservations.py
    ├── test_purchases.py
    ├── test_concurrency.py          # 🏆 Crown jewel
    ├── test_refunds.py
    └── test_reconciliation.py
```

---

## Database Schema (9 Entities)

### Entity-Relationship Diagram

```mermaid
erDiagram
    User ||--o{ Reservation : creates
    User ||--o{ Order : places
    Event ||--|{ TicketType : has
    TicketType ||--o{ Reservation : "held by"
    Reservation ||--o| Order : "converts to"
    Order }|--|| TicketType : "snapshot of"
    Order ||--o{ Ticket : contains
    Order ||--o{ Refund : "refunded by"
    Ticket ||--o| Refund : "partial refund of"
    
    User {
        uuid id PK
        string email UK
        string first_name
        string last_name
    }
    
    Event {
        uuid id PK
        string title
        text description
        datetime start_date
        datetime end_date
        string venue
        string status "draft|published|cancelled|completed"
        uuid organizer_id FK "which admin created this"
        int hold_duration_minutes "default 10"
        datetime created_at
        datetime updated_at
    }
    
    TicketType {
        uuid id PK
        uuid event_id FK
        string name "e.g. VIP, General"
        int total_capacity
        int sold "default 0"
        int held "default 0"
        int price_cents
        string status "active|paused|sold_out"
        datetime created_at
        datetime updated_at
    }
    
    Reservation {
        uuid id PK
        uuid user_id FK
        uuid ticket_type_id FK
        int quantity
        string status "active|confirmed|expired|cancelled"
        datetime expires_at
        datetime created_at
    }
    
    Order {
        uuid id PK
        uuid user_id FK
        uuid event_id FK
        uuid reservation_id FK
        uuid ticket_type_id FK
        string idempotency_key UK
        int quantity
        int unit_price_cents "snapshot at purchase time"
        int total_cents
        string status "processing|confirmed|partially_refunded|refunded|failed"
        string payment_id
        string payment_provider "fake|paymob"
        datetime confirmed_at
        datetime created_at
    }
    
    Ticket {
        uuid id PK
        uuid order_id FK
        string status "active|refunded|cancelled"
        datetime created_at
    }
    
    Refund {
        uuid id PK
        uuid order_id FK
        uuid ticket_id FK "nullable - partial refunds"
        int amount_cents
        string reason
        string status "pending|processed|failed"
        string initiated_by "self-contained financial doc"
        string payment_refund_id
        datetime processed_at
        datetime created_at
    }
    
    AuditLog {
        uuid id PK
        string entity_type
        uuid entity_id
        string action
        string actor
        json changes
        text reason "answers WHY, not just WHAT"
        datetime created_at
    }
    
    FailedTask {
        uuid id PK
        string task_id UK
        string task_name
        json args
        json kwargs
        text exception_message
        int retry_count
        string resolution "null|retried|refunded|manual"
        string resolved_by
        datetime resolved_at
        datetime created_at
    }
```

### What Was Cut and Why

| Cut | Reason |
|---|---|
| **OrderLineItem table** | 1 reservation = 1 order = 1 ticket type. No multi-type cart. Fields merged into Order. |
| **IdempotencyKey table** | `Order.idempotency_key` unique field already handles dedup. Separate table was generic framework for 1 endpoint. |
| **WaitlistEntry table** | Zero code touches it. Replaced with a comment in `events/models.py`. |
| **TicketType.service_fee_cents** | Not a billing system. Just `price_cents`. |
| **TicketType.tax_cents** | Same — price is price. |
| **Order.total_fees_cents** | Gone with fees. |
| **Order.total_tax_cents** | Gone with tax. |
| **Ticket.qr_code** | UUID is the ticket identifier. QR generation is a presentation concern, add later if needed. |
| **Ticket.attendee_name** | Derived from `Order.user`. No separate attendee registration for general admission. |
| **Ticket.attendee_email** | Same — from `Order.user`. |
| **Ticket.check_in_status** | Merged into `Ticket.status` — can transition `active → checked_in` if check-in is added later. |
| **Ticket.checked_in_at** | Cut with check-in fields. |
| **Ticket.qr_code** | The UUID PK *is* the QR content. Any client encodes `ticket.id` into a QR image on-the-fly. No DB column needed. |
| **FailedTask.traceback** | Exception message is enough for ops. Full traceback is in Celery logs. |

### Critical Indexes

```sql
-- Reservation: expiry sweep needs to find active expired reservations fast
CREATE INDEX idx_reservation_expiry 
    ON orders_reservation (expires_at) 
    WHERE status = 'active';

-- Order: user's orders
CREATE INDEX idx_order_user 
    ON orders_order (user_id, created_at DESC);

-- Order: event reporting
CREATE INDEX idx_order_event_status 
    ON orders_order (event_id, status);

-- AuditLog: query by entity
CREATE INDEX idx_audit_entity 
    ON core_auditlog (entity_type, entity_id, created_at DESC);

-- FailedTask: ops dashboard
CREATE INDEX idx_failed_task_unresolved 
    ON core_failedtask (created_at DESC) 
    WHERE resolved_at IS NULL;
```

### Database Constraints

```sql
ALTER TABLE events_tickettype ADD CONSTRAINT chk_sold_non_negative CHECK (sold >= 0);
ALTER TABLE events_tickettype ADD CONSTRAINT chk_held_non_negative CHECK (held >= 0);
ALTER TABLE events_tickettype ADD CONSTRAINT chk_no_oversell CHECK (sold + held <= total_capacity);
ALTER TABLE events_tickettype ADD CONSTRAINT chk_price_positive CHECK (price_cents >= 0);
ALTER TABLE orders_order ADD CONSTRAINT chk_total_positive CHECK (total_cents >= 0);
ALTER TABLE orders_refund ADD CONSTRAINT chk_refund_positive CHECK (amount_cents > 0);
```

> [!TIP]
> **💡 Tip for you:** These constraints are your last line of defense. Even if your Python code has a bug, the database refuses to enter an invalid state. If you ever see a `CHECK constraint violation` error, it means you found a concurrency bug before it reached production. Treat it as a gift, not a problem.

---

## Core Flows (Simplified Code)

### Reservation (Synchronous — 2-Statement Pattern)

```python
# orders/services/reservation_service.py

def create_reservation(user, ticket_type_id, quantity):
    with transaction.atomic():
        ticket_type = (
            TicketType.objects
            .select_for_update()
            .select_related('event')
            .get(id=ticket_type_id, status='active')
        )
        
        available = ticket_type.total_capacity - ticket_type.sold - ticket_type.held
        if available < quantity:
            raise InsufficientCapacityError(
                f"Requested {quantity}, only {available} available"
            )
        
        ticket_type.held += quantity
        ticket_type.save(update_fields=['held', 'updated_at'])
        
        reservation = Reservation.objects.create(
            user=user,
            ticket_type=ticket_type,
            quantity=quantity,
            status='active',
            expires_at=now() + timedelta(minutes=ticket_type.event.hold_duration_minutes),
        )
        
        AuditLog.record(
            entity_type='ticket_type',
            entity_id=ticket_type.id,
            action='inventory_held',
            actor=user.email,
            changes={'held_delta': quantity, 'reservation_id': str(reservation.id)},
        )
    
    return reservation
```

### Purchase (Asynchronous — Celery)

```python
# orders/views.py

class PurchaseView(APIView):
    throttle_scope = 'purchase'
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = PurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        idem_key = request.headers.get('Idempotency-Key')
        if not idem_key:
            return Response({'error': 'Idempotency-Key header required'}, status=400)
        
        # Idempotency check — Order.idempotency_key is unique
        existing_order = Order.objects.filter(idempotency_key=idem_key).first()
        if existing_order:
            return Response(OrderSerializer(existing_order).data)
        
        reservation_id = serializer.validated_data['reservation_id']
        process_purchase_task.delay(
            reservation_id=str(reservation_id),
            idempotency_key=idem_key,
            actor_email=request.user.email,
        )
        
        return Response({'status': 'processing', 'idempotency_key': idem_key}, status=202)


# orders/services/purchase_service.py

def process_purchase(reservation_id, idempotency_key, actor_email):
    with transaction.atomic():
        reservation = (
            Reservation.objects
            .select_for_update()
            .select_related('ticket_type', 'ticket_type__event', 'user')
            .get(id=reservation_id)
        )
        
        if reservation.status != 'active':
            raise ReservationNotActiveError()
        if reservation.expires_at < now():
            reservation.status = 'expired'
            reservation.save(update_fields=['status'])
            raise ReservationExpiredError()
        
        ticket_type = reservation.ticket_type
        total = ticket_type.price_cents * reservation.quantity
        
        # Payment (Strategy Pattern)
        provider = get_payment_provider()
        result = provider.capture(
            amount_cents=total,
            token="user_payment_token",
            idempotency_key=idempotency_key,
        )
        if not result.success:
            raise PaymentFailedError(result.error)
        
        # Move held → sold
        ticket_type.held -= reservation.quantity
        ticket_type.sold += reservation.quantity
        ticket_type.save(update_fields=['held', 'sold', 'updated_at'])
        
        # Create order (with price snapshot)
        order = Order.objects.create(
            user=reservation.user,
            event=ticket_type.event,
            reservation=reservation,
            ticket_type=ticket_type,
            idempotency_key=idempotency_key,
            quantity=reservation.quantity,
            unit_price_cents=ticket_type.price_cents,
            total_cents=total,
            status='confirmed',
            payment_id=result.payment_id,
            payment_provider=provider.name,
            confirmed_at=now(),
        )
        
        # Create individual tickets
        Ticket.objects.bulk_create([
            Ticket(order=order, status='active')
            for _ in range(reservation.quantity)
        ])
        
        reservation.status = 'confirmed'
        reservation.save(update_fields=['status'])
        
        AuditLog.record(
            entity_type='ticket_type',
            entity_id=ticket_type.id,
            action='inventory_sold',
            actor=actor_email,
            changes={
                'held_delta': -reservation.quantity,
                'sold_delta': reservation.quantity,
                'order_id': str(order.id),
            },
        )
    
    return order
```

### Reservation Expiry (Periodic Sweep)

```python
# orders/tasks.py

@shared_task
def sweep_expired_reservations():
    """Runs every 60s via Celery Beat. Finds expired active reservations."""
    expired_count = 0
    
    with transaction.atomic():
        stale = (
            Reservation.objects
            .filter(status='active', expires_at__lt=now())
            .select_related('ticket_type')
            .select_for_update(skip_locked=True)
        )
        
        for reservation in stale:
            reservation.ticket_type.held = F('held') - reservation.quantity
            reservation.ticket_type.save(update_fields=['held', 'updated_at'])
            reservation.status = 'expired'
            reservation.save(update_fields=['status'])
            
            AuditLog.record(
                entity_type='reservation',
                entity_id=reservation.id,
                action='reservation_expired',
                actor='system',
                changes={'status_old': 'active', 'status_new': 'expired'},
            )
            expired_count += 1
    
    if expired_count:
        logger.info(f"Expired {expired_count} stale reservations")
```

### Refund (Partial + Full)

```python
# orders/services/refund_service.py

def issue_refund(order_id, ticket_ids=None, reason='', actor_email=''):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(id=order_id)
        
        if order.status in ('refunded', 'failed'):
            raise InvalidRefundError(f"Order is {order.status}")
        
        if ticket_ids:
            tickets = Ticket.objects.filter(
                id__in=ticket_ids, order=order, status='active'
            )
        else:
            tickets = Ticket.objects.filter(order=order, status='active')
        
        if not tickets.exists():
            raise InvalidRefundError("No active tickets to refund")
        
        ticket_count = tickets.count()
        refund_amount = order.unit_price_cents * ticket_count
        
        provider = get_payment_provider()
        result = provider.refund(order.payment_id, refund_amount)
        if not result.success:
            raise PaymentRefundFailedError(result.error)
        
        # One refund record for the batch
        refund = Refund.objects.create(
            order=order,
            amount_cents=refund_amount,
            reason=reason,
            initiated_by=actor_email,
            status='processed',
            payment_refund_id=result.payment_id,
            processed_at=now(),
        )
        
        # Mark individual tickets as refunded
        tickets.update(status='refunded')
        
        # If partial refund, link refund to specific tickets
        if ticket_ids:
            refund.ticket_id = ticket_ids[0]  # Link to first for reference
            refund.save(update_fields=['ticket_id'])
        
        # Restore inventory
        TicketType.objects.filter(id=order.ticket_type_id).update(
            sold=F('sold') - ticket_count
        )
        
        # Update order status
        remaining = Ticket.objects.filter(order=order, status='active').count()
        order.status = 'refunded' if remaining == 0 else 'partially_refunded'
        order.save(update_fields=['status'])
        
        AuditLog.record(
            entity_type='order',
            entity_id=order.id,
            action='refund_issued',
            actor=actor_email,
            changes={
                'refund_amount_cents': refund_amount,
                'tickets_refunded': ticket_count,
            },
        )
    
    return order
```

---

## Rate Limiting

```python
# config/settings/base.py

REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.ScopedRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {
        'reserve': '10/min',
        'purchase': '5/min',
        'refund': '3/min',
        'events_list': '60/min',
    },
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://redis:6379/1',
    },
}
```

---

## DLQ (Dead Letter Queue)

```python
# core/signals.py

from celery.signals import task_failure

@task_failure.connect
def handle_task_failure(sender, task_id, exception, args, kwargs, **kw):
    """After all retries exhausted, capture to DLQ table."""
    FailedTask.objects.create(
        task_id=task_id,
        task_name=sender.name,
        args=list(args) if args else [],
        kwargs=dict(kwargs) if kwargs else {},
        exception_message=str(exception),
        retry_count=getattr(sender.request, 'retries', 0),
    )
```

---

## Payment Provider (Strategy Pattern)

```python
# payments/providers.py

class PaymentResult:
    def __init__(self, success, payment_id=None, error=None):
        self.success = success
        self.payment_id = payment_id
        self.error = error

class PaymentProvider(ABC):
    name: str
    
    @abstractmethod
    def capture(self, amount_cents, token, idempotency_key) -> PaymentResult: ...
    
    @abstractmethod
    def refund(self, payment_id, amount_cents) -> PaymentResult: ...

class FakePaymentProvider(PaymentProvider):
    name = 'fake'
    
    def capture(self, amount_cents, token, idempotency_key):
        if random.random() < 0.9:
            return PaymentResult(success=True, payment_id=f"fake_{uuid4().hex[:12]}")
        return PaymentResult(success=False, error="Simulated decline")
    
    def refund(self, payment_id, amount_cents):
        return PaymentResult(success=True, payment_id=f"fake_ref_{uuid4().hex[:12]}")

class PaymobPaymentProvider(PaymentProvider):
    """
    Paymob Accept API integration.
    Docs: https://developers.paymob.com/paymob-docs/
    API keys loaded from environment variables (never in code).
    """
    name = 'paymob'
    
    def capture(self, amount_cents, token, idempotency_key):
        # TODO: Implement via Paymob Accept API
        raise NotImplementedError("Paymob integration pending")

def get_payment_provider() -> PaymentProvider:
    provider_class = import_string(settings.PAYMENT_PROVIDER_CLASS)
    return provider_class()
```

---

## Celery Configuration

```python
# config/celery.py
app = Celery('paymob_ticketing')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# config/settings/base.py
CELERY_BROKER_URL = 'redis://redis:6379/0'
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

CELERY_BEAT_SCHEDULE = {
    'sweep-expired-reservations': {
        'task': 'orders.tasks.sweep_expired_reservations',
        'schedule': 60.0,
    },
    'daily-reconciliation': {
        'task': 'core.tasks.run_reconciliation_task',
        'schedule': crontab(hour=2, minute=0),
    },
}
```

---

## Reporting & CSV Schemas

**Daily Sales Report:**
```csv
date,event_id,event_title,orders_count,gross_revenue_cents,total_refunds_cents,net_revenue_cents
2026-08-04,evt_abc,"Summer Concert",150,1500000,50000,1450000
```

**Attendee Export:**
```csv
ticket_id,order_id,user_email,ticket_type,unit_price_cents,ticket_status
tkt_def,ord_abc,adham@example.com,"VIP",15000,"active"
```

**Reconciliation Report:**
```csv
ticket_type_id,name,total_capacity,sold,held,computed_available,actual_sold,actual_held,drift_sold,drift_held,status
uuid_here,"VIP",100,45,10,45,45,10,0,0,"OK"
```

---

## Operational Runbooks

### Incident: Stuck Worker or Backlog

| Field | Value |
|---|---|
| **Owner** | Ops / On-call |
| **Detection** | Queue length > 1000 for > 5 min |
| **TTR** | 15–30 minutes |

```bash
celery -A config inspect ping
celery -A config inspect active
redis-cli LLEN celery
docker-compose restart celery_worker
docker-compose up --scale celery_worker=3  # If queue is huge
```

### Incident: Oversell Detected

| Field | Value |
|---|---|
| **Owner** | Ops + Product |
| **Detection** | Reconciliation drift ≠ 0 |
| **TTR** | 1–4 hours |

```bash
# 1. Pause sales
python manage.py shell -c "TicketType.objects.filter(event_id='<ID>').update(status='paused')"

# 2. Run reconciliation
python manage.py run_reconciliation --event-id <ID>

# 3. Check audit logs for root cause
python manage.py shell -c "AuditLog.objects.filter(entity_type='ticket_type', entity_id='<ID>').order_by('-created_at')[:20]"
```

### Incident: Payment Captured but Order Not Created

| Field | Value |
|---|---|
| **Owner** | Ops + Finance |
| **Detection** | DLQ entry for `process_purchase_task` |
| **TTR** | 30–60 minutes |

```bash
python manage.py shell -c "FailedTask.objects.filter(task_name='orders.tasks.process_purchase_task', resolved_at__isnull=True)"
# Verify payment in Paymob dashboard → retry task OR manual refund
```

### Incident: Redis Down

| Field | Value |
|---|---|
| **Owner** | Ops |
| **Detection** | Celery tasks stop processing |
| **TTR** | 5–15 minutes |

```bash
redis-cli ping
docker-compose restart redis
celery -A config inspect ping
python manage.py shell -c "from orders.tasks import sweep_expired_reservations; sweep_expired_reservations()"
```

> [!NOTE]
> Reservations are in Postgres (durable). Redis down only pauses async tasks (purchase processing, expiry sweep). `appendonly yes` restores the task queue on recovery.

### Daily Maintenance

```bash
python manage.py run_reconciliation        # Expect: 0 drift
python manage.py shell -c "FailedTask.objects.filter(resolved_at__isnull=True).count()"  # Expect: 0
redis-cli LLEN celery                      # Expect: < 100
celery -A config inspect ping              # Expect: all pong
```

---

## Metrics & KPIs

| Metric | Implementation | Alert |
|---|---|---|
| Orders/hour | `Order.objects.filter(created_at__gte=1h_ago).count()` | — |
| Revenue/event | `SUM(total_cents) GROUP BY event` | — |
| Remaining/type | `total_capacity - sold - held` | < 10% |
| DLQ size | `FailedTask.objects.filter(resolved_at__isnull=True).count()` | > 0 |
| Oversell drift | Reconciliation | **CRITICAL** |
| Queue length | `redis-cli LLEN celery` | > 1000 |
| Checkout success | `confirmed / (confirmed + failed)` | < 95% |

---

## Docker Compose

```yaml
version: '3.8'

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: paymob_ticketing
      POSTGRES_USER: paymob
      POSTGRES_PASSWORD: devpassword
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U paymob"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    ports: ["6379:6379"]
    volumes: [redisdata:/data]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    volumes: [.:/app]
    ports: ["8000:8000"]
    env_file: .env
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }

  celery_worker:
    build: .
    command: celery -A config worker -l info
    volumes: [.:/app]
    env_file: .env
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }

  celery_beat:
    build: .
    command: celery -A config beat -l info
    volumes: [.:/app]
    env_file: .env
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }

volumes:
  pgdata:
  redisdata:
```

---

## Dependencies

```
# requirements/base.txt
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

# requirements/dev.txt
-r base.txt
factory-boy>=3.3
pytest>=8.0
pytest-django>=4.8
```

---

## 10-Day Implementation Phases with Skill Annotations

> [!IMPORTANT]
> **For the implementing LLM:** Before each phase, load ONLY the skills listed in that phase's table via `@mcp:agentic-awesome-skills get_skill`.

---

### Phase 1: Foundation (Day 1)

**Deliverables:** Django project scaffolding, Docker Compose running, Custom User, JWT auth, settings split.

| Load Skill | Why |
|---|---|
| `django-pro` | Django 5.x project structure, Celery config, DRF setup |
| `container-security-hardening` | Dockerfile best practices (non-root user, multi-stage build) |
| `andrej-karpathy` | Avoid overcomplicating the scaffolding |

**Tasks:**
- [ ] `Dockerfile` + `docker-compose.yml` + `.env.example`
- [ ] Django project init (`config/` as project, split settings)
- [ ] Custom User model (`users/` app, `AbstractUser`, `AUTH_USER_MODEL`)
- [ ] JWT auth (simplejwt — register, login, token refresh endpoints)
- [ ] DRF config (throttling, JSON renderer, exception handler)
- [ ] Redis + Celery base config
- [ ] Verify: `docker-compose up` starts all 5 services, JWT login works

---

### Phase 2: Event Domain + Schema (Day 2)

**Deliverables:** Event and TicketType models, admin panel, CRUD API, DB constraints.

| Load Skill | Why |
|---|---|
| `postgres-best-practices` | Schema design, indexing strategy, CHECK constraints |
| `api-design-principles` | REST endpoint naming, response structure, status codes |
| `api-endpoint-builder` | DRF viewset scaffolding with validation |

**Tasks:**
- [ ] `events/models.py` — Event, TicketType (lean fields per this plan)
- [ ] Django admin for Event + TicketType (for manual data entry)
- [ ] Event CRUD API (list, retrieve, create)
- [ ] TicketType API (list per event, retrieve with availability)
- [ ] DB migration + apply constraints (CHECK, indexes)
- [ ] `computed_available` property: `total_capacity - sold - held`
- [ ] Verify: Create event + ticket types via admin, read via API

---

### Phase 3: Reservation Flow + Concurrency (Days 3–4)

**Deliverables:** Reservation creation with `SELECT FOR UPDATE`, expiry sweep, **concurrency test** 🏆

| Load Skill | Why |
|---|---|
| `django-pro` | `select_for_update()`, `transaction.atomic()`, Celery Beat |
| `postgres-best-practices` | Row-level locking, partial indexes |
| `django-perf-review` | Avoid N+1 in reservation queries |
| `007` | Rate limiting on reservation endpoint |

**Tasks:**
- [ ] `orders/models.py` — Reservation model
- [ ] `orders/services/reservation_service.py` — `create_reservation()` with `SELECT FOR UPDATE`
- [ ] `orders/views.py` — POST `/api/reservations/` (throttle_scope='reserve')
- [ ] Cancel reservation endpoint (user-initiated)
- [ ] `orders/tasks.py` — `sweep_expired_reservations()` (periodic, every 60s)
- [ ] Celery Beat schedule config
- [ ] `core/models.py` — AuditLog model + `AuditLog.record()` class method
- [ ] **🏆 Concurrency test**: 100 threads, 50 remaining tickets → exactly 50 successes, 50 failures
- [ ] Verify: reservation creates hold, expiry sweep cleans up, concurrency test passes

> [!WARNING]
> **💡 Critical tip:** Use `TransactionTestCase` (not `TestCase`) for the concurrency test. Django's default `TestCase` wraps everything in a single transaction, so threads can't see each other's writes. This is the #1 gotcha.

---

### Phase 4: Purchase Flow (Day 5)

**Deliverables:** Order + Ticket creation, Celery task, payment strategy pattern, DLQ.

| Load Skill | Why |
|---|---|
| `django-pro` | Celery task definition, `bind=True`, retries |
| `api-security-best-practices` | Idempotency key handling, input validation |
| `async-python-patterns` | Celery task patterns, retry with backoff |

**Tasks:**
- [ ] `orders/models.py` — Order (with `ticket_type_id`, `unit_price_cents`, `idempotency_key`), Ticket (lean: just `order_id` + `status`)
- [ ] `payments/providers.py` — PaymentProvider ABC, FakeProvider, PaymobProvider stub
- [ ] `orders/services/purchase_service.py` — `process_purchase()`
- [ ] `orders/tasks.py` — `process_purchase_task` (3 retries, exponential backoff)
- [ ] `orders/views.py` — POST `/api/purchases/` (idempotency check via `Order.idempotency_key`)
- [ ] GET `/api/orders/{id}/` — order detail with tickets
- [ ] `core/models.py` — FailedTask model
- [ ] `core/signals.py` — Celery `task_failure` signal → FailedTask
- [ ] Verify: reserve → purchase → order created, duplicate idempotency key returns same result

---

### Phase 5: Refunds + Audit (Days 6–7)

**Deliverables:** Full and partial refund flow, audit logging throughout.

| Load Skill | Why |
|---|---|
| `django-pro` | `select_for_update()` in refund, `F()` expressions |
| `postgres-best-practices` | Atomic inventory restoration |
| `api-design-principles` | Refund endpoint design, error responses |

**Tasks:**
- [ ] `orders/models.py` — Refund model
- [ ] `orders/services/refund_service.py` — `issue_refund()` (partial + full)
- [ ] POST `/api/refunds/` endpoint (throttle_scope='refund')
- [ ] Verify inventory restoration: refund → `sold` decremented → tickets available again
- [ ] Add `AuditLog.record()` calls to ALL service functions
- [ ] Comment in `events/models.py` for future WaitlistEntry
- [ ] Verify: full refund, partial refund, inventory restored, audit trail complete

---

### Phase 6: Reporting + Reconciliation (Day 8)

**Deliverables:** CSV exports, reconciliation service, metrics endpoint, seed data command.

| Load Skill | Why |
|---|---|
| `django-perf-review` | Efficient queryset aggregation for reports |
| `postgres-best-practices` | Aggregate queries, `annotate()`, `Sum()` |

**Tasks:**
- [ ] `orders/exporters.py` — CSV generators (sales, attendee, reconciliation)
- [ ] Report API endpoints: GET `/api/reports/sales/`, `/api/reports/attendees/`
- [ ] `core/management/commands/run_reconciliation.py` — compare counters vs derived counts
- [ ] `core/management/commands/seed_data.py` — create test events, users, ticket types
- [ ] Metrics endpoint: GET `/api/metrics/` — all KPIs in JSON
- [ ] Verify: reconciliation shows 0 drift after a full reservation → purchase → refund cycle

---

### Phase 7: Testing + Load Test (Day 9)

**Deliverables:** Full test suite, load test script, all acceptance criteria verified.

| Load Skill | Why |
|---|---|
| `django-perf-review` | Identify N+1 queries in test runs |
| `007` | Security testing checklist (auth bypass, rate limit bypass) |
| `api-security-best-practices` | Validate rate limits, auth, input validation in tests |

**Tasks:**
- [ ] `tests/factories.py` — factory_boy factories for all 9 models
- [ ] `tests/test_reservations.py` — unit + integration tests
- [ ] `tests/test_purchases.py` — idempotency, expired reservation, payment failure
- [ ] `tests/test_concurrency.py` — 🏆 THE concurrency test (should already exist from Day 4)
- [ ] `tests/test_refunds.py` — full, partial, double-refund prevention
- [ ] `tests/test_reconciliation.py` — verify 0 drift after complex scenarios
- [ ] Load test script (simple Python `concurrent.futures` script)
- [ ] Verify: all tests pass, load test shows < 500ms reservation, < 2s purchase enqueue

---

### Phase 8: Polish + Documentation (Day 10)

**Deliverables:** README, runbook docs, Paymob provider stub, final review.

| Load Skill | Why |
|---|---|
| `andrej-karpathy` | Final review for overcomplication, unused code |
| `plan-writing` | Structured documentation |
| `api-design-principles` | API documentation quality |

**Tasks:**
- [ ] README.md — architecture diagram, setup instructions, API docs, design decisions
- [ ] Runbook documentation (in README or `docs/`)
- [ ] Paymob provider: implement if test API keys available, otherwise detailed stub
- [ ] Code cleanup: remove dead code, add docstrings to services
- [ ] Final `docker-compose up` from clean state → verify everything works
- [ ] Run full test suite one final time
- [ ] Verify: someone cloning the repo can `docker-compose up` and start testing within 5 minutes

---

## Critical Path

> [!CAUTION]
> **If you fall behind, this is the priority order:**
> 1. **Days 1–4: Reservation + concurrency test passes** — Nothing else matters if oversell is possible
> 2. **Day 5: Purchase flow works end-to-end** — Reserve → Pay → Order created
> 3. **Days 6–7: Refunds restore inventory** — Core business requirement
> 4. **Days 8–10: Everything else is polish** — Reports, docs, load tests, Paymob

If Day 4's concurrency test fails, **stop everything and fix it.** The entire project's credibility rests on zero oversell.
