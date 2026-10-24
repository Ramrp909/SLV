# AGENTS.md: Paint Shop Management System (read before every task)

This file is loaded automatically by AI coding assistants (Kilo reads `AGENTS.md` from the project root). The complete specification is `docs/blueprint/` (split from `paint-shop-blueprint.md`). If a task conflicts with the blueprint, **stop and ask**; never silently change a business rule.

## Project
Single-owner paint and hardware shop: inventory, GST invoicing, customers and dues, broker commissions, companies (suppliers), employees, expenses, reports. Stack: **Django 5 + Django REST Framework + PostgreSQL 16** backend, **React 18 + Vite** frontend (built last), REST API `/api/v1`, JWT auth (one owner user).

## Golden rules (never break)
1. **Backend is authoritative.** All money, GST, stock, commission, numbering and profit logic lives in backend services. React only displays and previews.
2. **Money and quantities use `decimal.Decimal`**, never float. Database: `DECIMAL`. Rounding: `ROUND_HALF_UP` to 2 decimals at line level (use the helper in `common/money.py`).
3. **Product-wise GST.** Each product has its own GST rate and HSN. Rates must exist in the `gst_rates` table (approved list). **Never hard-code a GST rate or HSN** anywhere except inside tests and docs, where they are labelled illustrative.
4. **Selling prices are GST-inclusive by default** (`prices_include_gst`).
5. **Commission** = `round(invoice.grand_total x commission_percent / 100, 2)`, using the saved `grand_total` (final amount incl. GST after discounts). The client may send only an optional commission percent override, never a base or amount. Commission accrues at invoice issue and is reversed proportionally by returns/cancellations through `commission_adjustments`.
6. **Stock changes only through `StockService`** (`apps/stock/services.py`), with a row lock on the product (`select_for_update`, fixed order). Weighted average inventory cost: recoverable GST excluded, non-recoverable GST included.
7. **Snapshots:** invoice lines store product code/name, HSN, GST rate, selling price, taxable value, tax amounts, discount allocation and cost snapshot. Later product changes must never alter issued invoices.
8. **Append-only records:** issued invoices, credit notes, receipts, stock movements, payments, commission adjustments and audit logs are never edited or deleted. Corrections are returns, cancellations, adjustments or new rows.
9. **Atomic and idempotent:** every create of an invoice, purchase, purchase return, receipt, credit note or payout runs inside `transaction.atomic()` and requires an `Idempotency-Key` header (unique constraint in the database).
10. **Audit every write** through `AuditService` (before/after JSON, actor, IP). Back-dated invoices are flagged.
11. **No overpayments** in Version 1: payments and receipts cannot exceed the outstanding due (`PAYMENT_EXCEEDS_DUE`).
12. **Invoice print data never contains** commission, cost or profit fields (separate serializer plus a test).
13. **Profit definitions:** gross profit = revenue excluding GST minus cost of goods sold; profit after commission = gross profit minus commission expense; net profit = profit after commission minus operating expenses. A manual line without internal cost has **unknown** profit (never zero) and sets `profit_complete = false`.
14. **Deactivate, never delete** records with history (products, companies, customers, brokers, employees).

## Code structure and style
- Django apps under `backend/apps/`: `core`, `accounts`, `catalog`, `stock`, `purchasing`, `parties`, `billing`, `commissions`, `hr`, `finance`, `analytics`. Shared helpers in `backend/common/`.
- **Thin views, logic in services.** Pattern: `models.py`, `services.py` (writes and business rules), `selectors.py` (read queries), `serializers.py`, `views.py`, `urls.py`, `tests/`.
- Business calculations are **pure functions** where possible (`calc.py`) so they can be unit-tested without a database.
- Python 3.12, type hints on public functions, `ruff` for lint and format. Every database change is a committed migration.
- Standard error format: `{ "code": "...", "message": "...", "fields": {...} }`. Lists use `page` and `page_size`; money returned as strings.
- Do not add new dependencies, rename existing models/fields, or change the database schema outside the current task without asking.

## How to work on a task
1. Read the task prompt and the attached blueprint sections only. Restate the goal in two lines.
2. **Write or update tests first** (or together), then the code.
3. Run `make test` (or the command in the task). **Do not say a task is done while any test fails.** Never weaken or delete a test to make it pass; explain if a test is wrong.
4. Reply with: files created or changed, commands run with results, anything left undone, any blueprint conflict found.
5. Keep changes inside the task scope; no unrelated refactoring.

## Safety
- Use **fake sample data only**. Never put real customer, supplier, price or business data into prompts or fixtures.
- Never read or print `.env` or secrets; use `.env.example` for variable names.
- Do not run destructive commands (drop database, `rm -rf`, force push) without explicit approval.
