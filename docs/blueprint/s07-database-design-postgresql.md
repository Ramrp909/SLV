## 7. Database Design (PostgreSQL)

### 7.1 Conventions
- Primary keys: `BIGINT` identity. Every table has `created_at`, `updated_at` (timestamps, UTC).
- Money: `DECIMAL(12,2)`. Average cost: `DECIMAL(14,4)`. Quantities: `DECIMAL(10,3)` (in packs; whole numbers normally, fractions only if the product allows).
- Enumerations are stored as short text with `CHECK` constraints.
- Records with history use `is_active` (deactivate), never hard delete.
- Immutable tables: `stock_movements`, `audit_log`, `payments` (corrections are new rows).

### 7.2 Entity relationship overview

```
companies 1---* products 1---* stock_movements
companies 1---* purchases 1---* purchase_items *---1 products
companies 1---* company_payments
customers 1---* invoices 1---* invoice_items *---0..1 products (empty for manual lines)
customers 1---* receipts 1---* payments *---1 invoices          (payments = allocations)
brokers   1---* invoices
invoices  1---1 commissions *---1 brokers
commissions 1---* commission_adjustments                         (reversals from returns/cancellations)
brokers   1---* broker_payouts 1---* broker_payout_items *---1 commissions
invoices  1---* sales_returns 1---* sales_return_items *---1 invoice_items
employees 1---* attendance
employees 1---* salaries ---> expenses
expense_categories 1---* expenses
gst_rates (approved list), number_series, app_settings, audit_log, import_jobs, backup_log (supporting)
```

### 7.3 Tables

**users** (Django auth; exactly one active superuser)
`id, username (unique), password_hash, last_login, is_active`

**app_settings** (single row)
`shop_name, logo_url, address, phone, email, gstin null, state null, state_code null, invoice_prefix, series_start_number (integer, default 1, minimum 1; used only to continue paper invoice numbers), invoice_footer, terms_text, prices_include_gst (default true), default_manual_line_gst_rate null, purchase_gst_recoverable_default (default true, to be confirmed with accountant), commission_default_percent (default 10), commission_override_allowed (default true), allow_negative_stock (default false), allow_future_invoice_dates (default false), block_prior_fy_backdating (default true), financial_year_start_month (default 4), salary_basis (default 'CALENDAR_DAYS'), attendance_weights (json), overdue_days (default 30), discount_warn_percent, idle_logout_minutes, print_format (default 'A4'), theme`

The old `commission_base` setting is removed: commission base is always the invoice `grand_total`.

**gst_rates** (approved GST rates, maintained by the owner or accountant)
`id, rate (decimal(5,2), unique), label, is_active`. Only active rates can be used on products, purchase lines, manual lines and imports. No product rates are assumed.

**companies** (paint companies / suppliers / local group)
`id, name (unique), phone, address, gstin, notes, is_local, is_active`

**company_payments** (append-only)
`id, company_id, purchase_id null, amount, payment_date, mode, reference, note`

**products**

| Column | Type | Notes |
|---|---|---|
| id | bigint PK | |
| product_code | text | **Required, unique**, case-insensitive, indexed |
| company_id | FK companies | **Required** |
| category | text null | optional report group |
| product_type | text | **Required**; e.g. Walmasta, Bison, Blade; indexed |
| sub_type | text null | base code or main variant; indexed |
| sub_sub_type | text null | |
| description | text null | |
| pack_size | decimal(10,3) | **Required**, > 0 |
| pack_unit | text | **Required**: LTR, ML, KG, G, PCS, SET, MTR (extendable list) |
| allow_fractional_qty | boolean | default false |
| qty_on_hand | decimal(10,3) | maintained only by the stock engine |
| avg_buying_price | decimal(14,4) null | **average inventory cost per unit**: excludes recoverable GST, includes non-recoverable GST; required when opening qty > 0 |
| last_buying_price | decimal(14,4) null | information only |
| selling_price | decimal(12,2) null | default per unit, **GST-inclusive** by default; needed before billing |
| gst_rate | decimal(5,2) null | must exist in `gst_rates`; needed before billing |
| hsn_code | text null | needed before billing |
| min_stock | decimal(10,3) null | |
| track_stock | boolean | default true |
| custom_fields | jsonb | extra fields added later |
| is_active | boolean | |

Derived in queries/API: `billing_ready` (selling price, GST rate and HSN present), stock value, litres (LTR/ML products only).

