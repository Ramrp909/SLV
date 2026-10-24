## 11. Non-Functional Requirements

### 11.1 Performance targets
- Initial JavaScript under about 200 KB gzipped; route-level code splitting; charts loaded only where used.
- Typical API response under 300 ms (95th percentile); invoice save under 1 second; dashboard under about 1 second (cached 60 s).
- Product code search results in under 300 ms with partial matching.
- Lists limited to 25 rows per page by default.
- Works well on low-end phones and slow connections (PWA caching of the app shell).

### 11.2 Security
- Single owner account; strong password policy; password hashed (Django default PBKDF2/Argon2).
- Short-lived access token (15 minutes) kept in memory; refresh token (7 days) in an httpOnly, Secure, SameSite cookie; CSRF protection on the refresh endpoint.
- Login throttling and temporary lockout; idle auto-logout.
- HTTPS only, restricted CORS to the frontend origin, security headers.
- Database in a private network, least-privilege credentials, secrets in environment variables.
- Input validation on every endpoint; ORM prevents SQL injection; output encoded to prevent XSS.
- Print endpoint never contains commission, cost or profit.
- Backups encrypted; audit log records login and export events.
- Optional later: two-factor authentication (TOTP) for the owner.

### 11.3 Reliability and backups
- Daily automated backups, retention 7 daily / 4 weekly / 12 monthly; point-in-time recovery on the managed database.
- Monthly restore drill; written restore procedure.
- Health-check endpoint and uptime monitoring; error tracking with Sentry; structured server logs.
- Database migrations are versioned and run during deployment, with a rollback plan.

### 11.4 Testing strategy
**Unit tests (highest priority: money, tax and stock logic, written as pure functions where possible)**
- Weighted average: opening, purchase, sale, return, adjustments, your 300/400 example, recoverable versus non-recoverable GST (average 350 versus 413, see 12.1), and the provisional purchase-return rule (kept behind one function so it can change once approved).
- Invoice calculation: GST-inclusive (default) and exclusive modes, **mixed GST rates on one invoice**, discount allocation with last-line remainder, CGST/SGST rounding, IGST, round-off, and the exact figures in 12.2.
- GST snapshots: change a product's GST rate and HSN after issue; the invoice, credit notes and reports must not change.
- Commission: 10,000 x 10% = 1,000 on the saved grand total; invoice-specific override; snapshot unchanged when the broker default changes; proportional reversal on partial returns with the remainder rule; full reversal on cancellation; negative broker balance after reversal; commission counted once as an expense (payouts and reversals never double-counted).
- Profit: gross profit excludes GST; profit after commission; net profit after expenses; manual line without cost marked **profit incomplete** (never zero); manual line with cost; returns reduce revenue, COGS and commission.
- Numbering: sequence, financial year from invoice date, configurable starting number, cancelled numbers never reused, concurrent requests.
- Dates: back-dated invoice allowed and flagged; future date blocked; prior-financial-year back-dating blocked by default.
- Payments: overpayment blocked for an invoice and for a customer receipt, refund cap, oldest-first allocation, repeated request with the same idempotency key.
- Returns: quantity cap, remainder rule, stock restored at the cost snapshot, COGS reversal.
- Purchases: recoverable and non-recoverable GST stored separately, supplier dues, company payments.
- Salary: calendar-day example in 12.8, leave weights, bonus and deductions.
- Import: approved GST rate check, only the five required columns enforced, billing-readiness warnings.

**Integration/API tests:** invoice create/cancel/return flows, receipt splitting, import validation, authentication (unauthenticated access rejected), print payload excludes commission, cost and profit, client-supplied totals ignored.

**Concurrency tests:** two simultaneous invoices for the last tin (one must fail); duplicate submit with the same idempotency key creates one invoice, one receipt, one return.

**End-to-end tests (Playwright):** login, add item, purchase, create invoice with two GST rates, print, add payment, return, broker payout, dashboard numbers.

**Data checks before go-live:** reconcile stock value, customer dues and broker pending commission with your manual books.

### 11.5 Deployment
- Environments: development, staging (optional), production.
- CI (GitHub Actions): lint, tests, build on every push; deploy on merge to main.
- Frontend: Vercel (environment variable for API URL). Backend: container or systemd service with Gunicorn and Nginx on AWS Lightsail/EC2 (or Render/Railway). Database: managed PostgreSQL.
- Domain name and HTTPS certificate; separate API subdomain.
- Estimated starting infrastructure: one small server plus one small managed database.

### 11.6 Suggested project structure

**Frontend**
```
src/
  app/            (router, providers, layout shell)
  components/     (DataTable, SearchSelect, MoneyInput, charts, ...)
  features/
    auth/ dashboard/ invoices/ brokers/ customers/
    inventory/ orders/ sales/ reports/ employees/
    expenses/ settings/
  lib/            (api client, formatters, GST preview math, constants)
  styles/         (design tokens, theme variables)
  main.tsx
```

**Backend**
```
backend/
  config/         (settings, urls, wsgi)
  apps/
    core/ accounts/ catalog/ stock/ purchasing/ parties/
    billing/ commissions/ hr/ finance/ analytics/
  common/         (money utils, pagination, exceptions, audit helpers)
  tests/
  manage.py
```

### 11.7 Data migration and go-live checklist
1. Prepare Excel files: products with opening quantity and cost, customers (with opening dues), brokers, employees.
2. Import into staging, review, then production.
3. Count physical stock and compare with the app; post adjustments for differences.
4. Run parallel billing for a few days if desired (paper plus app), then switch fully.
5. Confirm the invoice number series starts correctly: `INV/26-27/0001`, or the next paper number entered as the series starting number (13.19) before the first invoice.
6. Verify backups ran and a restore works.
7. Train the owner (billing, returns, payouts, reports, backup export).

### 11.8 After go-live
- Weekly review of error tracking and backup logs in the first month.
- Monthly restore drill and dependency updates.
- Feature backlog: dark theme polish, WhatsApp invoice sharing, thermal printing, two-factor authentication, barcode scanner support, supplier payment tracking, e-invoice integration if required later.
