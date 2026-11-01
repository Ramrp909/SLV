## 8. Backend API Design

All endpoints require the owner's JWT except login/refresh. Base path `/api/v1/`.

### 8.1 Auth
| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` | Username + password; returns access token, sets refresh cookie; throttled |
| POST | `/auth/refresh` | New access token |
| POST | `/auth/logout` | Clears refresh cookie |
| POST | `/auth/change-password` | Owner changes password |
| GET | `/auth/me` | Profile name for header |

### 8.2 Settings and system
| Method | Path | Purpose |
|---|---|---|
| GET/PUT | `/settings` | Shop profile, GST, numbering (including series start number), back-dating and payment rules |
| GET/POST/PUT | `/settings/gst-rates` | Approved GST rates (list, add, activate/deactivate) |
| POST | `/settings/logo` | Upload logo |
| GET | `/audit-log` | Filterable audit log |
| GET | `/notifications` | Computed alerts for the bell |
| GET | `/search?q=` | Global search, grouped results |
| GET | `/backups` | Backup status list |
| POST | `/backups/export` | Full data export (ZIP of CSV/Excel) |

### 8.3 Catalog and inventory
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/companies` | List, create |
| GET/PUT | `/companies/{id}` | Detail, update |
| POST | `/companies/{id}/deactivate` | Deactivate |
| GET | `/companies/{id}/ledger` | Purchases, payments, dues, stock value, sales and profit by company |
| POST | `/companies/{id}/payments` | Record payment to a company (split across oldest unpaid purchases) |
| GET/POST | `/stock/takes` | Physical count: create, list, post adjustments |
| GET | `/stock/snapshots?month=` | Month-end stock snapshot and stock-sheet export |
| GET/POST | `/products` | List (filters: company, type, sub_type, status, active, search by code), create (with optional opening stock) |
| GET/PUT | `/products/{id}` | Detail, update (stock fields not editable here) |
| POST | `/products/{id}/deactivate` / `activate` | Toggle |
| GET | `/products/lookup?code=` | Fast lookup for billing (code, name, pack, stock, default price, GST) |
| GET | `/products/suggest?field=type&q=` | Autocomplete for type/sub type |
| GET | `/catalog/companies` | Companies with product counts (catalog dropdown) |
| GET | `/stock/movements` | Movement history (filter by product, type, date) |
| POST | `/stock/adjustments` | Damage/loss/found stock with reason |
| GET | `/stock/valuation` | Stock value by company/type |

### 8.4 Purchasing
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/purchases` | List, create (stores taxable value, GST, recoverable and non-recoverable GST per line; updates stock and average inventory cost). Requires `Idempotency-Key` |
| GET | `/purchases/{id}` | Detail |
| POST | `/purchase-returns` | Return stock to company |
| GET | `/purchase-returns` | List |

### 8.5 Parties
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/customers` | List (with outstanding), create |
| GET/PUT | `/customers/{id}` | Detail with invoice history, shades used |
| POST | `/customers/{id}/receive-payment` | Creates a receipt and splits the amount across the oldest unpaid invoices; rejected with `PAYMENT_EXCEEDS_DUE` if it exceeds the customer's outstanding. Requires `Idempotency-Key` |
| GET | `/customers/{id}/statement` | Ledger of invoices and payments |
| GET/POST | `/brokers` | List, create |
| GET/PUT | `/brokers/{id}` | Detail, update |
| POST | `/brokers/{id}/deactivate` / `activate` | Toggle |
| GET | `/brokers/{id}/ledger` | Customers, bill totals, commissions, payouts |
| POST | `/brokers/{id}/payouts` | Record commission payout |
| GET | `/brokers/performance?period=` | Ranking by sales, profit, commission |

### 8.6 Billing
| Method | Path | Purpose |
|---|---|---|
| POST | `/invoices/preview` | Returns computed totals without saving (optional; frontend can compute locally) |
| POST | `/invoices` | Create invoice (atomic); requires `idempotency_key` |
| GET | `/invoices` | List with filters (date, customer, broker, status, number, shade) |
| GET | `/invoices/{id}` | Detail (owner view including commission and profit) |
| GET | `/invoices/{id}/print` | Print data **without** commission/profit fields |
| POST | `/invoices/{id}/cancel` | Cancel with reason |
| POST | `/invoices/{id}/payments` | Add payment |
| POST | `/invoices/{id}/returns` | Sales return / credit note |
| GET | `/invoices/day-summary?date=` | Counts, sales, collected, profit for one day (calendar and previous-day icon) |

**8.6.1 Create invoice: request and response (illustrative)**

Request (client sends inputs only; header `Idempotency-Key: <uuid>`):

