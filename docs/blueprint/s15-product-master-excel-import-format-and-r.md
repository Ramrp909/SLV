## 15. Product Master, Excel Import Format and Resolved Decisions (v3)

This section replaces the earlier stock-sheet analysis. Your answers settled the open questions, and the sample sheet is now used only to learn what kinds of items the shop sells.

### 15.1 What the sample sheet taught us (sample data only, not to be imported)
The sample file (`STOCK_OF_SHOP_JUNE_2026`, headed SLV PAINTS AND HARDWARE) has about 567 lines in five blocks (Berger, Local, Extra material, Rollers/blades/brushes, Polish material). It shows the shapes of products the application must support:

| Shape | Examples in the sample | What it needs |
|---|---|---|
| Paint with bases and several sizes | Long Life 10, Walmasta, Bison, Antidust in 1, 4, 10, 20 LTR with base codes PO, P1, N1, YL... | Product type + sub type (base) + size, one code per size |
| Colours in small packs | Enamels, stainers, metallics in 50 ML to 4 LTR | Same structure, many rows |
| Bagged goods | Putty, cement, powders in KG | Pack size + unit KG |
| Hardware sold in pieces | Blades, brushes, flats, rollers, tape | Unit PCS, size as sub type |
| Sandpaper | PAPER-50 to PAPER-220 (roughness) | Unit PCS, roughness as sub type |

Problems seen in the sample that become **import checks** in the application: missing prices, the same item listed twice, spelling variants of one name, sizes typed in mixed formats, totals typed by hand, and mixed units in one column. The import validates all of these (15.8).

### 15.2 Your answers and the decisions they led to

| # | Your answer | Decision in the blueprint |
|---|---|---|
| 1 | Unit price in the sample is the selling price; keep both buying and selling price | Every product holds **buying price** (becomes the weighted average cost) and **selling price** (default on invoices). Both are columns in the Excel template |
| 2 | Base codes are the sub-types; anything extra goes in sub-sub type | `sub_type` = base code or main variant; `sub_sub_type` = any extra detail (optional) |
| 3 | Walmasta, Bison are product types | `product_type` = product name such as Walmasta, Bison, Antidust, Long Life 10 |
| 4 | Product codes exist | Product code is mandatory and unique, taken from your Excel (no code generator needed) |
| 5 | Track separate companies | New company module: company-wise stock, purchases, payments to company, dues, sales and profit (15.5) |
| 6 | Blades, brushes, flats are bought in pieces | Bought and sold in the same unit (PCS). No purchase-to-sale unit conversion needed |
| 7 | Opened large packs are added manually in an empty invoice field; no automation | **Manual invoice line** (15.6). No repack feature |
| 8 | Paper-50 to paper-200 are roughness, sold per piece | Sandpaper: product type Sandpaper, sub type = roughness, unit PCS |
| 9 | Missing data in the sample does not matter | Dropped |
| 10 | You will prepare your own Excel after the blueprint, then we analyse and import | The Excel format is defined in 15.8, and a ready template file is supplied (`product-import-template.xlsx`) |
| 11 | Hardware goes on the same GST invoice | One invoice, per-item GST rate and HSN code, for paints and hardware together |
| 12 | Make the application future ready; add ER, API and data flow diagrams | Section 16 (diagrams) and Section 17 (future-ready design) |

### 15.3 Final product master

A product is **one sellable item with one size** (for example Walmasta, base P1, 20 LTR). The same paint in four sizes is four products with four codes.