**stock_movements** (append-only)
`id, product_id, movement_type ('OPENING','PURCHASE','SALE','SALE_RETURN','PURCHASE_RETURN','ADJ_IN','ADJ_OUT','CANCEL_REVERSAL'), quantity (signed), unit_cost, qty_after, avg_cost_after, reference_type, reference_id, reason, movement_date`

**purchases**
`id, purchase_no (unique), idempotency_key (unique), company_id, supplier_invoice_no, supplier_state, purchase_date, taxable_total, cgst_total, sgst_total, igst_total, gst_total, recoverable_gst_total, non_recoverable_gst_total, grand_total, paid_amount, payment_status ('UNPAID','PARTIAL','PAID'), notes`

**purchase_items**
`id, purchase_id, product_id, quantity, unit_price (excluding GST), taxable_value, gst_rate, hsn_code, cgst, sgst, igst, gst_amount, itc_eligible, recoverable_gst, non_recoverable_gst, inventory_cost_total (= taxable_value + non_recoverable_gst), inventory_cost_per_unit, line_total (including GST), avg_before, avg_after`

**purchase_returns / purchase_return_items**
`id, return_no (unique), idempotency_key (unique), purchase_id null, company_id, return_date, reason, taxable_total, gst_total, recoverable_gst_reversed, non_recoverable_gst_reversed, total` and `id, return_id, product_id, purchase_item_id null, quantity, unit_price, taxable_value, gst_amount, valuation_cost_per_unit (provisional rule 6.3), line_total`

**customers**
`id, name, phone (indexed), alt_phone, address, city, state, state_code, gstin null, opening_balance (default 0), notes, is_active`

**brokers**
`id, name, phone, address, default_commission_percent, joined_on, notes, is_active`

**invoices**

| Column | Type | Notes |
|---|---|---|
| id | bigint PK | |
| invoice_no | text unique | `INV/261105/0042` (prefix / date YYMMDD / serial) |
| idempotency_key | text unique | prevents duplicates |
| invoice_date | date | indexed; future dates blocked by default |
| is_backdated | boolean | invoice_date earlier than the creation date (audit-flagged) |
| customer_id | FK | |
| broker_id | FK null | |
| status | text | ACTIVE, CANCELLED |
| prices_include_gst | boolean | snapshot of setting (default true) |
| place_of_supply_state | text | |
| is_interstate | boolean | |
| subtotal | decimal | sum of gross lines |
| discount_type / discount_value / discount_amount | | PERCENT or AMOUNT |
| taxable_total, cgst_total, sgst_total, igst_total | decimal | |
| round_off, grand_total | decimal | `grand_total` = final invoice amount including GST after discounts |
| paid_amount, balance_due | decimal | `paid_amount <= grand_total` |
| payment_status | text | UNPAID, PARTIAL, PAID, CANCELLED |
| commission_percent | decimal null | applied-rate snapshot (**owner-only**) |
| commission_base_amount | decimal null | snapshot equal to `grand_total` at issue |
| commission_amount | decimal null | `round(grand_total x percent / 100)` at issue; later reversals live in `commission_adjustments` |
| gross_profit | decimal | taxable minus cost snapshots, for lines with known cost |
| profit_after_commission | decimal | gross_profit minus commission_amount |
| profit_complete | boolean | false when a manual line has no internal cost |
| unknown_cost_taxable_value | decimal | taxable value of lines without a known cost |
| notes | text | internal |
| cancel_reason, cancelled_at | | |

**invoice_items**
`id, invoice_id, product_id (null for manual lines), is_manual, description, unit_text, product_code_snapshot, product_name_snapshot, hsn_code, shade_code null, shade_name null, quantity, pack_size_snapshot, pack_unit_snapshot, default_price_snapshot, selling_price (GST-inclusive when prices_include_gst), line_discount, discount_allocation, discounted_value, gst_rate, taxable_value, cgst, sgst, igst, line_total, cost_snapshot (null if not entered), cost_entered, line_profit (null if cost unknown)`. Check: `product_id IS NOT NULL OR is_manual`.

**receipts** (append-only; one per money receipt)
`id, receipt_no (unique), idempotency_key (unique), customer_id, total_amount, receipt_date, mode ('CASH','UPI','CARD','BANK','CHEQUE'), reference, note`

