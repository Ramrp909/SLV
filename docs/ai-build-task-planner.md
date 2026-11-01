# AI Build Task Planner: Paint Shop Management System

Companion to `paint-shop-blueprint.md` (version 4). It splits the blueprint into small tasks that you give to an AI coding assistant **one at a time**: task, AI writes code, build and run, test, review, commit, next task. **Backend and database come first; the frontend is built last**, and its design is prepared separately (Figma AI or Claude Design) before frontend coding starts.

---

## 1. Is this setup suitable?

**Short answer: yes, with a strict test-and-review loop.** Free models can build this kind of application (CRUD, APIs, forms, reports) if every task is small and every result is tested. The risky parts are the **money, GST, stock and commission rules**, because a model can write code that looks right but is quietly wrong. This plan handles that by (a) writing those rules as pure functions with tests built from the blueprint's worked examples, (b) marking them as critical tasks (warning sign in the task list) that need a second review, and (c) never trusting a task as done until tests pass.

What I checked about your tools (as listed on OpenRouter in October 2026):

| Item | What the pages say | What it means for you |
|---|---|---|
| NVIDIA Nemotron 3 Ultra (free) | Model ID `nvidia/nemotron-3-ultra-550b-a55b:free`; released 4 June 2026; 55B active of 550B parameters; up to 1M-token context; supports tool calling; described as suited to coding agents and long agentic workflows | Good fit as a planner/reviewer or coder in Kilo |
| Thinking Machines Inkling (free) | Model ID `thinkingmachines/inkling:free`; released 17 July 2026; 41B active of 975B parameters; supports tool calling; the page says the free endpoint is **only for use with agentic harnesses** | Use it from Kilo (an agentic tool), not from a plain chat script. If requests are refused, check the page terms |
| Privacy of free endpoints | The Nemotron free endpoint page says not to upload confidential or personal data and that use is logged and may be used to improve NVIDIA products. The Inkling free endpoint is covered by the Thinking Machines free research terms | **Use fake sample data only.** Never paste real customers, prices, GSTIN or supplier details into prompts |
| OpenRouter free limits | Free models: 20 requests per minute; 50 requests per day, or 1,000 per day once you have bought at least $10 of credits (the higher limit stays) | An agent makes one request for every step (read file, edit, run test). 50 per day is far too low for this project. Buying the $10 credit once (still using the free models) is strongly recommended |
| Kilo extension rules | Kilo reads `AGENTS.md` from the project root (and from sub-folders), and also supports a rules folder (`.kilo/rules/` or the older `.kilocode/rules/`) | The supplied `AGENTS.md` carries the project's non-negotiable rules into every task |

I cannot verify how well these two newer models write Django and financial code. Treat them like any new developer: small tasks, tests first, review the diff. If a model keeps failing a critical task, try the other model, shrink the task, or use a stronger model for that task only.

---

## 2. One-time tool setup (you do this by hand)

1. Install VS Code, Python 3.12, Node 20+, Docker Desktop, Git.
2. Create an OpenRouter account and API key. Buy the $10 credit once to lift the free-model limit to 1,000 requests per day (the free models stay free per token). Check your limits at any time with the key information request shown in the OpenRouter limits page.
3. Install the Kilo extension in VS Code. Add the OpenRouter provider and your key. Add two profiles: `nvidia/nemotron-3-ultra-550b-a55b:free` and `thinkingmachines/inkling:free`.
4. Create the project folder and unzip **`project-starter-kit.zip`** into it. It gives you `AGENTS.md`, the split blueprint in `docs/blueprint/`, this planner, the Excel template and the diagrams.
5. Run `git init`; commit the starter kit as the first commit.
6. Keep real data out of the folder. Use only fake data for tests.

**Suggested model roles (try both on the first two tasks, then keep what works):**
- **Builder:** the model that gave the cleaner result in T-002/T-003.
- **Reviewer:** the other model, asked to review the diff for rule violations (use the Review prompt in section 4).
- **Critical tasks (marked CRITICAL):** generate with one, review with the other, and check the numbers against the blueprint's worked examples yourself.

**Request budget (rough estimate):** about 90 tasks x 30 to 60 requests, plus fixes, is roughly 3,000 to 6,000 requests: about 4 to 8 working days of the 1,000-per-day limit, so plan on 1 to 3 weeks of calendar time at a comfortable pace. If you hit "Rate limit exceeded", wait a minute and continue; do not keep re-sending.

---

## 3. The loop for every task

```
 1. Open the task card below.                      (you)
 2. Start a NEW chat/task in Kilo.                 (fresh context every task)
 3. Attach: AGENTS.md (auto) + the blueprint files named in "Attach".   (you)
 4. Paste the task prompt (inside the master template, section 4).      (you)
 5. AI writes tests + code.                        (AI)
 6. Run the commands in "Run and test".            (you or the AI)
 7. Red? Paste the failing output into the Fix prompt. Max 3 rounds, then
    shrink the task or switch model.                (you + AI)
 8. Green? Run the Review prompt with the other model.                  (AI)
 9. Check "Done when". Commit: git commit -m "T-xxx short title".       (you)
10. Next task.
```

**Rules of thumb**
- One task per chat; never carry a long chat across tasks.
- Attach only the files named in the task (small context, fewer mistakes, fewer requests).
- Work on a git branch per phase; merge only when the phase **Gate** passes.
- Never let the AI change the blueprint. If it reports a conflict, you decide, update the blueprint, then continue.
- Keep a file `docs/decisions.md` for any deviation you approve.

**Blueprint context files** (in `docs/blueprint/`): `s01` scope, `s02` decisions, `s03` stack, `s04` architecture, `s05` UI spec, `s06` business logic, `s07` database, `s08` API, `s09` screens, `s10` roadmap, `s11` non-functional, `s12` worked examples, `s13` open items, `s14` glossary, `s15` product master and Excel, `s16` diagrams, `s17` future-ready, `s18` AI plan.

---

## 4. Prompt templates

**Master template** (fill the three fields from the task card):

```
ROLE: Senior Django / PostgreSQL engineer working in this repository. Follow AGENTS.md exactly.
TASK: <task id and title>
CONTEXT: The attached blueprint sections are the source of truth. If anything conflicts, stop and tell me.
GOAL AND REQUIREMENTS: <paste the Prompt from the task card>
DELIVERABLES: <paste Deliverables>
PROCESS: Write tests first, then code. Run <Run and test command>. Fix until all tests pass.
FINAL REPLY: files created or changed, commands run with results, anything not done, any blueprint conflict.
```

**Fix prompt** (when tests fail):

```
The tests fail. Here is the full output: <paste>. Fix the code (not the tests) unless a test contradicts the blueprint,
in which case tell me which blueprint section it contradicts. Change only what is needed. Re-run and show results.
```

**Review prompt** (second model, after green tests):

```
Review this diff against AGENTS.md and the attached blueprint sections. Check: Decimal only, rounding half-up, product-wise GST (no hard-coded rates),
GST-inclusive prices, commission on saved grand_total, StockService only, append-only records, idempotency, atomic transactions, audit entries,
snapshots, no commission/cost/profit in print data. List violations and risks with file and line. Do not rewrite code unless asked.
```

**Stuck prompt** (after 3 failed rounds): "Summarise what you tried, the exact error, and propose two smaller sub-tasks that would each be testable alone."

---

## 5. Definition of done (every task)
- Tests written and passing (`make test`); linter clean (`make lint`).
- No rule in `AGENTS.md` violated; Review prompt found no open violation.
- Migrations committed; no unrelated file changed.
- The task's "Done when" line is true.
- Committed with the task id.

CRITICAL marks tasks where a mistake silently corrupts money or stock. They need the Review prompt and a manual check of the numbers.

---

## 6. Phase overview

