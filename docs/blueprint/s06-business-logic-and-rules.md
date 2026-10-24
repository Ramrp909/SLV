## 6. Business Logic and Rules

### 6.1 Product structure
A **product** is one sellable item with one size. In this document the older word "pack" means one sellable **unit** (a tin, a bag or a piece). The final field list, with examples, is in **Section 15.3**; the summary is:

| Field | Required | Notes |
|---|---|---|
| Product code | **Yes** | Unique (case-insensitive). Primary key for searching, filtering and billing lookup |
| Company | **Yes** | From the companies list |
| Product type | **Yes** | Product name, e.g. Walmasta, Bison, Blade, Sandpaper |
| Pack size + unit | **Yes** | e.g. 20 LTR, 100 ML, 40 KG, 1 PCS |
| Category | No | Optional report group (Paint, Hardware...) |
| Sub type | No (usually filled) | Base code (PO, P1, N1...) or size/roughness for hardware |
| Sub-sub type | No | Any additional detail |
| Quantity on hand | System | In units; changed only by stock transactions |
| Average buying price (inventory cost) | System | Weighted average inventory cost per unit (see 6.3) |
| Selling price | No at creation; **needed before billing** | GST-inclusive default price per unit |
| GST rate and HSN code | No at creation; **needed before billing** | Per product; GST rate must be one of the approved rates (6.5) |
| Minimum stock level | No | Low stock alert threshold |
| Track stock / Active | Yes (defaults Y) | Deactivate instead of delete |

**Billing readiness:** a product can be created and imported without selling price, GST rate or HSN code (so the master list can be loaded before the owner supplies verified tax data), but it **cannot be added to an invoice or purchase until those fields are set**. The product list shows a "Needs tax/price details" badge for such items. Opening stock quantity above zero requires a buying price.

Derived (always calculated): stock value = quantity x average inventory cost; litres = quantity x pack size for LTR/ML products only.

Type, sub type and sub-sub type are saved with **autocomplete** and compared ignoring capital letters and extra spaces.

### 6.2 The four price terms

| Term | Meaning | Example (one tin) |
|---|---|---|
| Inventory cost (average buying price) | Weighted average cost per unit, excluding recoverable GST and including non-recoverable GST (see 6.3) | 350 |
| Default selling price | Standard **GST-inclusive** price auto-filled on the invoice | 450 |
| Selling price (on invoice line) | Final negotiated **GST-inclusive** price for this customer | 420 |
| Cost snapshot | Copy of the inventory cost saved on the invoice line at the time of sale | 350 |

Profit per line = (taxable selling value, excluding GST) minus (quantity x cost snapshot). The snapshot guarantees that old invoices keep their original profit even when later purchases change the cost.

### 6.3 Weighted average cost (stock costing)

Each product holds `qty_on_hand` (units) and `avg_buying_price`, defined as the **average inventory cost per unit**.

**Inventory cost of a purchase line** = (taxable value + non-recoverable GST) / quantity. Recoverable GST is **not** part of inventory cost; it is stored separately on the purchase (6.10).

| Event | Quantity | Average inventory cost |
|---|---|---|
| Opening stock | + qty | = entered buying price (taken as inventory cost: excluding recoverable GST) |
| Purchase | + qty | `new_avg = (old_qty x old_avg + in_qty x line_inventory_cost) / (old_qty + in_qty)`. If old_qty is 0, new_avg = line_inventory_cost |
| Sale | - qty | Unchanged. The invoice line stores `cost_snapshot = current avg` |
| Sale return / invoice cancellation | + qty | Treated like a purchase at the **original cost snapshot** (average recalculated) |
| Purchase return | - qty | **Provisional rule, needs accountant approval (13.14):** valued at the inventory cost of the purchase line being returned (or the current average if no purchase is referenced); `new_avg = (old_qty x old_avg - ret_qty x ret_cost) / (old_qty - ret_qty)`; when quantity reaches 0 the last average is kept |
| Adjustment in (found stock) | + qty | Valued at the current average (average unchanged) |
| Adjustment out (damage, leakage, loss, opened pack) | - qty | Average unchanged |
| Stock take difference | +/- qty | Same as adjustment in/out |

