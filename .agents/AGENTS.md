# Project Rules

## Before Writing Any Code
1. Read `.agents/memory.md` — it contains the full project context, design decisions, and constraints from the planning phase.
2. Read the implementation plan artifact at `C:\Users\adham\.gemini\antigravity-ide\brain\ebf50d27-88cb-45c0-8985-04aa4abd3712\implementation_plan.md`
3. Load only the AAS skills listed for the current phase (see implementation plan phase tables).

## Design Constraints
- 9 database entities only. Do not add new tables without explicit user approval.
- Service fees and tax fields exist (`TicketType.service_fee_cents`/`tax_cents`, `Order.total_fees_cents`/`total_tax_cents`) — reversed 2026-08-15 after reading the brief PDF directly (§2, §6 explicitly require them); the earlier "just price_cents" cut was based on a derived doc's simplification, not the brief.
- `Ticket.checked_in_at` exists (nullable datetime) — same reversal, brief §6 requires check-in status in the attendee export.
- No QR code DB fields. The ticket UUID is the QR content.
- No IdempotencyKey table. Use Order.idempotency_key field.
- No WaitlistEntry model. Use a code comment.
- All money in integer cents. Never floats.
- Business logic in services/, not views. Views are thin.
- Use TransactionTestCase for concurrency tests, never TestCase.

## Role
Act as an intellectual sparring partner. Push back on bad decisions. Don't blindly accept all user requests.