| Phase | Name | Tasks | Gate (what must work before moving on) |
|---|---|---|---|
| 0 | Project setup | T-001 to T-004 | Empty project runs, tests and CI green |
| 1 | Backend foundation | T-101 to T-106 | Owner can log in; settings, GST rates, numbering, audit, idempotency work |
| 2 | Catalog and products | T-201 to T-204 | Companies and products via API with validation |
| 3 | Stock engine | T-301 to T-304 | Weighted average and concurrency tests pass |
| 4 | Purchasing and company dues | T-401 to T-405 | Purchases with GST split, company payments and dues |
| 5 | Excel import | T-501 to T-504 | Your template imports with preview, opening stock loaded **(Milestone M1)** |
| 6 | Customers and brokers | T-601 to T-603 | Master data complete |
| 7 | Billing calculation (pure) | T-701 to T-703 | Worked examples 12.2, 12.3, 12.4 reproduced exactly |
| 8 | Invoices, payments, returns | T-801 to T-806 | Full invoice life cycle via API **(Milestone M2)** |
| 9 | Commissions and brokers | T-901 to T-903 | Payouts, ledger, performance **(Milestone M3)** |
| 10 | Employees and expenses | T-1001 to T-1003 | Attendance, salary, expenses |
| 11 | Analytics and reports | T-1101 to T-1107 | Dashboard, reports, stock take, exports |
| 12 | Backend hardening | T-1201 to T-1206 | OpenAPI complete, security, backups, performance, backend frozen |
| 13 | Design pass | T-1301 | Mockups and design tokens approved |
| 14 | Frontend foundation | T-1401 to T-1405 | Login and empty shell working against the API |
| 15 | Frontend modules | T-1501 to T-1514 | Every screen works end to end |
| 16 | Integration and go-live | T-1601 to T-1604 | E2E tests, deployment, real data import, UAT, go-live |

---

## 7. Tasks

Format of each card: **Depends on** (finish those first), **Attach** (blueprint files; `6.3` means that subsection), **Prompt**, **Deliverables**, **Run and test**, **Done when**. All paths are under `backend/` unless stated.

### Phase 0: Project setup

#### T-001 Repository and tooling
- **Depends on:** none. **Attach:** s03, s04 (4.3), s11 (11.6).
- **Prompt:** Create the monorepo layout `backend/`, `frontend/` (empty placeholder), `docs/`, with `AGENTS.md` at the root. Add `.gitignore` (Python, Node, `.env`), `README.md` (how to run), a `Makefile` with targets `install`, `run`, `test`, `lint`, `migrate`, `seed`, and a `docker-compose.yml` with PostgreSQL 16 (named volume, port 5432, credentials from `.env`).
- **Deliverables:** the files above, `.env.example` (variable names only).
- **Run and test:** `docker compose up -d db` then `docker compose ps`.
- **Done when:** database container is healthy; `make` targets exist.

#### T-002 Django project and settings
- **Depends on:** T-001. **Attach:** s03, s04, s11 (11.2).
- **Prompt:** In `backend/` create a Django 5 project `config` with settings split into `base.py`, `dev.py`, `prod.py` (environment variables via django-environ; PostgreSQL; time zone Asia/Kolkata; UTC storage). Install DRF, SimpleJWT, django-filter, drf-spectacular, psycopg 3, openpyxl, pytest, pytest-django, ruff. Add `GET /api/v1/health` returning `{status: "ok"}`. Configure pytest to use the test database and ruff in `pyproject.toml`.
- **Deliverables:** `config/`, `requirements.txt` (pinned), `pytest.ini`, health endpoint and its test.
- **Run and test:** `make migrate && make test && make lint`.
- **Done when:** health test passes; server starts with `make run`.

#### T-003 App skeleton and common helpers
- **Depends on:** T-002. **Attach:** s04 (4.2 to 4.4), s06 (6.4 rounding), `AGENTS.md`.
- **Prompt:** Create the Django apps `core, accounts, catalog, stock, purchasing, parties, billing, commissions, hr, finance, analytics` (empty, registered) and a `common/` package containing: `money.py` (`D()` Decimal constructor from string, `q2()` quantize ROUND_HALF_UP to 0.01, `q4()`, safe sum), `pagination.py` (page and page_size, max 100), `exceptions.py` (error format with `code`, `message`, `fields` and a DRF exception handler), `renderers` so Decimals serialise as strings.
- **Deliverables:** apps, `common/*`, unit tests for money helpers (half-up cases such as 0.005, 2.675, 31.665).
- **Run and test:** `make test`.
- **Done when:** money tests pass; floats are rejected by `D()`.

#### T-004 Continuous integration
- **Depends on:** T-003. **Attach:** s11 (11.5).
- **Prompt:** Add a GitHub Actions workflow running ruff and pytest against a PostgreSQL service on every push and pull request.
- **Deliverables:** `.github/workflows/ci.yml`.
- **Run and test:** push a branch and open the Actions tab.
- **Done when:** CI is green.

**Gate 0:** project runs, CI green, `AGENTS.md` present.

### Phase 1: Backend foundation

#### T-101 Owner login
- **Depends on:** T-003. **Attach:** s08 (8.1), s11 (11.2), s09 (9.1).
- **Prompt:** In `apps/accounts` implement a management command `create_owner` (username, password from prompt). Implement `POST /auth/login` (access token in body, refresh token in an httpOnly secure cookie), `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/change-password`, `GET /auth/me`. Access token life 15 minutes, refresh 7 days. Throttle login; lock for 15 minutes after 5 failed attempts in 15 minutes with a generic error message. Disable any registration endpoint. Default DRF permission is authenticated.
- **Deliverables:** accounts app, tests (success, wrong password, lockout, refresh, unauthenticated access to any endpoint returns 401).
- **Run and test:** `pytest apps/accounts -q`.
- **Done when:** all endpoints behave as specified; health endpoint is the only public one.

#### T-102 App settings and approved GST rates
- **Depends on:** T-101. **Attach:** s07 (7.3 app_settings, gst_rates), s06 (6.5), s08 (8.2).
- **Prompt:** In `apps/core` create the single-row `AppSettings` model with every column listed in 7.3 (including `prices_include_gst`, `purchase_gst_recoverable_default`, `commission_default_percent`, `allow_future_invoice_dates`, `block_prior_fy_backdating`, `salary_basis`, `attendance_weights`, `print_format`) and the `GstRate` model (`rate` unique, `is_active`). Seed settings row and the single rate 0.00. API: `GET/PUT /settings`, `GET/POST/PUT /settings/gst-rates`. Do not seed any other GST rate. Provide `validate_gst_rate(value)` that accepts only active approved rates.
- **Deliverables:** models, migration with seed, serializers, views, tests (cannot create a second settings row, unknown rate rejected, deactivated rate rejected).
- **Run and test:** `pytest apps/core -q -k "settings or gst"`.
- **Done when:** approved list works and `validate_gst_rate` is reusable.

#### T-103 CRITICAL Number series service
- **Depends on:** T-102. **Attach:** s06 (6.11), s07 (number_series), s12 (12.6).
- **Prompt:** In `apps/core` implement `NumberSeries` and `next_number(series_code, document_date)` returning strings of the form `PREFIX/YYMMDD/NNNN`, for example `INV/261105/0042`: the prefix (INV from settings `invoice_prefix`; CN, PUR, RCT, PR fixed), the **document date** as YYMMDD, and a running serial padded to 4 digits. The serial is consecutive per series and **financial year** (start month from settings, April default) and is **not restarted daily**; the financial year comes from the document date. Lock the series row with `select_for_update` inside the caller's transaction. Support a starting number: a new year's row starts at `series_start_number - 1` (applies only to the first number of the current year; it cannot be lowered once a number was issued). Reject any generated number longer than 16 characters. Allowed characters are letters, digits and slash only. Numbers are never reused. A back-dated document gets the next serial and its own date in the number.
- **Deliverables:** model, service, tests: exact format (`INV/261105/0042`), serial continues across days (0042 then 0043 on 6 November), financial-year rollover (31 March to 1 April gives `INV/270401/0001`), back-dated document (date 28 October, next serial), start number 215, length 15 and the 16-character guard, and a concurrency test with 20 parallel transactions producing unique, contiguous serials (use `TransactionTestCase`).
- **Run and test:** `pytest apps/core -q -k number`.
- **Done when:** concurrency test passes repeatedly (run it 3 times).

#### T-104 Audit log
- **Depends on:** T-101. **Attach:** s06 (6.12), s07 (audit_log), s08 (8.2).
- **Prompt:** In `apps/core` implement append-only `AuditLog` (timestamp, action, entity_type, entity_id, summary, before_json, after_json, ip_address, actor) and an `AuditService.record(...)`. The model must refuse updates and deletes. Add `GET /audit-log` with filters (date range, action, entity). Add a helper to capture the request IP and actor.
- **Deliverables:** model, service, API, tests (cannot update or delete, filters work, JSON snapshots stored).
- **Run and test:** `pytest apps/core -q -k audit`.
- **Done when:** audit records can be written from any service and listed.

