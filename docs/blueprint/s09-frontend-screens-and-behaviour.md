## 9. Frontend Screens and Behaviour

General rules for all screens: server-side pagination, filter bar above tables, Export (Excel) button on lists, empty states with a clear action, inline validation messages, unsaved-changes warning on forms, amounts shown with the rupee symbol and Indian digit grouping (e.g. 1,23,456.00).

### 9.1 Login (`/login`)
- Fields: username, password, **Login** button. Nothing else (no sign-up, no forgot-password link; password reset is done by the developer/command).
- Show/hide password toggle, Enter key submits.
- Wrong credentials show a generic message; after 5 failed attempts in 15 minutes the account is locked for 15 minutes (message shown).
- Success redirects to `/dashboard`. Already logged-in users opening `/login` go to the dashboard.
- Idle auto-logout after the configured minutes (default 30).

### 9.2 Application shell
- **Left menu (15%)** and **header** exactly as in 5.4 and 5.5.
- Active menu item highlighted as a pill; submenus expand in place.
- Header search results dropdown; keyboard `/` focuses search, `Esc` closes.
- Route guard: no token means redirect to login. A 401 response triggers one silent token refresh, then logout.

### 9.3 Dashboard (`/dashboard`)
Layout follows the reference image. One API call (`/dashboard`).

