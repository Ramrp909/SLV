## 13. Open Items and Assumptions

### 13.A Confirmed for Version 1 (closed; see Section 2.1)
Product-wise GST, GST-inclusive prices, commission on the final invoice total including GST, commission accrual at issue with proportional reversal, purchase GST costing (recoverable excluded, non-recoverable included), back-dating with audit and no future dates, calendar-day salary basis, overpayments blocked, A4 printing only, invoice numbering with the invoice date inside the number, for example `INV/261105/0042` (starting serial 0001, or the continued paper number), optional category, manual non-stock lines.

### 13.B Open decisions (owner or accountant must supply or approve)

| # | Item | Status and interim behaviour |
|---|---|---|
| 13.1 | Verified GST rate and HSN code for each product, and the approved GST rate list | **Open.** Products can be loaded without them but cannot be billed until set; only rates on the approved list are accepted |
| 13.2 | Shop GSTIN, state and state code | **Open.** Configurable and may stay blank until supplied; needed for CGST/SGST versus IGST and for the invoice header |
| 13.13 | Is the shop eligible for input credit (is purchase GST recoverable)? | **Open (accountant).** Setting `purchase_gst_recoverable_default` is on by default as a starting value only; it can be set per purchase line |
| 13.14 | **Purchase-return valuation rule** | **Open (accountant approval).** Provisional rule: value the return at the inventory cost of the purchase line returned (else the current average) and recalculate the average (6.3). Alternative: return at current average with the difference booked as a purchase variance |
| 13.17 | Place-of-supply rules for the shop's customers | **Open (accountant to verify)** the defaults in 6.5 |
| 13.19 | Existing paper invoice numbers: last used number in the current financial year | **Data needed at go-live** if paper numbers are to be continued (entered as the series starting number) |
| 13.20 | Invoice number format with the date inside (`INV/261105/0042`) | **Open (accountant to confirm).** It meets the stated limits (consecutive serial within the financial year, unique, at most 16 characters, allowed characters); confirm it matches your GST practice |

### 13.C Assumptions (not owner-confirmed; configurable)

| # | Assumption | Default |
|---|---|---|
| 13.3 | One product code per size of the same product | Yes |
| 13.5 | Optional dashboard strip (today's sales, profit, dues, pending commission) | Included |
| 13.6 | Optional default GST rate for manual lines | None; the owner picks the rate on each manual line unless a default is set |
| 13.7 | CGST/SGST rounding: CGST = half-up of half the GST, SGST = remainder | As stated in 6.4 |
| 13.8 | Default attendance day-weights (P 1, HD 0.5, PL 1, UL 0, A 0, H 1) | Configurable in Settings |
| 13.15 | Back-dating into a previous financial year is blocked | Blocked by default (`block_prior_fy_backdating`); can be switched off |
| 13.16 | Opening stock buying price in the Excel is the inventory cost per unit (excluding recoverable GST) | Stated in the template instructions |
| 13.18 | A broker paid more than the adjusted commission shows a negative balance; no automatic recovery | As stated in 6.7 |

### 13.D Future enhancements (not in Version 1)
Customer advance ledger (payments before a bill exists), 80 mm thermal printing, staff logins with roles (including commission-override permission), branch or godown stock, price-exclusive invoicing mode as the owner default, e-invoice integration, WhatsApp sharing. See Section 17.
