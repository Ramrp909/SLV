## 2. Confirmed Decisions

### 2.1 Confirmed for Version 1 (owner decisions; not to be re-asked)

| # | Decision | Detail |
|---|---|---|
| 1 | Single user | One owner login only |
| 2 | Stock costing | **Weighted average inventory cost**. Recoverable GST on purchases is excluded from cost; non-recoverable GST is included (6.3, 6.10) |
| 3 | Product-wise GST | Every product has its own configurable GST rate and HSN code. Different products on one invoice may have different rates. Rates are validated against a configurable approved list (6.5) |
| 4 | GST-inclusive selling prices | Product selling prices are GST-inclusive by default (setting `prices_include_gst`, default on) |
| 5 | Broker commission base | `commission_amount = final invoice total including GST, after all discounts x commission rate / 100`, using the backend-calculated, saved `grand_total` (6.7) |
| 6 | Commission timing | Commission accrues when the invoice is issued and is reversed proportionally for returns and cancellations (6.7, 6.9) |
| 7 | Purchase costing | Purchase tax is stored separately: taxable value, GST, recoverable GST, non-recoverable GST (6.10) |
| 8 | Back-dated invoices | Past invoice dates are allowed and audit-logged; future dates are blocked by default (6.18) |
| 9 | Employee salary | Calendar days is the default basis; attendance, leave, bonus and deductions are configurable (6.14) |
| 10 | Overpayments | Payments above the outstanding due are blocked in Version 1; a customer advance ledger is a future enhancement (6.8) |
| 11 | Invoice printing | A4 in Version 1; 80 mm thermal printing deferred (9.4) |
| 12 | Invoice numbering | Starts at `INV/26-27/0001` unless existing paper numbers must be continued (starting number is a setting); server-generated, gap-free, never reused after cancellation (6.11) |
| 13 | Product category | Optional. Required product fields: company, product type, product code, pack size and unit (6.1) |
| 14 | Manual invoice lines | Non-stock manual lines with an optional internal cost for profit reporting (15.6) |

### 2.2 Earlier confirmed decisions (still valid)

| # | Decision | Detail |
|---|---|---|
| 15 | Deactivation | Brokers, employees, and records with history are deactivated, never deleted |
| 16 | Shade/colour codes | Captured per invoice line |
| 17 | Customer dues | Partial payments and credit sales tracked |
| 18 | Backups | Automatic daily backups plus a restore procedure |
| 19 | Excel | Import and export; the owner prepares data in the application's template |
| 20 | Audit log | Every important change recorded |
| 21 | UI and layout | Follows the reference dashboard image; left menu about 15% |
| 22 | Performance | Lightweight frontend, no heavy animation or processing in the browser |
| 23 | Prices | Each product holds a buying price and a selling price |
| 24 | Product hierarchy | Company, product type (Walmasta, Bison...), sub type (base code), optional sub-sub type, product code |
| 25 | Companies | Separate companies tracked: stock, purchases, payments, dues, sales and profit |
| 26 | Hardware | Bought and sold in pieces; same GST invoice as paints |
| 27 | Future | API-first, versioned, configurable, extensible design (Section 17) |

### 2.3 Assumptions (not owner-confirmed) and future enhancements
Assumptions and unresolved items are kept separate in **Section 13** (open decisions) so that nothing unresolved is treated as approved. Future enhancements (customer advance ledger, thermal printing, staff logins, branch stock) are listed in Section 17.