**payments** (append-only; allocation of a receipt to one invoice, or a refund)
`id, receipt_id null, invoice_id, direction ('RECEIVED','REFUNDED'), amount, payment_date, mode, reference, note`. Rule: for RECEIVED, the sum of allocations on an invoice never exceeds its `grand_total` (service check under row lock plus database check on `paid_amount`).

**sales_returns / sales_return_items** (credit notes)
`id, return_no (unique, CN series), idempotency_key (unique), invoice_id, return_date, reason, is_cancellation, taxable_total, cgst_total, sgst_total, igst_total, round_off, total (credit note total), cost_reversed, refund_amount, commission_reversed` and `id, return_id, invoice_item_id, quantity, taxable_value, cgst, sgst, igst, line_total, cost_snapshot`

**commissions**
`id, invoice_id (unique), broker_id, percent (applied snapshot), base_amount (= invoice grand_total), amount, adjusted_amount (amount plus adjustments), paid_amount, status ('PENDING','PARTIAL','PAID','REVERSED')`

**commission_adjustments** (append-only)
`id, commission_id, source_type ('RETURN','CANCELLATION'), source_id, amount (negative), adjustment_date, note`

**broker_payouts / broker_payout_items**
`id, idempotency_key (unique), broker_id, amount, payout_date, mode, reference, note` and `id, payout_id, commission_id, amount`

**employees**
`id, name, phone, address, designation, joining_date, base_salary, notes, is_active`

**attendance**
`id, employee_id, attendance_date, status ('P','A','HD','PL','UL','H'), note` with unique `(employee_id, attendance_date)`

**salaries**
`id, employee_id, month (YYYY-MM), salary_basis_snapshot, base_salary_snapshot, days_in_basis, paid_days, gross_amount, bonus, advance_deducted, other_deductions, adjustment_note, net_payable, status ('PENDING','PAID'), paid_date, payment_mode, expense_id` with unique `(employee_id, month)`

**expense_categories**
`id, name (unique), is_system, is_active`

**expenses**
`id, category_id, amount, expense_date, payment_mode, note, source ('MANUAL','SALARY','RECURRING'), reference_id`

**recurring_expenses**
`id, category_id, amount, day_of_month, note, is_active, last_generated_month`

**number_series**
`id, series_code, financial_year, prefix, last_number (initialised to series_start_number - 1), padding` with unique `(series_code, financial_year)`

**audit_log** (append-only)
`id, timestamp, action, entity_type, entity_id, summary, before_json, after_json, ip_address`

**import_jobs**
`id, entity, filename, status ('VALIDATED','COMMITTED','FAILED'), total_rows, valid_rows, error_rows, errors_json, committed_at`

**backup_log**
`id, backup_type, file_ref, size_bytes, status, message`

### 7.4 Indexes and constraints
- `products(product_code)` unique; trigram indexes on `product_code`, `product_type`, `sub_type`, `customers(name, phone)`, `brokers(name)`; btree on `products(company_id, is_active)`.
- `invoices(invoice_date)`, `invoices(customer_id, payment_status)`, `invoices(broker_id, invoice_date)`, `invoices(invoice_no)` unique, `invoices(idempotency_key)` unique.
- `invoice_items(invoice_id)`, `invoice_items(product_id)`, `invoice_items(shade_code)`.
- `stock_movements(product_id, movement_date)`.
- `payments(invoice_id)`, `payments(receipt_id)`, `receipts(customer_id, receipt_date)`, `commissions(broker_id, status)`, `commission_adjustments(commission_id)`.
- Unique `idempotency_key` on purchases, purchase_returns, receipts, sales_returns and broker_payouts as well.
- `expenses(expense_date, category_id)`.
- `CHECK` constraints: quantities non-negative, selling price and costs non-negative when set, commission percent 0-100, `paid_amount <= grand_total`, valid status values, `product_id IS NOT NULL OR is_manual`, `gst_rate` present in `gst_rates` (enforced by foreign key on rate or service validation).
- Foreign keys use `ON DELETE RESTRICT` (history is never cascaded away).
- Financial documents (invoices, credit notes, receipts, purchases) and ledgers (stock movements, payments, commission adjustments, audit log) are append-only in the application; corrections are new rows.
- Optional later: monthly summary table or materialized view if reports slow down.

### 7.5 Seed data
Default expense categories (Rent, Power, Salaries, Miscellaneous), number series for the current financial year (starting number configurable), one settings row, the approved GST rate list containing only **0** until the owner or accountant adds the rates they use, default attendance weights, and the owner account (created by command, not by public sign-up).