| Widget | Content | Notes |
|---|---|---|
| Overview: Total Products | Count of active products | Click goes to Inventory Items |
| Overview: Invoices | Invoices this month (today's count in small text) | Click goes to All Invoices |
| Overview: Total Stock | Total **stock value** at cost (rupees), with unit counts | Different units cannot be added together |
| Overview: Out of Stock | Count of products with zero stock; orange tint; **info icon tooltip** lists first 10 product codes | Click opens Inventory filtered to out of stock |
| Total Customers | Customer count | |
| Pie: Inventory | Sold vs remaining stock by **value** (this financial year) with percentages | |
| Top 10 Brokers by sales | Horizontal bars with amounts; period switch (This month / Quarter / Year) | Click opens broker detail |
| Expense vs Profit | Area/line chart, last 6 months; "Highest Expense" and "Highest Profit" markers | Profit = profit after commission; Expense = operating expenses (6.13) |
| Optional strip (recommended) | Today's sales, today's profit, customer dues, broker commission pending | Small row of four cards, can be removed if you want the image exactly |

### 9.4 Invoices

**All Invoices (`/invoices`)**: table columns: Invoice No, Date, Customer, Broker, Total, Paid, Balance, Status, actions (View, Print, Add payment, Cancel). Filters: date range, customer, broker, status, shade code, invoice number. Summary strip above table: count, total sales, collected, outstanding. Profit and commission columns are shown **only on the owner detail view**, hidden by default in the list (toggle).

**Today Billings (`/invoices/today`)** and **Past Billings (`/invoices/past`)**: the same list with a preset date filter (today / before today). The header calendar opens Past Billings for the chosen date with a **day summary strip** (invoices, sales, collected, profit).

**Create Invoice (`/invoices/new`)**: the most important screen. Built for speed (keyboard friendly).

Top section:
- Invoice number: shown as "Auto" (assigned by server on save). Invoice date (default today): past dates are allowed and logged as back-dated; future dates are blocked ("Future invoice dates are not allowed").
- **Customer:** search by name/phone, or **+ New customer** inline (name, phone, optional address/state/GSTIN).
- **Broker:** optional search; shows default commission percent. Walk-in customers: leave blank.
- Place of supply (defaults from customer state, otherwise shop state).

Items grid (add rows with Enter/Tab; no limit on rows):

| Column | Behaviour |
|---|---|
| Product code | Type-ahead search by code (primary), also name/company. Scanner input works |
| Product details | Company, type, sub type, pack size auto-shown (read-only) |
| Shade code / shade name | Optional text |
| Stock | Available packs shown; warning if quantity exceeds |
| Quantity | Number of packs |
| Default price | Read-only reference |
| Selling price | **GST-inclusive, editable**, prefilled with default price; warning if below cost |
| Line discount | Optional |
| GST % | From product (read-only). Lines may have different rates. A product without GST rate/HSN or price cannot be added ("Product needs price, GST rate and HSN before billing") |
| Line total | Calculated |

**Manual line:** the last empty row of the grid accepts a hand-typed, non-stock line (description, quantity, unit, GST-inclusive selling price, GST rate from the approved list, optional internal cost). It has no product link and no stock effect; without an internal cost the invoice shows a "profit incomplete" badge on the owner panel. See Section 15.6.

Footer:
- Subtotal, **invoice discount** (percent or amount), taxable value, CGST/SGST or IGST, round-off, **grand total**.
- **Payment:** amount received now, mode, reference. Balance due shown. The amount cannot exceed the grand total ("Payment exceeds amount due"). Leaving it empty creates a credit sale.
- Notes (internal).
- **Owner-only panel** (collapsible, clearly labelled "Not printed on invoice"): broker, **commission %** (editable), commission amount (always grand total x rate, calculated by the server and never typed), expected gross profit and **profit after commission**, a "profit incomplete" badge when a manual line has no cost, and a below-cost flag.

Actions: **Save**, **Save and Print**, **Save and New**. Duplicate-click safe (idempotency key). On success shows the invoice with Print button.

Keyboard shortcuts: `Alt+N` new invoice, `Alt+S` save, `Alt+P` save and print, `/` focus search.

**Invoice view (`/invoices/{id}`)**: header (number, date, status badge), customer and broker, line items, GST breakup, payments list with Add payment, return/cancel actions, owner panel (commission, profit, cost snapshots), audit trail for this invoice.

**Print layout (A4 only in Version 1; 80 mm thermal printing is deferred):** A4 print stylesheet (browser print or Save as PDF), shop logo, name, address, GSTIN, customer details (GSTIN if present), item table with product code, name, shade, HSN, quantity, rate, GST, amount, tax summary, round-off, grand total in figures and words, amount paid and balance, terms, signature line. **No commission, broker percentage, cost or profit anywhere.**

### 9.5 Brokers

**Broker Sales Performance (`/brokers/performance`)**
- Period selector (month, quarter, year, custom).
- Ranking table: broker, number of invoices, total sales, gross profit generated, commission earned, commission paid, commission pending, average bill value.
- Bar chart of top brokers. Sorting by sales or profit. Quarterly and annual views answer "who brought the most business and profit."

**Broker Profiles (`/brokers/profiles`)**
- List with search, status filter (active/inactive). **Add broker** (name, phone, address, default commission percent, notes). Edit. **Deactivate/Activate** (no delete). Inactive brokers cannot be chosen on new invoices.

**Broker detail (`/brokers/{id}`)**
- Summary cards: total sales, total commission, paid, pending.
- **Commission ledger:** date, invoice number, customer name, final invoice total (including GST, after discount), applied commission percent, commission amount, reversals, paid so far, status.
- **Record payout:** amount, date, mode; allocated to oldest pending commissions automatically; payout history list.
- Date and customer filters, Excel export.

### 9.6 Customers (`/customers`)
- List: name, phone, total purchases, **outstanding balance**, last purchase date. Search, filter (has dues, active).
- Customer detail: profile (edit), **bill details list** (invoice number, date, total, paid, balance, broker), shades used before, ledger/statement, **Receive payment** button (amount split across oldest unpaid invoices), WhatsApp/SMS reminder link, statement export.
- Customers with history cannot be deleted (deactivate only).

### 9.7 Inventory

**Inventory Items (`/inventory/items`)**
- Table: product code, company, type, sub type, sub-sub type, pack size and unit, quantity (units), litres (liquid products only), average inventory cost per unit, selling price (GST-inclusive), GST rate, stock value, status chip (In stock / Low / Out) and a "Needs tax/price details" badge when the product is not billing-ready.
- Filters: company, type, sub type, stock status, active; search by product code first.
- Actions: Add item, Edit, Deactivate, Import Excel, Export.

**Add / Edit Item (`/inventory/items/new`)**: first screen to be built and delivered.
- Fields: product code (mandatory, uniqueness checked live), company (dropdown + quick add), category (optional), product type, sub type, sub-sub type (optional), pack size and unit, **buying price**, **selling price**, GST rate and HSN, minimum stock level, track stock, and for new products **opening quantity**. Stock value is shown as a calculated value.
- On save with opening quantity, an `OPENING` stock movement is created.
- Editing an item cannot change stock quantity directly (use Stock Update).
- Bulk add by Excel import with preview.

**Product Catalog (`/inventory/catalog`)**: company dropdown; selecting a company shows that company's items as a compact card/table list with stock and price; click goes to item detail.

**Item detail:** summary, stock movement history, price history, sales of this item, edit.

**Stock Update (`/inventory/stock-update`)**
- Tab 1: **New purchase** (links to Orders > Purchase Items entry form).
- Tab 2: **Adjustment:** product, in/out, quantity, reason (damage, leakage, opened pack, found, correction), date. Writes a movement and an audit entry.
- Tab 3: **Stock take:** choose a company or category, enter counted quantities, see differences, confirm to post adjustments.

**Companies (`/inventory/companies`)**
- List of companies with stock value, purchases, paid, dues. Company detail: profile, products, purchases, payments (Record payment), ledger, company-wise sales and profit, Excel export. Companies are added or deactivated here (no delete).

### 9.8 Orders

**Purchase Items (`/orders/purchases`)**
- List of purchases (date, company, supplier invoice no., total, paid, balance).
- **New purchase:** company, supplier invoice number, date, rows of product code, quantity, unit price (excluding GST), GST rate, input-credit (ITC) eligible flag; totals with GST split into recoverable and non-recoverable; paid amount. On save shows the new average inventory cost per product.

**Return Items (`/orders/returns`)**
- Tabs: **Customer returns** (select invoice, items and quantity, reason, refund method) and **Returns to company** (select purchase/company, items, quantity).
- Shows effect preview (stock, revenue and GST reversed, commission reduction, refund or reduced balance) before saving.

### 9.9 Sales

**Sales Analysis (`/sales/analysis`)**
- Period selector. Charts: sales trend, by company, by type. Tables: top products, margin by product/company, average discount given, fast movers, slow/non-moving stock, month versus same month last year.

**Broker Commissions (`/sales/broker-commissions`)**
- Commission given to each broker and the sales they brought (period filter), pending versus paid, commission as a percentage of sales, and profit after commission per broker.
- Additional suggested views: customers with highest dues, discount given per invoice, best-selling shades.

### 9.10 Employees
- **Employee Profiles:** list, add, edit, deactivate/activate (no delete).
- **Attendance:** date picker (defaults today); one row per active employee with status buttons (P, A, HD, L, H); Save marks all in one call; monthly grid view with summary counts.
- **Salary:** choose month; system calculates per employee from attendance; edit bonus/advance/deductions; **Mark as paid** (date, mode) creates the Salaries expense; shows pending and paid.

### 9.11 Expenses (`/expenses`)
- Month selector and totals per category (Rent, Power, Salaries, Miscellaneous, custom).
- **Add expense:** category, amount, date, mode, note. List with filters. Salary expenses appear automatically and are read-only (edit via salary).
- **Recurring:** manage rent/power templates; "due now" prompts appear on the dashboard bell with one-click add.

### 9.12 Reports (`/reports`)
- **Period reports:** weekly, monthly, quarterly (financial-year quarters), annual: sales, discounts, GST, gross profit, commission expense (accrued, net of reversals), profit after commission, expenses, net profit, and revenue with unknown cost (profit incomplete), with comparison to the previous period.
- **Item min/max sold:** most and least sold items for the chosen period, with non-moving stock list.
- Additional reports: Profit and Loss, GST summary (for accountant), customer dues ageing, stock valuation, broker report, expense report, daily sales summary.
- Every report: date range, filters, on-screen table plus chart where useful, **Export to Excel**.

### 9.13 Settings
- **Shop profile:** logo, name, address, phone, GSTIN, state and state code, invoice footer and terms (GSTIN and state may stay blank until verified values are supplied).
- **GST rates:** the approved GST rate list (add, activate, deactivate). Products, purchase lines, manual lines and imports can only use these rates.
- **Tax and billing:** prices include GST (default on), default GST rate for manual lines (optional), discount warning percent, below-cost policy (warn), purchase GST recoverable by default (confirm with accountant).
- **Dates:** allow future invoice dates (off), block back-dating into a previous financial year (on).
- **Commission:** default percent and whether the commission rate can be overridden on an invoice. (The commission base is fixed: invoice grand total.)
- **Stock:** allow negative stock (off), low-stock defaults.
- **Numbering:** prefix, financial-year start, **starting number for the current year** (used only to continue paper invoice numbers), view series.
- **Employees:** salary basis (calendar days default), attendance statuses and day-weights.
- **Printing:** A4 (thermal 80 mm deferred).
- **Data:** Excel import wizard, full export, backup status and last backup time.
- **Audit Log** viewer.
- **Security:** change password, idle logout time.

### 9.14 Shared components
App shell, DataTable (server pagination, sort, filter bar), SearchSelect (async), MoneyInput (Indian formatting, 2 decimals), DateRangePicker, StatusChip, ConfirmDialog, ExportButton, ImportWizard, StatCard, charts (Pie, Bar list, Area), Toast, EmptyState, Skeleton, PrintLayout.