**Consistency rule:** one costing policy is used everywhere. Stock valuation = quantity x average inventory cost; cost of goods sold (COGS) = quantity sold x cost snapshot (the average at the moment of sale); month-end snapshots, stock take differences and company-wise stock value all use the same average. Returns reverse COGS at the original snapshot.

**Your example (prices excluding GST, GST recoverable):** last month 10 tins at 300, this month 10 tins at 400. `(10 x 300 + 10 x 400) / 20 = 350` per tin. Every tin sold is costed at 350 until the next purchase changes the average. If GST on those purchases were **non-recoverable** at 18%, the inventory costs would be 354 and 472 and the average 413 (see 12.1).

**Other rules**
- Negative stock is **blocked** by default (setting `allow_negative_stock`, default off).
- Stock changes are done while holding a **row lock** on the product (`SELECT ... FOR UPDATE`, rows locked in a fixed order) so two bills can never sell the same last tin.
- Average cost is stored per unit with 4 decimal places to limit rounding drift.
- Every change is written to `stock_movements` with quantity and average after, so stock can be audited and rebuilt.
- Manual invoice lines never touch stock or average cost (15.6).

### 6.4 Invoice calculation (order of operations)

**Who calculates:** the backend only. The client sends inputs (items, quantities, selling prices, discounts, optional commission rate override, payment). It never sends totals, GST amounts, commission base or commission amount; the backend recalculates everything, saves it, and returns the saved values. The screen may show a live preview using the same formulas.

**Price basis:** product selling prices are **GST-inclusive** by default (setting `prices_include_gst`, default on). The exclusive mode is an optional configuration; the formulas for both are below. Rounding policy (unchanged): **half-up to 2 decimals at line level**.