```json
{
  "invoice_date": "2026-11-05",
  "customer_id": 41,
  "broker_id": 7,
  "commission_percent": "10.00",
  "discount": { "type": "PERCENT", "value": "5.00" },
  "items": [
    { "product_id": 312, "quantity": "10", "selling_price": "520.00", "shade_code": "N1-204" },
    { "product_id": 540, "quantity": "2",  "selling_price": "700.00" },
    { "is_manual": true, "description": "Thinner from opened drum", "unit_text": "LTR",
      "quantity": "3", "selling_price": "120.00", "gst_rate": "18.00", "internal_cost": "80.00" }
  ],
  "payment": { "amount": "5000.00", "mode": "UPI", "reference": "UPI-TXN-88" }
}
```

The request must **not** contain totals, GST amounts, commission base or commission amount; if present they are ignored and logged as a validation warning.

Response (saved values calculated by the backend; the print endpoint returns the same document without the owner-only fields):

```json
{
  "id": 1288, "invoice_no": "INV/261105/0042", "status": "ACTIVE",
  "subtotal": "...", "discount_amount": "...", "taxable_total": "...",
  "cgst_total": "...", "sgst_total": "...", "igst_total": "0.00",
  "round_off": "...", "grand_total": "...",
  "paid_amount": "5000.00", "balance_due": "...", "payment_status": "PARTIAL",
  "owner_only": {
    "commission_percent": "10.00", "commission_base_amount": "<= grand_total",
    "commission_amount": "<= round(grand_total x 10 / 100)",
    "gross_profit": "...", "profit_after_commission": "...", "profit_complete": true
  },
  "items": [ { "gst_rate": "18.00", "hsn_code": "...", "taxable_value": "...", "cgst": "...", "sgst": "...", "line_total": "..." } ]
}
```

### 8.7 Commissions and sales
| Method | Path | Purpose |
|---|---|---|
| GET | `/commissions` | Filter by broker, status, period |
| GET | `/sales/analysis` | Sales by day/product/company/type, margins, slow/fast movers |
| GET | `/sales/broker-commissions` | Commission given and sales brought, by broker |

### 8.8 Dashboard and reports
| Method | Path | Purpose |
|---|---|---|
| GET | `/dashboard` | One aggregated call: cards, pie, top 10 brokers, 6-month expense vs profit (cached about 60 s) |
| GET | `/reports/sales?granularity=week|month|quarter|year&from=&to=` | Sales, profit, commission |
| GET | `/reports/item-minmax?period=` | Most and least sold items, non-moving stock |
| GET | `/reports/profit-loss` | Gross profit, profit after commission, net profit (commission expense on accrual basis) |
| GET | `/reports/gst-summary` | Output and input GST by rate |
| GET | `/reports/dues-ageing` | Customer dues by age |
| GET | `/reports/stock-valuation` | Stock value |
| GET | `/reports/expenses` | By category and month |
| GET | `*/export?format=xlsx` | Excel export on any list or report |

### 8.9 HR and expenses
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/employees`, `/employees/{id}` | CRUD, with deactivate/activate |
| GET/PUT | `/attendance?date=` / `/attendance/bulk` | Mark attendance for a day in one call |
| GET | `/attendance/summary?month=` | Monthly summary per employee |
| GET/POST | `/salaries` | Generate and list salaries |
| POST | `/salaries/{id}/pay` | Mark paid (creates expense) |
| GET/POST | `/expenses`, `/expenses/{id}` | CRUD |
| GET/POST | `/expense-categories` | Manage categories |
| GET/POST | `/recurring-expenses` | Manage recurring items |
| GET | `/recurring-expenses/due` | Items due now |
| POST | `/recurring-expenses/{id}/generate` | Create the expense entry |

### 8.10 Import/export
| Method | Path | Purpose |
|---|---|---|
| GET | `/import/{entity}/template` | Download Excel template |
| POST | `/import/{entity}/validate` | Upload, validate, return preview and errors |
| POST | `/import/{entity}/commit` | Commit a validated import |

`entity` values: `products`, `customers`, `brokers`, `employees`, `opening-stock`.

### 8.11 Security of the invoice print endpoint
The print/PDF payload is built from a dedicated serializer that **does not contain** commission, broker percentage, cost price or profit. This guarantees that the commission can never leak onto a customer copy.

### 8.12 Idempotency and error codes
- Every create call for an invoice, purchase, purchase return, receipt, credit note and broker payout requires an `Idempotency-Key` header (a client-generated UUID). A repeated call with the same key returns the original result and creates nothing new.
- Business errors use the standard error format (4.4). Main codes: `INSUFFICIENT_STOCK`, `PRODUCT_NOT_BILLING_READY`, `GST_RATE_NOT_APPROVED`, `FUTURE_DATE_NOT_ALLOWED`, `PRIOR_FY_BACKDATE_BLOCKED`, `PAYMENT_EXCEEDS_DUE`, `REFUND_EXCEEDS_RECEIVED`, `RETURN_QTY_EXCEEDS_SOLD`, `PAYOUT_EXCEEDS_PENDING`, `INVOICE_ALREADY_CANCELLED`, `DUPLICATE_PRODUCT_CODE`, `VALIDATION_ERROR`.