| Field | Required | Notes |
|---|---|---|
| Product code | **Yes** | Unique, case-insensitive, your existing code. Used for search, filter and billing |
| Company | Yes | Berger, Local, Asian... one company per product |
| Category | No | Optional group for reports (Paint, Primer, Enamel, Stainer, Putty, Hardware...) |
| Product type | Yes | Walmasta, Bison, Blade, Sandpaper... |
| Sub type | No (usually filled) | Base code for paints (PO, P1, N1...), size or roughness for hardware |
| Sub-sub type | No | Any extra detail |
| Pack size and pack unit | Yes | Number plus unit: LTR, ML, KG, G, PCS, SET, MTR (list can be extended in Settings) |
| Quantity on hand | System | In units (tins, bags, pieces); changed only through purchases, sales, returns, adjustments, stock take |
| Buying price | Required only when opening quantity is above 0 | Per unit, excluding recoverable GST; becomes the weighted average inventory cost (6.3) |
| Selling price | No at creation; needed before billing | GST-inclusive default per unit on invoices; editable per invoice |
| GST rate and HSN code | No at creation; needed before billing | Per product; GST rate must be an approved rate (6.5); verified values come from the owner |
| Minimum stock | No | Low-stock alert |
| Track stock | Yes (default Y) | N for items you do not count |
| Active | Yes (default Y) | Deactivate instead of delete |
| Custom fields | No | Extra fields added later without changing the database design (Section 17) |

Illustrative examples (made-up values, only to show how names map to fields):

| Company | Product type | Sub type | Sub-sub type | Size | Unit |
|---|---|---|---|---|---|
| Berger | Walmasta | P1 | | 20 | LTR |
| Berger | Bison | PO | | 10 | LTR |
| Berger | Fast Red (stainer) | STN | | 100 | ML |
| Berger | Waterproof Putty | | | 40 | KG |
| Local | Blade | 4 inch | | 1 | PCS |
| Local | Sandpaper | 120 | | 1 | PCS |

Product type, sub type and sub-sub type are saved with autocomplete and are compared **ignoring capital letters and extra spaces**, so "Walmasta", "WALMASTA " and "walmasta" are treated as one name.

**Totals across different units:** litres, kilograms and pieces cannot be added together. The dashboard therefore shows **stock value in rupees**, plus unit counts per unit type where needed. "Litres sold" appears only for LTR/ML products.

### 15.4 Pricing recap (unchanged logic)
- **Buying price** feeds the weighted average cost; each invoice line stores a **cost snapshot**, so profit never changes later.
- **Selling price** is the default price on the invoice line and can be edited per customer.
- Opening stock from Excel sets the starting average inventory cost equal to the buying price in the file, which must **exclude recoverable GST** (and include any non-recoverable GST).

### 15.5 Company tracking (new module)
Companies appear under **Inventory > Companies** and in Orders. For each company:
- Profile: name, GSTIN, phone, address, notes, active flag, "local/unbranded" flag.
- **Stock held** (units and value at cost) and product list.
- **Purchases** with supplier bill number and totals.
- **Payments to the company** (amount, date, mode, optional purchase reference). A payment can be split across the oldest unpaid purchases, like customer receipts.
- **Company dues** = purchases total minus payments.
- **Company-wise sales and profit** (period filter) and best-selling products per company.
- Excel export of the company ledger.

New table `company_payments` (company, purchase optional, amount, date, mode, reference, note). Purchases gain a payment status (UNPAID, PARTIAL, PAID).