For each line `i` (GST rate `r_i` is the rate stored on the line, which may differ from line to line):
1. `gross_i = quantity_i x selling_price_i`
2. `net_i = gross_i - line_discount_i` (line discount optional)
3. **Invoice discount allocation:** the invoice discount `D` (percent or amount) is allocated across lines in proportion to `net_i`: `allocation_i = round(D x net_i / sum(net))`; the **last line takes the rounding remainder** so allocations add up exactly to `D`. `discounted_i = net_i - allocation_i`. Allocation works on GST-inclusive amounts, so mixed GST rates are handled correctly.
4. GST (per line, at that line's rate):
   - Prices include GST: `taxable_i = round(discounted_i / (1 + r_i/100))`, `gst_i = discounted_i - taxable_i`
   - Prices exclude GST: `taxable_i = discounted_i`, `gst_i = round(taxable_i x r_i/100)`
5. Split GST by place of supply (6.5):
   - Same state: `cgst_i = round(gst_i / 2)`, `sgst_i = gst_i - cgst_i`
   - Different state: `igst_i = gst_i`
6. `grand_total_unrounded = sum(taxable_i + gst_i)`; `round_off = round(grand_total_unrounded) - grand_total_unrounded` (nearest rupee); `grand_total = grand_total_unrounded + round_off`. This **saved `grand_total`** is the "final invoice amount".
7. `balance_due = grand_total - payments received`

**Snapshots saved on every line:** product code and name, HSN code, GST rate, selling price, default price, discount allocation, taxable value, CGST/SGST/IGST amounts, line total and cost snapshot. Later changes to a product's price, GST rate or HSN code never change issued invoices.

**Profit and commission use the saved values:**
- `line_profit_i = taxable_i - quantity_i x cost_snapshot_i` (taxable value excludes GST; GST is never counted as profit)
- Manual lines without an internal cost have **no profit figure** (not zero); the invoice is marked `profit_complete = false` and the revenue of such lines is shown as `unknown_cost_taxable_value`
- `gross_profit = sum(line_profit_i)` over lines whose cost is known
- `commission_amount = round(grand_total x commission_percent / 100)` (6.7)
- `profit_after_commission = gross_profit - commission_amount` (commission is **not** subtracted from the GST-inclusive total; it is an expense against gross profit)

### 6.5 GST rules
- **Product-wise GST:** every product stores its own GST rate and HSN code. There is no single shop-wide rate. One invoice may contain lines with different rates.
- **Approved rates:** GST rates are validated against a configurable list of approved rates (`gst_rates`, Settings > GST rates). The list is maintained by the owner or accountant; no product rates are assumed by the system. A product, purchase line, manual line or Excel row with a rate not on the list is rejected.
- **Verified data is supplied by the owner:** actual product GST rates, HSN codes, shop GSTIN and shop state stay configurable and may be blank until the owner provides verified values. A product without GST rate and HSN is not billing-ready (6.1) and cannot be sold.
- **Place of supply:** defaults to the customer's state; if none, the shop state. Shop state code and customer state code decide CGST+SGST (same state) versus IGST (different state). GSTIN format is validated and, when present, its state code is compared with the selected state (warning on mismatch). The owner or accountant should verify these rules for the shop's situation.
- **Customers:** without GSTIN the sale is B2C; with GSTIN the invoice shows it (B2B).
- **Snapshots and immutability:** each invoice line stores the applied GST rate, HSN code, taxable value, CGST, SGST and IGST. Changing a product's GST rate or HSN later does not modify previously issued invoices, credit notes or reports.
- **Manual lines** carry their own GST rate (chosen from the approved list; an optional default can be set in Settings).
- The invoice shows: taxable value and GST per rate, CGST/SGST or IGST, round-off, grand total, and the amount in words.
- The GST summary report groups output GST by rate and input GST (from purchases, split into recoverable and non-recoverable) for your accountant.

### 6.6 Shade / colour codes
- Each invoice line has optional **shade code** and **shade name** (text), printed on the invoice.
- Stock is **not** tracked per shade (tinting is done on demand from the base product).
- Shade code is searchable (invoice list, global search) so a customer's earlier shade can be found for repeat orders.
- Customer detail shows previously used shades.

### 6.7 Broker commission

**Confirmed formula (Version 1):**

`commission_amount = final_invoice_total_including_gst_after_discounts x commission_rate / 100`

Example: final invoice amount (including GST, after discounts) 10,000 and rate 10% gives commission **1,000**.

- **Base:** the saved, backend-calculated `grand_total` of the invoice (6.4). It is never supplied or edited by the client. The old `commission_base` setting and its two modes are removed.
- **Rate:** the broker's default rate (settings default 10%, allowed range 0-100%) is copied to the invoice and can be overridden per invoice where authorized (single owner in Version 1; a permission `commission.override` is reserved for future roles). The applied rate and the calculated amount are saved as **historical snapshots** on the commission record; later changes to the broker's default never alter old invoices.
- **Accrual:** commission accrues when the invoice is issued (`commissions` row created in the same transaction as the invoice). There is no "release after full payment" rule in Version 1.
- **Visibility:** never shown on the customer invoice or print; visible only on the owner panel of the billing screen and in the broker section.
- **Status:** `PENDING` -> `PARTIAL` -> `PAID`, and `REVERSED` when the whole commission is reversed.
- **Payouts:** the owner records a payout (amount, date, mode); the system allocates it to the oldest pending commissions first. A payout cannot exceed the broker's pending commission.
- **Reversals (returns and cancellations):** every reversal is saved as a `commission_adjustments` row (negative amount, source return or cancellation, date). For a credit note: `reversal = round(commission_percent_snapshot x credit_note_total / 100)`, never more than the commission still outstanding on that invoice (the final return takes any rounding remainder). A cancellation reverses the whole remaining commission. `commissions.adjusted_amount = amount + sum(adjustments)`.
- **Already paid:** if the broker has been paid more than the adjusted commission, the broker's balance shows a negative amount (recoverable); no automatic clawback is made.
- **Deactivated brokers** keep all history; they cannot be selected on new invoices.

**Commission as an expense (profit reporting):** commission is an expense recognised **when it accrues** (invoice date) and reduced by reversals (return or cancellation date). **Payouts are not expenses**; they only settle the liability. Reports therefore show three separate figures: commission expense (accrued net of reversals), commission paid, commission pending. Because payouts are excluded from expenses and reversals are separate adjustment rows, commission is never counted twice.

### 6.8 Customer dues
- Invoice `payment_status`: `UNPAID`, `PARTIAL`, `PAID`, `CANCELLED`.
- Payments: cash, UPI, card, bank transfer, cheque, with reference and note.
- A payment can be recorded at billing time or later on the invoice.
- **Receipts and allocations:** every money receipt is saved as a `receipts` header (receipt number, customer, amount, date, mode) with one `payments` row per invoice it settles (the allocation). A receipt entered on the customer page is split across that customer's oldest unpaid invoices.
- **Overpayments are blocked in Version 1:** a payment (or the total of a customer receipt) cannot exceed the outstanding due of the invoice(s) it is applied to. The server checks this while holding a lock on the invoice and returns `PAYMENT_EXCEEDS_DUE`. Customer advances (money received before a bill exists) need a separate customer ledger and are a future enhancement.
- Customer outstanding = opening balance + sum of invoice balances.
- The customer opening balance field supports dues that existed before using the app.
- Overdue = unpaid balance older than N days (setting `overdue_days`, default 30); shown on dashboard/notifications and in the dues ageing report (0-30, 31-60, 61-90, 90+).
- Receipts carry an idempotency key so a double click or retry never records a payment twice.
- Optional: "Send reminder" button that opens a WhatsApp/SMS link with a prefilled message.

### 6.9 Returns and cancellations

**Sales return (credit note):** against an invoice, choose items and quantity (cannot exceed sold minus already returned). All amounts are taken from the **stored invoice line snapshot**, never from current product data:
- **Revenue (excluding GST):** `returned_taxable = round(line.taxable_value x returned_qty / line.quantity)`; GST (CGST/SGST/IGST) is reversed in the same proportion. When the cumulative returned quantity equals the sold quantity, the return takes the remainder, so credit notes always add up exactly to the original line.
- **Credit note total** = returned taxable + returned GST (+ its own round-off to the nearest rupee). Credit notes use their own number series (`CN`).
- **Stock:** returned quantity goes back at the original **cost snapshot** (average recalculated, 6.3). **COGS** is reduced by `returned_qty x cost_snapshot`, so gross profit is reduced by the revenue reversed minus the cost reversed.
- **Commission:** reduced as described in 6.7 using the credit note total. The credit note itself never creates a commission.
- **Money:** the customer's balance due on the invoice is reduced first; any remaining credit is refunded (`REFUNDED` payment, not more than the amount actually received on that invoice). Refund as customer credit/advance is not available in Version 1.
- **Manual lines:** can be returned for revenue and GST reversal; they have no stock effect and a COGS reversal only if an internal cost was entered.

**Invoice cancellation:** allowed for the owner with a mandatory reason. Effects: every line counts as returned (same rules as above, one cancellation record), stock restored, commission fully reversed, payments marked refunded, invoice marked `CANCELLED`, **its number is never reused**.

**Invoices are not edited after saving.** To fix a mistake: cancel and recreate, or issue a return. This keeps GST records and profit history reliable.

**Purchase return:** returns stock to the company with its GST reversed; valuation follows the provisional rule in 6.3 (accountant approval pending, 13.14). Amounts reduce the company dues.

**No duplicate effects:** invoices, receipts, returns, payouts and purchases each carry an idempotency key with a unique constraint, and every stock, payment and commission effect is written inside the same database transaction as its document.

### 6.10 Purchases (stock in)
- Header: company, supplier invoice number, purchase date, supplier state (for CGST/SGST versus IGST), notes.
- Each line: product, quantity, **unit price excluding GST**, GST rate (from the approved list), and an **ITC eligible** flag (default from the setting `purchase_gst_recoverable_default`, to be confirmed with the accountant, 13.13).
- Per line the system calculates and **stores separately**: `taxable_value`, `cgst/sgst/igst`, `gst_amount`, `recoverable_gst`, `non_recoverable_gst`, `inventory_cost_total = taxable_value + non_recoverable_gst`, `inventory_cost_per_unit`, `avg_before`, `avg_after`.
- **Rule:** recoverable GST is excluded from inventory cost; non-recoverable GST is included in inventory cost. The purchase total payable to the company is `taxable + all GST`.
- On save: stock movements created at the line's inventory cost per unit, weighted average updated per product, last buying price recorded, company dues increased by the purchase grand total.
- The GST summary report shows input GST split into recoverable and non-recoverable.
- Payments to the company reduce dues (`company_payments`); a purchase has `payment_status` UNPAID, PARTIAL or PAID.

### 6.11 Invoice numbering
- Format: `INV/26-27/0001` (prefix / financial year / sequence). Financial year starts in April (setting).
- **Starting number:** the series starts at `INV/26-27/0001` unless existing paper invoices need to be continued; in that case the owner enters the next paper number as `series_start_number` for the current financial year before the first invoice (it cannot be lowered after an invoice exists).
- Generated **on the server inside the invoice transaction** using a counter row locked per series and financial year, so there are no gaps or duplicates even with parallel requests.
- The financial year of an invoice is taken from the **invoice date**.
- Separate series: `INV` (invoice), `CN` (sales return / credit note), `PUR` (purchase entry), `RCT` (payment receipt), `PR` (purchase return).
- A cancelled number is **never reused**; the cancelled invoice stays visible.
- The sequence restarts at 0001 at the start of each financial year.
- Back-dated invoices receive the next number in sequence (numbers follow the order of issue, the date shown is the chosen date); the audit log flags them (6.18).

### 6.12 Audit log
Recorded for: login/logout/failed login, create/update/deactivate of every master record, invoice create/cancel, **back-dated invoice creation (with the date entered and the actual time)**, payments, returns, stock adjustments, price and GST changes, commission payouts and reversals, settings changes (including approved GST rates), imports, exports, backups and restores.

Each entry: timestamp, action, entity type, entity id, human summary, **before and after values (JSON)**, IP address. The log is **append-only** (no edit/delete in the application) and viewable in Settings > Audit Log with filters by date, action and entity.

### 6.13 Profit and loss definitions

Three metrics, always kept separate:

| Metric | Definition |
|---|---|
| **Gross profit** | Net sales revenue **excluding GST** (after discounts and returns) minus cost of goods sold (cost snapshots, after return reversals) |
| **Profit after commission** | Gross profit minus broker **commission expense** (accrued commission net of reversals, 6.7) |
| **Net profit** | Profit after commission minus applicable operating expenses (rent, power, salaries, miscellaneous and custom categories) |

Rules:
- Historical invoice prices, discounts, tax snapshots and cost snapshots are used; current product data is never used for past periods.
- GST is never part of revenue or profit.
- Commission is **not** subtracted from the GST-inclusive invoice total; it is an expense against gross profit. Commission payouts are not expenses (6.7), and salary payments appear in expenses once (via the salary record, 6.14).
- Returns reduce revenue, GST, COGS and commission in the period of the credit note.
- Lines without a known cost (manual lines with no internal cost) are excluded from gross profit and shown as **profit incomplete** with the revenue involved, never silently counted as zero cost.
- The dashboard chart "Profit" series is **profit after commission**; the "Expense" series is operating expenses.

### 6.14 Employees
- Profile: name, phone, address, designation, joining date, monthly base salary, active flag (deactivate, never delete).
- Attendance per day: **Present (P), Absent (A), Half-day (HD), Paid leave (PL), Unpaid leave (UL), Holiday (H)** (one record per employee per day). The statuses and the day-weight each earns are configurable in Settings (defaults: P 1, HD 0.5, PL 1, UL 0, A 0, H 1).
- **Default salary basis: calendar days.** `salary = base_salary / days_in_month x paid_days`, where `paid_days` is the sum of the configured day-weights for the month. The basis can be changed in Settings (for example fixed 26 or 30 days).
- Salary adjustments per month: bonus, advance deducted, other deductions (each with a note); `net_payable = salary + bonus - advance - other deductions`.
- Marking a salary as paid automatically creates **one expense entry in the Salaries category** (no double entry).

### 6.15 Expenses
- Default categories: Rent, Power, Salaries, Miscellaneous. The owner can add more categories.
- Fields: category, amount, date, payment mode, note.
- **Recurring expenses** (rent, power): saved with a day of month; when the day arrives, the dashboard/notifications prompt "Rent due: add now?" with one click to create the entry. No background scheduler is needed.

### 6.16 Backups and Excel import/export
**Backups**
- Automatic daily database backup (managed database snapshots/point-in-time recovery, plus a nightly `pg_dump` to encrypted object storage).
- Retention: 7 daily, 4 weekly, 12 monthly.
- Backup status is logged (`backup_log`) and a failure raises a notification.
- A restore test is done monthly. A written restore procedure is part of the handover.
- In-app "Download full data export (Excel/ZIP of CSVs)" gives you your own copy anytime.

**Excel import** (products, customers, brokers, employees, opening stock)
1. Download the template.
2. Upload the file.
3. The system **validates** and shows a preview with row-level errors (duplicate product code, missing fields, bad numbers).
4. The owner confirms; valid rows are committed in one transaction (or the owner chooses to skip invalid rows).
5. An import record is saved and audited. Products are matched by product code (create or update).

**Excel export:** every list and report has an Export button (respects current filters).

### 6.17 Search and filtering
- Products: by code (primary), company, type, sub type, sub-sub type, stock status (in stock, low, out), active flag.
- Invoices: by number, customer, broker, date range, payment status, shade code, product.
- Search fields use PostgreSQL trigram indexes so partial matches stay fast.

### 6.18 Validation rules (key ones)
- **Selling price** must be greater than 0 when set; a **warning** (not a block) appears if the invoice selling price is below cost.
- **Quantity** must be positive and not exceed stock (unless negative stock is allowed). Manual lines are exempt from the stock check.
- **Discount** cannot exceed the invoice subtotal; a confirmation appears above a configurable percentage.
- **Commission percent** between 0 and 100; accepted from the client only as an optional override, never the amount or base.
- **Product:** product code unique; company, product type, pack size and unit required; category optional; GST rate must be on the approved list; HSN code text.
- **Billing readiness:** a product without selling price, GST rate or HSN cannot be added to an invoice (message: "Product needs price, GST rate and HSN before billing").
- **Invoice date:** past dates are allowed and audit-logged as back-dated; **future dates are blocked** (setting `allow_future_invoice_dates`, default off). *Assumption, not owner-confirmed (13.15):* back-dating into a previous financial year is blocked by default (setting `block_prior_fy_backdating`), because it would insert numbers into a closed series.
- **Payments:** a payment or receipt cannot exceed the outstanding due (`PAYMENT_EXCEEDS_DUE`); a refund cannot exceed the amount received on that invoice.
- **Returns:** quantity cannot exceed sold minus already returned.
- **Manual line:** description, quantity, selling price and GST rate (approved list) required; internal cost optional.
- Phone numbers validated (10 digits for India), GSTIN validated by format and state code.
