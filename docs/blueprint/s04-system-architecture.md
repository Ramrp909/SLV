## 4. System Architecture

### 4.1 Overview

```
+---------------------------+        HTTPS / JSON (REST)        +--------------------------------+
|  React PWA (Vercel)       | <-------------------------------> |  Django + DRF API (AWS/Render) |
|  - Pages, forms, charts   |   JWT access token (in memory)    |  - Auth, business rules        |
|  - TanStack Query cache   |   refresh token (httpOnly cookie) |  - Stock engine, GST, commission|
+---------------------------+                                   |  - Excel import/export          |
                                                                |  - Audit logging                |
                                                                +---------------+----------------+
                                                                                |
                                                                   SQL (private network)
                                                                                |
                                                                +---------------v----------------+
                                                                |  PostgreSQL 16 (managed)        |
                                                                |  - Daily backups + PITR          |
                                                                +---------------+----------------+
                                                                                |
                                                                +---------------v----------------+
                                                                |  Object storage (S3)            |
                                                                |  - Backup files, shop logo       |
                                                                +--------------------------------+
```

### 4.2 Principles
1. **All business rules live in the backend** (stock cost, GST, commission, numbering, profit). The frontend only shows previews for convenience; the backend recalculates and is the source of truth.
2. **Transactions:** creating an invoice is one atomic operation (invoice, items, stock movements, payment, commission, audit log, number). It fully succeeds or fully rolls back.
3. **Immutable history:** stock movements, audit logs and issued invoices are never edited. Corrections are made with cancellations, returns or adjustments.
4. **Snapshots:** invoices keep copies of product name, code, prices, GST rate and cost at the time of sale.
5. **Money:** `DECIMAL`, never floating point. Rounding rule: half-up to 2 decimals at line level.
6. **Soft deactivation:** records with history are deactivated, not deleted.
7. **Server-side pagination, filtering and sorting** on every list.
8. **Idempotent saves:** the invoice create call carries a client-generated key so a double click or a retry never creates two invoices.

### 4.3 Backend app structure (Django apps)

| App | Responsibility |
|---|---|
| `core` | Settings, number series, audit log, import/export framework, notifications, backup log |
| `accounts` | Single owner login, password change, throttling |
| `catalog` | Companies, products |
| `stock` | Stock movements, weighted average engine, adjustments |
| `purchasing` | Purchases, purchase returns |
| `parties` | Customers, brokers |
| `billing` | Invoices, items, payments, sales returns, GST calculation |
| `commissions` | Commission records, broker payouts, performance |
| `hr` | Employees, attendance, salaries |
| `finance` | Expenses, recurring expenses |
| `analytics` | Dashboard, sales analysis, reports |

### 4.4 API conventions
- Base path `/api/v1/`, JSON only.
- Pagination: `?page=1&page_size=25` (max 100).
- Search: `?search=`, filters as named query params, ordering: `?ordering=-created_at`.
- Money and quantities returned as **strings** (e.g. `"5313.56"`) to avoid float errors.
- Dates in ISO format (`YYYY-MM-DD`), timestamps in UTC; displayed in IST on the frontend.
- Error format: `{ "code": "INSUFFICIENT_STOCK", "message": "...", "fields": { "items[0].quantity": "Only 3 in stock" } }`.
- Every create/update/cancel call writes to the audit log.