#### T-105 CRITICAL Idempotency
- **Depends on:** T-101. **Attach:** s08 (8.12), s06 (6.9), `AGENTS.md`.
- **Prompt:** Implement an idempotency mechanism for create endpoints: header `Idempotency-Key` (UUID) is required; a repeated call with the same key and same user returns the stored response without creating anything; same key with a different payload returns 409. Provide a decorator or mixin plus an `IdempotencyRecord` model (key unique, request hash, response status and body). Also document that business tables carry their own unique `idempotency_key` column for a second line of defence.
- **Deliverables:** model, mixin, tests (repeat call returns same body, different payload 409, missing header 400).
- **Run and test:** `pytest apps/core -q -k idempot`.
- **Done when:** a double submit creates exactly one record in the test endpoint.

#### T-106 API conventions and OpenAPI
- **Depends on:** T-003. **Attach:** s04 (4.4), s08 (8.12).
- **Prompt:** Wire pagination, `django-filter`, ordering and search defaults; register the exception handler; expose the OpenAPI schema and Swagger UI with drf-spectacular; define the error codes listed in 8.12 as constants in `common/errors.py`.
- **Deliverables:** configuration, `common/errors.py`, a schema generation test.
- **Run and test:** `pytest -q -k schema` and open `/api/docs`.
- **Done when:** Swagger UI loads with the health, auth, settings endpoints.

**Gate 1:** log in with the owner, change settings, add a GST rate, issue numbers, write audit records, all via Swagger.

### Phase 2: Catalog and products

#### T-201 Companies
- **Depends on:** T-102, T-104. **Attach:** s07 (companies), s15 (15.5), s08 (8.3).
- **Prompt:** In `apps/catalog` create `Company` (name unique case-insensitive, phone, address, gstin, notes, is_local, is_active) with CRUD API, deactivate/activate (no delete) and audit entries. Validate GSTIN format when given.
- **Deliverables:** model, serializer, view, tests (duplicate name differing only by case rejected, deactivate keeps history).
- **Run and test:** `pytest apps/catalog -q -k company`.
- **Done when:** companies can be created, edited, deactivated.

#### T-202 CRITICAL Product model and validation
- **Depends on:** T-201. **Attach:** s06 (6.1, 6.5), s07 (products), s15 (15.3).
- **Prompt:** Create `Product` exactly as in 7.3. Required: product_code (unique, case-insensitive, stored uppercase), company, product_type, pack_size (> 0), pack_unit (LTR, ML, KG, G, PCS, SET, MTR). Optional: category, sub_type, sub_sub_type, selling_price, gst_rate, hsn_code, min_stock. `gst_rate`, when set, must pass `validate_gst_rate`. Normalise type, sub type and sub-sub type (trim, collapse spaces, case-insensitive duplicates map to the existing spelling). Add property/annotation `billing_ready` (selling price, GST rate and HSN present). Stock fields (`qty_on_hand`, `avg_buying_price`) are read-only here.
- **Deliverables:** model, migration, validators, tests (required fields, optional fields, case-insensitive code, not billing ready until price/GST/HSN set, unapproved GST rate rejected).
- **Run and test:** `pytest apps/catalog -q -k product`.
- **Done when:** a product with only the five required fields saves and shows `billing_ready = false`.

#### T-203 Products API
- **Depends on:** T-202. **Attach:** s08 (8.3), s09 (9.7), s06 (6.17).
- **Prompt:** Implement products list/create/detail/update/deactivate/activate. List filters: company, category, product_type, sub_type, stock status, active, billing_ready; search by product code first (trigram indexes on code, type, sub type). Add `GET /products/lookup?code=` (fast billing lookup returning code, name parts, pack, stock, selling price, GST, billing_ready) and `GET /products/suggest?field=&q=` for autocomplete. Updates cannot change stock fields.
- **Deliverables:** views, filters, migration for trigram extension and indexes, tests including query-count test for list and lookup.
- **Run and test:** `pytest apps/catalog -q`.
- **Done when:** partial code search is fast and filters work.

#### T-204 Catalog and readiness endpoints
- **Depends on:** T-203. **Attach:** s08 (8.3), s09 (9.7).
- **Prompt:** Add `GET /catalog/companies` (companies with product counts) and a filter/report endpoint listing products that are **not billing ready**, with the missing fields.
- **Deliverables:** views and tests.
- **Run and test:** `pytest apps/catalog -q -k catalog`.
- **Done when:** both endpoints return correct counts on sample data.

**Gate 2:** create companies and products through Swagger; product code search works; unapproved GST rate is rejected.

### Phase 3: Stock engine

#### T-301 CRITICAL Stock movements and StockService skeleton
- **Depends on:** T-202, T-104. **Attach:** s06 (6.3), s07 (stock_movements), s04 (4.2).
- **Prompt:** In `apps/stock` create the append-only `StockMovement` model and `StockService.apply_movement(...)` which locks product rows with `select_for_update` in a fixed order (by id), updates `qty_on_hand` and `avg_buying_price`, writes the movement with `qty_after` and `avg_cost_after`, and blocks negative stock unless `allow_negative_stock` is on. Movement types: OPENING, PURCHASE, SALE, SALE_RETURN, PURCHASE_RETURN, ADJ_IN, ADJ_OUT, CANCEL_REVERSAL. No other code may change product stock fields.
- **Deliverables:** model, service, tests (negative stock blocked, movements immutable, product stock fields consistent with the last movement).
- **Run and test:** `pytest apps/stock -q`.
- **Done when:** stock can only change through the service.

#### T-302 CRITICAL Weighted average functions (pure)
- **Depends on:** T-301. **Attach:** s06 (6.3), s12 (12.1).
- **Prompt:** Implement pure functions in `apps/stock/costing.py` with Decimal: `after_purchase(old_qty, old_avg, in_qty, line_inventory_cost)`, `after_sale(...)` (average unchanged), `after_return(...)` (at the original cost snapshot), `after_adjustment_in/out(...)`, and `after_purchase_return(old_qty, old_avg, ret_qty, ret_cost)` isolated in one function because the rule is provisional (13.14). Connect `StockService` to them. Average has 4 decimals.
- **Deliverables:** functions, tests reproducing 12.1 exactly: 10 at 300 + 10 at 400 gives 350; sell 15 then buy 10 at 420 gives 396.6667; GST recoverable gives 350 versus non-recoverable 413.
- **Run and test:** `pytest apps/stock -q -k costing`.
- **Done when:** all 12.1 figures match.

#### T-303 Opening stock, adjustments and movement history
- **Depends on:** T-302. **Attach:** s06 (6.3), s08 (8.3), s09 (9.7).
- **Prompt:** Add `StockService.opening_stock(product, qty, buying_price)` (buying price required when qty > 0; allowed only when the product has no movements) and `POST /stock/adjustments` (in/out, qty, reason: damage, leakage, opened pack, found, correction; date) plus `GET /stock/movements` with filters (product, type, date). Audit every call.
- **Deliverables:** service, endpoints, tests.
- **Run and test:** `pytest apps/stock -q`.
- **Done when:** adjustments update stock and appear in history.

#### T-304 CRITICAL Concurrency test for the last unit
- **Depends on:** T-301. **Attach:** s06 (6.3), s11 (11.4).
- **Prompt:** Write a `TransactionTestCase` where two simultaneous threads try to take the last unit of a product through `StockService`; exactly one must succeed and one must fail with `INSUFFICIENT_STOCK`, and stock must end at 0, never negative.
- **Deliverables:** the test (run it 5 times in a loop in CI as a repeat mark).
- **Run and test:** `pytest apps/stock -q -k concurrent`.
- **Done when:** the test is stable.

**Gate 3:** stock engine proven by tests and the 12.1 figures.

### Phase 4: Purchasing and company dues

#### T-401 CRITICAL Purchase GST calculation (pure)
- **Depends on:** T-302, T-102. **Attach:** s06 (6.10, 6.3), s12 (12.1).
- **Prompt:** Implement `apps/purchasing/calc.py`: for each purchase line compute taxable value, GST amount, CGST/SGST (same state) or IGST (different state), recoverable and non-recoverable GST from `itc_eligible`, `inventory_cost_total = taxable + non_recoverable`, `inventory_cost_per_unit`, `line_total` including GST. Use half-up rounding to 2 decimals per line and the CGST/SGST rule `cgst = round(gst/2)`, `sgst = gst - cgst`. Rates must be approved rates.
- **Deliverables:** pure functions and tests for recoverable and non-recoverable examples (illustrative 18%), mixed rates and IGST.
- **Run and test:** `pytest apps/purchasing -q -k calc`.
- **Done when:** inventory costs 300/400 (recoverable) and 354/472 (non-recoverable) are reproduced.