### 15.6 Manual invoice line (for opened packs and one-off items) - confirmed
Each invoice has an empty row where you can type a line by hand:
- Fields: description, quantity, unit (text), GST-inclusive selling price, GST rate (from the approved list; an optional default can be set in Settings), **optional internal cost**.
- It is **not linked to a product** and creates **no stock movement** or average cost change (you adjust the opened pack's stock yourself through Stock Update when needed).
- It is included in the invoice totals, GST, round-off, payment and the commission base (the grand total).
- **Profit:** with an internal cost, line profit = taxable value minus the entered cost. **Without a cost, profit is unknown, not zero:** the invoice is flagged `profit_complete = false`, the line's taxable value is reported as `unknown_cost_taxable_value`, and reports show "profit incomplete" with the revenue involved.
- The invoice stores `is_manual = true`; the print shows the description like any other line (the internal cost is never printed).
- Returns of manual lines reverse revenue and GST; COGS is reversed only if a cost was entered.

### 15.7 Hardware and sandpaper rules
- Hardware is bought and sold in pieces: the same unit in purchases and invoices.
- Roughness (50 to 220 and so on) is the sub type of the Sandpaper product type, so it is searchable and filterable.
- Hardware items use the same invoice, GST calculation, discounts, commission base and returns as paints.

### 15.8 Excel import format (version 1)

You will prepare the Excel file; the application reads it. The template file **product-import-template.xlsx** has the sheets *Instructions*, *Products* (empty, for your data), *Example* (illustrative rows) and *Lists* (drop-down values).

**Rules for the Products sheet:** one header row (row 1), one product per row from row 2, no merged cells, no totals, no blank separator rows, no section titles, numbers without symbols or commas.

| Column | Required | Format | Example |
|---|---|---|---|
| product_code | **Yes** | Text, unique | BGR-WM-P1-20L |
| company | **Yes** | Text | Berger |
| category | No | Text | Interiors |
| product_type | **Yes** | Text | Walmasta |
| sub_type | No | Text | P1 |
| sub_sub_type | No | Text | |
| pack_size | **Yes** | Number greater than 0 | 20 |
| pack_unit | **Yes** | LTR, ML, KG, G, PCS, SET, MTR | LTR |
| opening_qty | No | Number, blank = 0 | 4 |
| buying_price | Yes **if opening_qty is above 0** | Number, per unit, excluding recoverable GST | |
| selling_price | No (needed before billing) | Number, GST-inclusive, per unit | |
| gst_rate | No (needed before billing) | Number; must be an **approved GST rate** | |
| hsn_code | No (needed before billing) | Text | |
| min_stock | No | Number | |
| track_stock | No | Y or N, default Y | Y |
| active | No | Y or N, default Y | Y |
| description | No | Text | |

Only product code, company, product type, pack size and pack unit are always required; category stays optional. GST rates and HSN codes are left blank until verified values are available; the actual rates and codes are never assumed by the system or this document.

**Checks done on upload** (nothing is saved until you confirm):
1. Column headers match the template.
2. Required values present; numbers are numbers; units are in the list.
3. `gst_rate`, when given, is on the **approved GST rate list** (otherwise: "add this rate in Settings > GST rates first").
4. `buying_price` present when `opening_qty` is above 0.
5. `product_code` unique within the file and not already used by a different item.
6. Duplicate warning when company + product type + sub type + sub-sub type + size + unit repeat under different codes.
7. Warning when selling price is below buying price.
8. Spelling-variant warning when a company, product type or sub type differs from an existing one only by case or spaces.
9. Summary count of rows that are **not billing-ready** (missing selling price, GST rate or HSN).
10. A **preview** lists new products, updated products, new companies to be created, warnings and errors. You can download an error report, fix the file and upload again.

**What the import does on confirm (one transaction):** creates new companies and products, creates **opening stock** movements for rows with `opening_qty` (average inventory cost starts at `buying_price`), updates master data (names, prices, GST, HSN, min stock) for codes that already exist (never overwriting with blanks unless the owner ticks "clear blank fields"), writes an import record and audit entries.

**What it never does:** overwrite stock quantity of an existing product (stock changes only through purchases, sales, returns, adjustments or stock take).

**Later templates** (same method): customers, brokers, employees, purchases and stock-count sheets. They will be added when needed.

### 15.9 Roadmap effect

| Phase | Change | Effort |
|---|---|---|
| 0 Discovery | Freeze the Excel template columns with you; you prepare the data file in parallel | +2 days |
| 2 Inventory master | Pack size and unit, company module basics, import wizard with validation and preview | +0.5 week |
| 3 Purchases and stock | Company payments and dues, company ledger | +0.5 week |
| 5 Billing | Manual invoice line | included |
| 8 Dashboard | Stock value instead of mixed-unit totals | included |
| 9 Reports | Stock take, month-end snapshot, "stock sheet" Excel export | +0.5 week |

Single developer: about **20 to 21 weeks**; two developers in parallel: about **12 to 14 weeks**. The Gantt chart in 16.16 shows the sequence.

### 15.10 Remaining open items
The twelve business decisions are confirmed and closed (Section 2.1). What is still open is listed in **Section 13**: verified GST rates, HSN codes and the approved rate list (13.1), shop GSTIN and state (13.2), input-credit eligibility (13.13), the purchase-return valuation rule (13.14), place-of-supply verification (13.17), and the last paper invoice number if numbering is continued (13.19). Assumptions (13.3, 13.5 to 13.8, 13.15, 13.16, 13.18) stay configurable and are not claimed as approved.