#### T-402 Purchases create API
- **Depends on:** T-401, T-103, T-105, T-201. **Attach:** s06 (6.10), s07 (purchases, purchase_items), s08 (8.4).
- **Prompt:** Implement `Purchase` and `PurchaseItem` models per 7.3, `PurchaseService.create_purchase` (atomic, idempotent via `Idempotency-Key`, number from `next_number('PUR')`, products must be billing-ready for GST only, stock in through `StockService` at each line's inventory cost per unit, store `avg_before` and `avg_after`, update company dues, audit) and `GET/POST /purchases`, `GET /purchases/{id}`.
- **Deliverables:** models, service, API, tests (average updated, tax stored separately, duplicate submit creates one purchase, rollback on failure).
- **Run and test:** `pytest apps/purchasing -q`.
- **Done when:** a purchase updates stock, average, dues and the audit log in one transaction.

#### T-403 Company payments and dues
- **Depends on:** T-402. **Attach:** s15 (15.5), s07 (company_payments), s08 (8.3).
- **Prompt:** Add `CompanyPayment`, `POST /companies/{id}/payments` splitting the amount across the oldest unpaid purchases, updating `paid_amount` and `payment_status`. A payment cannot exceed the company's outstanding dues (assumption: same rule as customers; flag any conflict). Idempotent.
- **Deliverables:** model, service, API, tests.
- **Run and test:** `pytest apps/purchasing -q -k payment`.
- **Done when:** dues and statuses are right after partial and full payments.

#### T-404 Purchase returns (provisional valuation)
- **Depends on:** T-402. **Attach:** s06 (6.3, 6.9), s13 (13.14), s07 (purchase_returns).
- **Prompt:** Implement purchase returns using the **provisional** valuation function from T-302 (value at the returned purchase line's inventory cost; recalculate average). Reverse GST in proportion (recoverable and non-recoverable), reduce company dues, number from `PR`. Keep the valuation in one replaceable function and add a code comment pointing to open item 13.14.
- **Deliverables:** models, service, API, tests.
- **Run and test:** `pytest apps/purchasing -q -k return`.
- **Done when:** returns reduce stock, average and dues consistently.

#### T-405 Company ledger API
- **Depends on:** T-403, T-404. **Attach:** s15 (15.5), s08 (8.3).
- **Prompt:** Implement `GET /companies/{id}/ledger` returning stock value (units and value at average cost), purchases, payments, returns, dues. (Company-wise sales and profit are added in T-1102.)
- **Deliverables:** selector, API, tests.
- **Run and test:** `pytest apps/purchasing -q -k ledger`.
- **Done when:** ledger totals reconcile with purchases minus payments minus returns.

**Gate 4:** enter a purchase, pay the company, return goods, check dues and stock value.

### Phase 5: Excel import (Milestone M1)

#### T-501 Import framework
- **Depends on:** T-104. **Attach:** s15 (15.8), s07 (import_jobs), s08 (8.10), s06 (6.16).
- **Prompt:** In `apps/core` create `ImportJob` and a generic import pipeline: upload `.xlsx`, read the `Products` sheet with openpyxl, validate the header row against the template columns, return row-wise errors and an error report download. Reject merged cells, formulas in data rows and files over 5,000 rows.
- **Deliverables:** model, parser, error report builder, tests using `product-import-template.xlsx` from `docs/templates/` and deliberately broken files.
- **Run and test:** `pytest apps/core -q -k import`.
- **Done when:** a wrong header or broken file gives clear errors.

#### T-502 Product import validation and preview
- **Depends on:** T-501, T-202, T-102. **Attach:** s15 (15.8), s06 (6.1, 6.5).
- **Prompt:** Implement `POST /import/products/validate`: required columns (product_code, company, product_type, pack_size, pack_unit), buying price required when opening_qty > 0, unit in list, approved GST rate, unique codes within file and database, duplicate-variant warning, selling below buying warning, spelling-variant warning, count of rows not billing-ready, preview of new and updated products and new companies. Nothing is saved.
- **Deliverables:** validator, preview endpoint, tests for each of the 10 checks.
- **Run and test:** `pytest apps/core -q -k "import and validate"`.
- **Done when:** every check has a passing and a failing test.

#### T-503 CRITICAL Product import commit
- **Depends on:** T-502, T-303. **Attach:** s15 (15.8), s06 (6.3).
- **Prompt:** Implement `POST /import/products/commit` (in one transaction): create new companies and products, create opening stock movements through `StockService.opening_stock`, update master data of existing codes (never overwrite stock quantity; ignore blank cells unless `clear_blank=true`), record the import and audit entries. Idempotent per validated job.
- **Deliverables:** commit service, tests (re-running the same job does nothing, existing product stock untouched, rollback on one bad row).
- **Run and test:** `pytest apps/core -q -k "import and commit"`.
- **Done when:** the template with sample rows imports fully and stock values are correct.

#### T-504 Template download and Excel export
- **Depends on:** T-503. **Attach:** s08 (8.10), s15 (15.8).
- **Prompt:** Add `GET /import/products/template` (serves the template) and `GET /products/export?format=xlsx` honouring list filters. Build a reusable `ExcelExporter` in `common/` for later reports.
- **Deliverables:** endpoints, exporter, tests.
- **Run and test:** `pytest -q -k export`.
- **Done when:** exported file reopens cleanly and re-imports without errors.

**Gate 5 (M1):** your own Excel file imports through Swagger with a preview, and opening stock appears in stock movements.

### Phase 6: Customers and brokers

#### T-601 Customers
- **Depends on:** T-102, T-104. **Attach:** s07 (customers), s06 (6.5, 6.8), s08 (8.5).
- **Prompt:** In `apps/parties` create `Customer` (name, phone, alt_phone, address, city, state, state_code, gstin optional, opening_balance default 0, notes, is_active). Validate phone (10 digits) and GSTIN format plus state-code match (warning on mismatch). CRUD API with search by name or phone, deactivate (customers with invoices cannot be deleted).
- **Deliverables:** model, API, tests.
- **Run and test:** `pytest apps/parties -q -k customer`.
- **Done when:** customers can be created, searched and deactivated.

#### T-602 Brokers
- **Depends on:** T-102, T-104. **Attach:** s07 (brokers), s06 (6.7), s08 (8.5).
- **Prompt:** Create `Broker` (name, phone, address, default_commission_percent 0 to 100 with settings default, joined_on, notes, is_active). CRUD API, deactivate/activate (no delete); inactive brokers cannot be selected on new invoices (enforced later in billing).
- **Deliverables:** model, API, tests.
- **Run and test:** `pytest apps/parties -q -k broker`.
- **Done when:** brokers work with deactivation.

#### T-603 Customer outstanding selector
- **Depends on:** T-601. **Attach:** s06 (6.8).
- **Prompt:** Add a selector `customer_outstanding(customer)` = opening balance + sum of invoice balances (invoices arrive in phase 8; build it now against the `Invoice` interface with a stub returning 0) and `GET /customers/{id}` returning outstanding.
- **Deliverables:** selector, API field, tests with stubbed invoices.
- **Run and test:** `pytest apps/parties -q`.
- **Done when:** opening balance appears as outstanding.

**Gate 6:** master data (companies, products, customers, brokers) complete.

### Phase 7: Billing calculation (pure functions)

#### T-701 CRITICAL Invoice calculation engine
- **Depends on:** T-003. **Attach:** s06 (6.4), s12 (12.2).
- **Prompt:** In `apps/billing/calc.py` implement pure functions (no database) `calculate_invoice(lines, discount, prices_include_gst, is_interstate)`. Per line: gross, line discount, invoice discount allocation in proportion to net value with the **last line taking the remainder**, GST per line at that line's rate (inclusive and exclusive modes), `cgst = round(gst/2)`, `sgst = gst - cgst`, or IGST. Totals, `round_off` to the nearest rupee, `grand_total`. Half-up rounding at line level. Return dataclasses.
- **Deliverables:** module, tests: the exact figures of 12.2 (taxable 5,453.11; GST 816.89; CGST 408.45; SGST 408.44; grand total 6,270.00), mixed rates, IGST, exclusive mode, and property tests (allocations add to the discount; taxable + GST equals line value; cgst + sgst equals gst).
- **Run and test:** `pytest apps/billing -q -k calc`.
- **Done when:** all figures in 12.2 match exactly.

#### T-702 CRITICAL Profit and commission functions
- **Depends on:** T-701. **Attach:** s06 (6.4, 6.7, 6.9, 6.13), s12 (12.2 to 12.4).
- **Prompt:** Implement pure functions: `line_profit` (taxable minus quantity x cost snapshot; `None` when cost unknown), `invoice_profit` (gross profit over known-cost lines, `profit_complete`, `unknown_cost_taxable_value`), `commission_amount(grand_total, percent)` = half-up of grand_total x percent / 100, `commission_reversal(percent, credit_note_total, remaining)` capped at the remaining commission, `credit_note_amounts(line, returned_qty, already_returned_qty)` using the remainder rule when the line is fully returned.
- **Deliverables:** functions and tests: commission 10,000 at 10% = 1,000; 12.2 gives commission 627.00 and profit after commission 326.11; 12.3 manual line profit 65.08 or unknown; 12.4 return figures (837.29, 150.71, 98.80, 815.82, 287.62).
- **Run and test:** `pytest apps/billing -q -k "profit or commission"`.
- **Done when:** every number in 12.2 to 12.4 matches.

#### T-703 Place of supply and GSTIN helpers
- **Depends on:** T-601. **Attach:** s06 (6.5).
- **Prompt:** Implement `is_interstate(shop_state_code, place_of_supply_code)`, `place_of_supply(customer, settings)`, and GSTIN format and state-code helpers. No state or rate is hard-coded beyond the standard state-code list file in `common/`.
- **Deliverables:** helpers and tests.
- **Run and test:** `pytest apps/billing -q -k supply`.
- **Done when:** same-state gives CGST+SGST, different state gives IGST.

**Gate 7:** all worked examples 12.2, 12.3 and 12.4 reproduced by pure-function tests.

### Phase 8: Invoices, payments, returns (Milestone M2)

#### T-801 Invoice, commission and item models
- **Depends on:** T-701, T-601, T-602, T-202. **Attach:** s07 (invoices, invoice_items, commissions, commission_adjustments), s07 (7.4).
- **Prompt:** Create `Invoice`, `InvoiceItem`, `Commission`, `CommissionAdjustment` exactly per 7.3, including constraints (`product_id IS NOT NULL OR is_manual`, `paid_amount <= grand_total`, unique `invoice_no` and `idempotency_key`) and indexes. No business logic yet.
- **Deliverables:** models, migration, constraint tests.
- **Run and test:** `pytest apps/billing -q -k model`.
- **Done when:** constraints reject invalid rows.

#### T-802 CRITICAL Create invoice service
- **Depends on:** T-801, T-703, T-702, T-301, T-103, T-105, T-104. **Attach:** s06 (6.4 to 6.7, 6.11, 6.18, 15.6), s08 (8.6, 8.6.1, 8.12), s12 (12.2, 12.3, 12.7).
- **Prompt:** Implement `InvoiceService.create_invoice` in one `transaction.atomic()`: validate date (future blocked by setting; previous financial year blocked by default; flag `is_backdated`), broker active, product billing-ready, GST rates approved, stock available (manual lines exempt), then lock products, number via `next_number('INV')`, call `calculate_invoice`, save lines with **all snapshots**, stock out via `StockService` with cost snapshot = current average, manual lines with optional internal cost (no stock effect), create the `Commission` from the saved grand total and the applied percent (default from broker, optional override if allowed), initial payment (not above grand total), profit fields, audit entry. Ignore any client totals. Idempotent. Endpoint `POST /invoices`.
- **Deliverables:** service, endpoint, tests: 12.2 end to end, 12.3 manual line with and without cost, 12.7 dates, insufficient stock, duplicate submit, client totals ignored, rollback leaves nothing behind.
- **Run and test:** `pytest apps/billing -q -k create`.
- **Done when:** the saved invoice equals the worked example to the paisa.

#### T-803 Invoice read APIs and print payload
- **Depends on:** T-802. **Attach:** s08 (8.6, 8.11), s09 (9.4), s06 (6.12).
- **Prompt:** Implement `GET /invoices` (filters: date range, customer, broker, status, shade code, number, payment status), `GET /invoices/{id}` (owner view), `GET /invoices/{id}/print` using a **dedicated serializer** with no commission, broker percent, cost or profit, and `GET /invoices/day-summary?date=`. Totals in words for the print payload.
- **Deliverables:** views, serializers, tests including a **leak test** that scans the print response for forbidden fields.
- **Run and test:** `pytest apps/billing -q -k "list or print or summary"`.
- **Done when:** the leak test passes.

#### T-804 CRITICAL Receipts, payments and overpayment block
- **Depends on:** T-802. **Attach:** s06 (6.8), s07 (receipts, payments), s08 (8.5, 8.6, 8.12), s12 (12.5).
- **Prompt:** Implement `Receipt` and `Payment` (allocation) models and services: `POST /invoices/{id}/payments`, `POST /customers/{id}/receive-payment` (splits across oldest unpaid invoices, one allocation row per invoice), refunds with a cap at the amount received. Lock invoices while allocating; reject amounts above the outstanding due with `PAYMENT_EXCEEDS_DUE`. Update `paid_amount`, `balance_due`, `payment_status`. Idempotent receipts. Wire `customer_outstanding` from T-603 to real invoices.
- **Deliverables:** models, services, endpoints, tests: 12.5 split, overpayment rejected for invoice and receipt, refund cap, duplicate submit.
- **Run and test:** `pytest apps/billing -q -k "payment or receipt"`.
- **Done when:** statuses and balances are always consistent.

#### T-805 CRITICAL Invoice cancellation
- **Depends on:** T-802, T-804. **Attach:** s06 (6.9, 6.7), s08 (8.6).
- **Prompt:** Implement `POST /invoices/{id}/cancel` (reason mandatory): restore stock at the cost snapshot, reverse the whole remaining commission through a `commission_adjustments` row (source CANCELLATION), mark payments refunded, set status CANCELLED, keep the number (never reused), audit. A cancelled invoice cannot be cancelled again.
- **Deliverables:** service, endpoint, tests (stock restored, commission REVERSED, number retained, second cancel rejected).
- **Run and test:** `pytest apps/billing -q -k cancel`.
- **Done when:** reports exclude the cancelled invoice correctly.

#### T-806 CRITICAL Sales returns and credit notes
- **Depends on:** T-802, T-804. **Attach:** s06 (6.9, 6.7, 6.13), s07 (sales_returns), s12 (12.4).
- **Prompt:** Implement `POST /invoices/{id}/returns`: quantity cannot exceed sold minus already returned; amounts from the invoice line snapshot with the remainder rule; credit note number from `CN`; stock back at cost snapshot; COGS reversal; commission reversal from the credit note total (capped, `commission_adjustments` row); refund or reduced balance (refund not above amount received); manual lines reverse revenue and GST only (COGS only if cost was entered). Idempotent.
- **Deliverables:** service, endpoint, tests: 12.4 figures, two partial returns that together equal a full return (remainder rule), return after payout (negative broker balance), over-return rejected.
- **Run and test:** `pytest apps/billing -q -k return`.
- **Done when:** 12.4 matches exactly and cumulative returns never exceed the invoice.

**Gate 8 (M2):** run the complete flow in Swagger: purchase, invoice with two GST rates, partial payment, return, cancellation; all balances reconcile.

### Phase 9: Commissions and brokers (Milestone M3)

#### T-901 CRITICAL Broker payouts
- **Depends on:** T-806. **Attach:** s06 (6.7), s07 (broker_payouts), s08 (8.5).
- **Prompt:** Implement `BrokerPayout` and `BrokerPayoutItem`, `POST /brokers/{id}/payouts` allocating to the oldest pending commissions (using `adjusted_amount`), updating `paid_amount` and status (PENDING, PARTIAL, PAID); payout cannot exceed the broker's pending commission (`PAYOUT_EXCEEDS_PENDING`); idempotent; audit.
- **Deliverables:** models, service, endpoint, tests (partial and full payout, over-payout rejected, status transitions, reversal after payout shows negative balance).
- **Run and test:** `pytest apps/commissions -q -k payout`.
- **Done when:** commission statuses match the blueprint life cycle.

#### T-902 Broker ledger and performance
- **Depends on:** T-901. **Attach:** s08 (8.5, 8.7), s09 (9.5).
- **Prompt:** Implement `GET /brokers/{id}/ledger` (customer, final invoice total, applied percent, commission, reversals, paid, status) and `GET /brokers/performance?period=` (week, month, quarter, year, custom) returning invoices count, total sales, gross profit generated, commission earned, paid, pending, average bill value, ranked.
- **Deliverables:** selectors, endpoints, tests with fixtures.
- **Run and test:** `pytest apps/commissions -q -k "ledger or performance"`.
- **Done when:** ranking matches hand-calculated sample data.

#### T-903 Commission expense helper
- **Depends on:** T-902. **Attach:** s06 (6.7, 6.13).
- **Prompt:** Implement `commission_expense(period)` on an **accrual basis**: accrued commissions by invoice date minus reversals by adjustment date; payouts excluded. Used later by reports.
- **Deliverables:** selector and tests proving payouts and reversals are never double-counted.
- **Run and test:** `pytest apps/commissions -q -k expense`.
- **Done when:** the three figures (expense, paid, pending) reconcile.

**Gate 9 (M3):** broker commission life cycle works including payouts and reversals.

### Phase 10: Employees and expenses

#### T-1001 Employees and attendance
- **Depends on:** T-104, T-102. **Attach:** s06 (6.14), s07 (employees, attendance), s08 (8.9).
- **Prompt:** Implement `Employee` (deactivate, never delete) and `Attendance` (statuses P, A, HD, PL, UL, H; unique per employee and date) with `PUT /attendance/bulk` for a day and `GET /attendance/summary?month=`. Day-weights come from settings `attendance_weights`.
- **Deliverables:** models, API, tests.
- **Run and test:** `pytest apps/hr -q -k "employee or attendance"`.
- **Done when:** a day's attendance can be saved in one call.

#### T-1002 Expenses
- **Depends on:** T-104. **Attach:** s06 (6.15), s07 (expenses, expense_categories, recurring_expenses), s08 (8.9).
- **Prompt:** Implement categories (seed Rent, Power, Salaries, Miscellaneous), expenses CRUD (salary-sourced expenses read-only), recurring templates with `GET /recurring-expenses/due` and `POST .../generate`.
- **Deliverables:** models, API, tests.
- **Run and test:** `pytest apps/finance -q`.
- **Done when:** monthly totals by category are correct.

#### T-1003 Salary calculation and payment
- **Depends on:** T-1001, T-1002. **Attach:** s06 (6.14), s12 (12.8), s07 (salaries).
- **Prompt:** Implement salary generation by month: calendar days basis by default (configurable), paid days from weights, bonus, advance, other deductions with notes; `POST /salaries/{id}/pay` creates exactly one Salaries expense linked by `expense_id` (idempotent).
- **Deliverables:** service, API, tests: 12.8 gives 18,666.67 and net 17,666.67; paying twice creates one expense.
- **Run and test:** `pytest apps/hr -q -k salary`.
- **Done when:** 12.8 matches.

**Gate 10:** employees, salaries and expenses work; salary paid appears once in expenses.

### Phase 11: Analytics and reports

#### T-1101 Dashboard endpoint
- **Depends on:** T-903, T-1002, T-303. **Attach:** s09 (9.3), s08 (8.8), s06 (6.13).
- **Prompt:** Implement one aggregated `GET /dashboard`: total products, invoices (month and today), stock value, out-of-stock count (active tracked products at zero, first 10 codes), customers, sold versus remaining stock by value, top 10 brokers by sales, expense versus profit for the last 6 months (profit = profit after commission), optional strip (today's sales, profit, dues, pending commission). Cache for 60 seconds.
- **Deliverables:** selectors, endpoint, tests against fixtures with known answers, query-count test.
- **Run and test:** `pytest apps/analytics -q -k dashboard`.
- **Done when:** numbers match the fixture exactly.

#### T-1102 Sales analysis and period reports
- **Depends on:** T-1101. **Attach:** s09 (9.9, 9.12), s08 (8.7, 8.8), s15 (15.5).
- **Prompt:** Implement sales analysis (by day, product, company, product type; margin; average discount; fast and slow movers; month versus same month last year; company-wise sales and profit added to the company ledger) and period reports for week, month, quarter (financial-year quarters) and year, including "unknown cost revenue (profit incomplete)".
- **Deliverables:** endpoints and reconciliation tests (report totals equal the sum of invoices).
- **Run and test:** `pytest apps/analytics -q -k "sales or period"`.
- **Done when:** totals reconcile with invoices and credit notes.

#### T-1103 CRITICAL Profit and loss report
- **Depends on:** T-1102, T-903. **Attach:** s06 (6.13), s08 (8.8), s12.
- **Prompt:** Implement `GET /reports/profit-loss` with gross profit (revenue excluding GST minus COGS, after returns), commission expense (accrual), profit after commission, operating expenses, net profit, and the incomplete-profit revenue shown separately. Use only stored snapshots.
- **Deliverables:** endpoint, tests: figures follow 12.2 and 12.4 after the return; changing a product's price or GST afterwards changes nothing.
- **Run and test:** `pytest apps/analytics -q -k profit`.
- **Done when:** the three profit metrics agree with the hand calculation.

#### T-1104 GST summary, dues ageing, stock valuation, item min/max
- **Depends on:** T-1102, T-402. **Attach:** s06 (6.5, 6.8), s09 (9.12), s08 (8.8).
- **Prompt:** Implement GST summary (output GST by rate; input GST split into recoverable and non-recoverable; credit notes netted), dues ageing (0-30, 31-60, 61-90, 90+), stock valuation (by company and product type), item min/max sold and non-moving stock.
- **Deliverables:** endpoints and tests.
- **Run and test:** `pytest apps/analytics -q -k "gst or ageing or valuation or minmax"`.
- **Done when:** the GST summary matches 12.2 by rate.

#### T-1105 Stock take and month-end snapshot
- **Depends on:** T-303. **Attach:** s15 (15.5), s07 (stock_takes, stock_snapshots).
- **Prompt:** Implement `StockTake` and items (`GET/POST /stock/takes`, post adjustments for differences through `StockService`) and monthly `StockSnapshot` creation (command and endpoint) plus a "stock sheet" Excel export for any month (sections, units, quantity, average cost, value, grand total).
- **Deliverables:** models, services, endpoints, tests.
- **Run and test:** `pytest apps/stock -q -k "take or snapshot"`.
- **Done when:** a count creates the right adjustments and the export matches stock value.

#### T-1106 Excel export for every list and report
- **Depends on:** T-504, T-1102. **Attach:** s08 (8.8), s06 (6.16).
- **Prompt:** Add `format=xlsx` to every list and report endpoint using the shared exporter, honouring filters; print-friendly headers; Indian number formats.
- **Deliverables:** exports and a generic test that every list endpoint exports.
- **Run and test:** `pytest -q -k export`.
- **Done when:** each export opens cleanly.

#### T-1107 Notifications, global search and day summary
- **Depends on:** T-1101. **Attach:** s05 (5.5), s08 (8.2).
- **Prompt:** Implement `GET /notifications` (low and out of stock, overdue dues, pending commission, due recurring expenses, backup status) and `GET /search?q=` (products by code and name, customers, brokers, invoices by number or shade code; top 5 each; trigram search).
- **Deliverables:** endpoints and tests.
- **Run and test:** `pytest apps/analytics -q -k "notif or search"`.
- **Done when:** results are grouped and fast.

**Gate 11:** every report reconciles with invoices, returns, purchases and expenses.

### Phase 12: Backend hardening

#### T-1201 OpenAPI completeness
- **Depends on:** all backend tasks. **Attach:** s08, s04 (4.4).
- **Prompt:** Make sure every endpoint has request and response schemas, error codes and examples in the OpenAPI document. Add a test that fails if an endpoint has no schema.
- **Deliverables:** annotations, schema test, exported `openapi.json`.
- **Run and test:** `pytest -q -k schema`.
- **Done when:** the schema covers all of section 8.

#### T-1202 Security checklist
- **Depends on:** T-1201. **Attach:** s11 (11.2).
- **Prompt:** Verify and test: default deny permissions, login throttling and lockout, CORS limited to the frontend origin, secure cookies, security headers, no stack traces in production, secrets only from environment, print endpoint leak test, client totals ignored.
- **Deliverables:** tests and a short `docs/security-check.md`.
- **Run and test:** `pytest -q -k security`.
- **Done when:** the checklist is green.

#### T-1203 Backups
- **Depends on:** T-1202. **Attach:** s06 (6.16), s11 (11.3).
- **Prompt:** Implement a management command that runs `pg_dump`, encrypts the file, stores it (local folder now, S3-compatible later behind a storage interface), writes `backup_log` and raises a notification on failure; document a restore procedure and a restore test script using a scratch database.
- **Deliverables:** command, storage interface, docs, test with a fake storage.
- **Run and test:** `pytest -q -k backup` and a manual restore into a scratch database.
- **Done when:** a restore reproduces the data.

#### T-1204 Performance
- **Depends on:** T-1201. **Attach:** s11 (11.1), s07 (7.4).
- **Prompt:** Add a seed command that generates fake data (50 companies, 600 products, 2,000 customers, 50,000 invoices) and query-count tests on dashboard, invoice list and product search; add missing indexes.
- **Deliverables:** seed command, benchmarks, index migration.
- **Run and test:** `make seed` then the performance tests.
- **Done when:** typical API calls stay under 300 ms on the seeded data.

#### T-1205 Demo data command
- **Depends on:** T-1204. **Attach:** s11.
- **Prompt:** Create `seed_demo` producing a small, realistic fake dataset (a few products with different GST rates, two companies, brokers, customers, purchases and invoices) for frontend development and demos. Fake names only.
- **Deliverables:** command and README note.
- **Run and test:** `make seed`.
- **Done when:** the dashboard has believable numbers.

#### T-1206 Backend acceptance and freeze
- **Depends on:** T-1205. **Attach:** s12, s13.
- **Prompt:** Add an acceptance test module that executes every worked example 12.1 to 12.8 through the public API and asserts the printed figures. Report coverage. Tag the release `backend-v1`.
- **Deliverables:** acceptance tests, coverage report.
- **Run and test:** `pytest -q` (full suite).
- **Done when:** the full suite is green and the API contract is frozen.

**Gate 12 (backend complete):** no frontend work starts before this gate passes.

### Phase 13: Design pass (before frontend code)

#### T-1301 Design tokens and mockups (you, with Figma AI or Claude Design)
- **Depends on:** Gate 12 (so screens reflect the real API). **Attach:** the reference dashboard image, s05, s09, `docs/diagrams` wireframes.
- **Prompt (for the design tool):** "Design a lightweight web and mobile (responsive) admin application for a paint and hardware shop. Use the attached reference dashboard image for style: dark teal-blue left menu (about 15% width) with light active pill, light blue page background, soft rounded white cards, muted blue, green and orange chart colours, rounded humanist font. Create these screens: Login; Dashboard (4 overview cards including Out of Stock with info icon, Total Customers, sold-versus-remaining pie, Top 10 Brokers bars, Expense vs Profit area chart, optional today strip); Create Invoice (customer and broker pickers, item grid with product code, shade, quantity, GST-inclusive price, discount, GST %, manual line row, totals panel with CGST/SGST, payment, owner-only commission panel marked 'not printed'); Inventory Items list and Add Product form; Broker detail with commission ledger and payout; A4 invoice print layout. No animations. Export PNG for each screen and a design-tokens JSON (colours, radii, spacing, font sizes)."
- **Deliverables:** `docs/design/*.png`, `docs/design/tokens.json`.
- **Run and test:** you review each screen against s09; adjust until approved.
- **Done when:** six screens and tokens are approved. (Design only; the AI builds from these in phase 14 and 15.)

### Phase 14: Frontend foundation

#### T-1401 Frontend scaffold
- **Depends on:** T-1301, T-1206. **Attach:** s03 (3.1), s05 (5.6), s11 (11.6).
- **Prompt:** In `frontend/` create a React 18 + Vite + TypeScript app with Tailwind CSS using `docs/design/tokens.json`, React Router, TanStack Query, React Hook Form + Zod, dayjs, lucide-react, vitest and ESLint. No animation libraries. Route-level code splitting; charts lazy loaded (Recharts only where used).
- **Deliverables:** scaffold, scripts `dev`, `build`, `test`, `lint`.
- **Run and test:** `npm run build && npm test`.
- **Done when:** the build is under about 200 KB gzipped for the empty shell.

#### T-1402 API client and authentication
- **Depends on:** T-1401. **Attach:** s08 (8.1), s11 (11.2), `openapi.json`.
- **Prompt:** Generate a typed client from `openapi.json`; implement login, access token kept in memory, silent refresh through the cookie on 401, logout, idle auto-logout from settings, an Idempotency-Key generator for create calls, and an error mapper from the standard error format to form field errors.
- **Deliverables:** `src/lib/api`, auth provider, tests.
- **Run and test:** `npm test`.
- **Done when:** login and refresh work against the running backend.

#### T-1403 Application shell
- **Depends on:** T-1402. **Attach:** s05 (5.1 to 5.5), s09 (9.2), design PNGs.
- **Prompt:** Build the layout: left menu about 15% with all menus in 5.4, header with shop logo and name, calendar date jump (opens Past Billings for the date), global search box, Create Invoice icon, previous-day sales popover, notification bell, theme toggle placeholder, profile name menu. Responsive: icon-only on tablet, drawer on phone.
- **Deliverables:** shell components and tests.
- **Run and test:** `npm test && npm run build`.
- **Done when:** the shell matches the approved design at three widths.

#### T-1404 Shared components
- **Depends on:** T-1401. **Attach:** s09 (9.14), s05 (5.6).
- **Prompt:** Build DataTable (server pagination, sorting, filter bar), SearchSelect (async, debounced), MoneyInput (Indian formatting, 2 decimals, string value), DateRangePicker, StatusChip, ConfirmDialog, ExportButton, StatCard, Toast, EmptyState, Skeleton, PrintLayout. Money is handled as strings or integers of paise; never float arithmetic for totals.
- **Deliverables:** components with tests and a small example page.
- **Run and test:** `npm test`.
- **Done when:** each component has a passing test.

#### T-1405 Login page and route guards
- **Depends on:** T-1402, T-1403. **Attach:** s09 (9.1).
- **Prompt:** Build the login page exactly as 9.1 (username, password, show/hide, Enter submits, generic error, lockout message) and guards that redirect unauthenticated users.
- **Deliverables:** page, guards, tests.
- **Run and test:** `npm test`.
- **Done when:** the owner can log in and reach an empty dashboard.

**Gate 14:** login and shell work with the real backend.

### Phase 15: Frontend modules

For each module: build the page against the real API, add component tests, run the app with `seed_demo` data, compare with the design PNGs.

#### T-1501 Settings pages
- **Depends on:** T-1405. **Attach:** s09 (9.13), s08 (8.2).
- **Prompt:** Build Settings: shop profile, **GST rates** list, tax and billing, dates, commission, stock, numbering (including the starting number), employees (salary basis, attendance weights), printing (A4), data (import, export, backups), audit log viewer, security.
- **Deliverables:** pages and tests.
- **Run and test:** `npm test`.
- **Done when:** every setting round-trips with the API.

#### T-1502 Inventory: companies, products, catalog
- **Depends on:** T-1501. **Attach:** s09 (9.7), s15 (15.3).
- **Prompt:** Build Inventory Items (filters, code search, badges for not billing-ready and out of stock), the Add/Edit Product form (required fields only the five; optional fields grouped; no stock edit), Product Catalog (company dropdown), Companies list and detail with ledger.
- **Deliverables:** pages and tests.
- **Run and test:** `npm test`.
- **Done when:** products can be added and found quickly.

#### T-1503 Excel import wizard
- **Depends on:** T-1502. **Attach:** s15 (15.8), s06 (6.16).
- **Prompt:** Build the wizard: download template, upload, validation results with row errors and error report download, preview (new, updated, warnings, not billing-ready count), confirm, summary.
- **Deliverables:** wizard and tests.
- **Run and test:** `npm test`.
- **Done when:** the real template imports through the UI.

#### T-1504 Purchases, stock update, stock take
- **Depends on:** T-1502. **Attach:** s09 (9.7, 9.8), s06 (6.10).
- **Prompt:** Build Purchase Items (list and form with unit price excluding GST, GST rate, ITC flag, GST split display, company dues), Stock Update (adjustments), Stock Take, company payments.
- **Deliverables:** pages and tests.
- **Run and test:** `npm test`.
- **Done when:** a purchase shows the new average inventory cost.

#### T-1505 Customers and brokers
- **Depends on:** T-1404. **Attach:** s09 (9.5, 9.6).
- **Prompt:** Build customer list and detail (bills, dues, shades used, receive payment with overpayment error), broker profiles (add, edit, deactivate) and broker detail (ledger, payout).
- **Deliverables:** pages and tests.
- **Run and test:** `npm test`.
- **Done when:** dues and payouts display and update correctly.

#### T-1506 CRITICAL Create Invoice screen
- **Depends on:** T-1502, T-1505. **Attach:** s09 (9.4), s06 (6.4, 6.7), s12 (12.2, 12.3), design PNG.
- **Prompt:** Build the Create Invoice screen exactly as 9.4: customer and broker pickers, keyboard-friendly item grid with product-code search, shade fields, GST-inclusive editable price, line discount, per-line GST, one manual line row (description, quantity, unit, price, GST rate from approved list, optional cost), invoice discount, live preview of totals using a **shared test vector file** (`tests/vectors/invoice_cases.json`, exported from the backend tests) so the preview equals the server, payment with overpayment guard, owner-only commission panel (rate override only), date rules, Save, Save and Print, Save and New with idempotency key.
- **Deliverables:** screen, preview calculation module, tests that run every vector and compare to the backend figures.
- **Run and test:** `npm test` and a manual run creating the 12.2 invoice.
- **Done when:** the UI preview equals the saved invoice for every vector.

#### T-1507 Invoice lists, view and A4 print
- **Depends on:** T-1506. **Attach:** s09 (9.4), s08 (8.11).
- **Prompt:** Build All, Today and Past Billings (with day summary strip), invoice view (owner panel hidden by default), and the **A4 print layout** using the print endpoint only (no commission, cost or profit). Thermal printing is not part of Version 1.
- **Deliverables:** pages, print stylesheet, tests (print page contains no forbidden fields).
- **Run and test:** `npm test`.
- **Done when:** the A4 print matches the design.

#### T-1508 Payments, returns and cancellation flows
- **Depends on:** T-1507. **Attach:** s09 (9.4, 9.8), s06 (6.8, 6.9).
- **Prompt:** Build add-payment dialog (blocked above due), return flow with effect preview (revenue and GST reversed, commission reduction, refund or reduced balance), cancel flow with mandatory reason.
- **Deliverables:** dialogs and tests.
- **Run and test:** `npm test`.
- **Done when:** the effects shown match the backend responses.

#### T-1509 Broker performance pages
- **Depends on:** T-1505. **Attach:** s09 (9.5, 9.9).
- **Prompt:** Build Broker Sales Performance (ranking, chart, period selector) and Sales > Broker Commissions (earned, paid, pending, percentage of sales).
- **Deliverables:** pages and tests.
- **Run and test:** `npm test`.
- **Done when:** figures match the API.

#### T-1510 Dashboard
- **Depends on:** T-1404. **Attach:** s09 (9.3), s05 (5.1, 5.2), design PNG.
- **Prompt:** Build the dashboard exactly as the approved design: four overview cards (Out of Stock with info tooltip), customers card, pie, top 10 brokers bars, expense versus profit area chart, optional strip. Lazy-load charts.
- **Deliverables:** page and tests.
- **Run and test:** `npm test && npm run build`.
- **Done when:** it matches the design with `seed_demo` data.

#### T-1511 Sales analysis and reports
- **Depends on:** T-1404. **Attach:** s09 (9.9, 9.12).
- **Prompt:** Build Sales Analysis and Reports (period reports, item min/max, profit and loss with the three profit metrics and "profit incomplete", GST summary, dues ageing, stock valuation, stock sheet) with Excel export buttons.
- **Deliverables:** pages and tests.
- **Run and test:** `npm test`.
- **Done when:** every report loads and exports.

#### T-1512 Employees and expenses
- **Depends on:** T-1404. **Attach:** s09 (9.10, 9.11).
- **Prompt:** Build employee profiles, attendance (day screen and monthly grid), salary screen (adjustments, mark paid), expenses with category totals and recurring prompts.
- **Deliverables:** pages and tests.
- **Run and test:** `npm test`.
- **Done when:** salary paid appears once in expenses.

#### T-1513 Header features
- **Depends on:** T-1507, T-1510. **Attach:** s05 (5.5).
- **Prompt:** Finish the header: calendar jump to a day's invoices with summary, global search results dropdown (grouped), previous-day popover, notification bell list.
- **Deliverables:** components and tests.
- **Run and test:** `npm test`.
- **Done when:** each header control works end to end.

#### T-1514 PWA, mobile polish, dark theme
- **Depends on:** T-1513. **Attach:** s05 (5.3, 5.6).
- **Prompt:** Add the PWA manifest and service worker (app shell caching), refine phone layouts (tables become card lists), implement the light/dark toggle through CSS variables, check the bundle size.
- **Deliverables:** PWA files, theme, build report.
- **Run and test:** `npm run build` and a Lighthouse run.
- **Done when:** the app installs on a phone and stays within the size target.

**Gate 15:** every screen works against the real backend.

### Phase 16: Integration and go-live

#### T-1601 End-to-end tests
- **Depends on:** Gate 15. **Attach:** s11 (11.4).
- **Prompt:** Using Playwright write end-to-end tests: login, import products, purchase, create an invoice with two GST rates, print (no commission), part payment, return, broker payout, dashboard numbers.
- **Deliverables:** tests and CI job.
- **Run and test:** `npx playwright test`.
- **Done when:** the suite is green in CI.

#### T-1602 Deployment
- **Depends on:** T-1601. **Attach:** s03 (3.3), s11 (11.5).
- **Prompt:** Prepare production configuration: backend container with Gunicorn behind Nginx and HTTPS, managed PostgreSQL, frontend on Vercel with the API URL variable, environment variables, migrations on deploy, health checks, error tracking, uptime monitor.
- **Deliverables:** deployment files and a runbook (`docs/deploy.md`).
- **Run and test:** deploy to staging and run the smoke test.
- **Done when:** staging works end to end.

#### T-1603 Real data import and reconciliation (you)
- **Depends on:** T-1602. **Attach:** s15 (15.8), s11 (11.7), s13.
- **Prompt:** Not an AI task. Prepare your Excel from the template with verified GST rates and HSN codes (add the approved rates in Settings first), import to staging, review the preview, count physical stock, post differences through Stock Take, enter opening customer dues, set the invoice starting number if continuing paper numbers, then repeat on production.
- **Deliverables:** loaded production data.
- **Run and test:** stock value, customer dues and broker pending commission match your books.
- **Done when:** reconciliation signed off.

#### T-1604 UAT, training and go-live
- **Depends on:** T-1603. **Attach:** s11 (11.7, 11.8).
- **Prompt:** Run the UAT checklist (billing, returns, payouts, reports, backup export), train the owner, take a backup and run a restore drill, switch over.
- **Deliverables:** signed checklist.
- **Run and test:** one full day of parallel billing if desired.
- **Done when:** the shop bills on the system.

---

## 8. Extra suggestions

1. **Golden test vectors:** keep one JSON file of invoice, return and commission cases (from section 12). The backend tests and the frontend preview tests both read it, so the two can never drift apart.
2. **Two-model review for CRITICAL tasks** and one human check of the numbers against section 12.
3. **Phase branches and tags:** `git tag gate-3`, `gate-8`, `backend-v1`. If a later task breaks something, you can return to a known good point.
4. **Never run the AI against your real database.** Use the Docker development database and fake data.
5. **Cost control:** buy the $10 credit once; check the free-model limit with the key information request; avoid very long chats (they use more requests and context).
6. **Keep the blueprint current:** if you approve a change, edit the blueprint first, regenerate the split files, then run the task.
7. **Accountant checkpoints:** before T-1603, have your accountant review the GST rates and HSN list, the input-credit setting (13.13), the purchase-return rule (13.14) and the place-of-supply defaults (13.17).
8. **Order flexibility:** phases 10 (employees, expenses) and 11 (reports) can swap with phase 9 if the owner wants reports earlier, but nothing in phases 13 to 15 should start before Gate 12.
9. **If a free model is unavailable or rate-limited:** the free list rotates; switch to another `:free` model in Kilo for that task, or wait. Always re-run the tests after switching.
