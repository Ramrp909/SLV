## 12. Worked Examples

All rupee figures are illustrative. GST rates used here (18% and 5%) are chosen only to show the arithmetic of mixed rates; they are **not** verified rates for the shop's products.

### 12.1 Weighted average cost, with and without recoverable GST
Prices excluding GST. Last month 10 tins at 300, this month 10 tins at 400.

| Step | Quantity | Average inventory cost per tin | Note |
|---|---|---|---|
| Last month purchase | 10 at 300 | 300 | qty 10 |
| This month purchase | 10 at 400 | (10x300 + 10x400)/20 = **350** | qty 20 |
| Sell 15 tins | -15 | 350 | cost snapshot 350 each, cost of goods 5,250; qty 5 |
| Purchase 10 at 420 | +10 | (5x350 + 10x420)/15 = **396.6667** | qty 15, stock value 5,950.00 |

**GST treatment on the same two purchases (illustrative 18% GST):**

| | Purchase 1 (10 at 300) | Purchase 2 (10 at 400) | Average |
|---|---|---|---|
| GST amount | 540.00 | 720.00 | |
| **GST recoverable**: inventory cost per tin | 300 (recoverable GST 540 stored separately) | 400 (recoverable GST 720 stored separately) | **350** |
| **GST non-recoverable**: inventory cost per tin | 354 | 472 | **413** |
| Payable to the company | 3,540.00 | 4,720.00 | |

### 12.2 Invoice with mixed GST rates, discount, commission and profit
Assumptions: prices include GST, same state, invoice discount 5%, broker commission 10% of the final invoice total.

| Line | Qty | Selling price (incl. GST) | Gross | GST rate | Cost snapshot per tin |
|---|---|---|---|---|---|
| A (4L tin) | 10 | 520 | 5,200 | 18% | 350 |
| B (4L tin) | 2 | 700 | 1,400 | 5% | 500 |

- Subtotal 6,600; discount 5% = 330, allocated by line value: A 260, B 70 (last line takes any remainder)
- Discounted values (incl. GST): A 4,940.00, B 1,330.00, total **6,270.00**
- A: taxable 4,186.44, GST 753.56 (CGST 376.78, SGST 376.78)
- B: taxable 1,266.67, GST 63.33 (CGST 31.67, SGST 31.66; CGST rounds half-up, SGST is the remainder)
- Totals: taxable **5,453.11**, GST **816.89** (CGST 408.45, SGST 408.44), round-off 0.00, **grand total 6,270.00**
- GST summary: 18% taxable 4,186.44 / tax 753.56; 5% taxable 1,266.67 / tax 63.33
- Cost of goods: 10x350 + 2x500 = 4,500.00
- **Gross profit** = 5,453.11 - 4,500.00 = **953.11** (A 686.44 + B 266.67)
- **Commission** = 6,270.00 x 10% = **627.00** (final invoice total including GST)
- **Profit after commission** = 953.11 - 627.00 = **326.11**
- Payment received 5,000.00 gives balance due **1,270.00**, status `PARTIAL`

The printed invoice shows lines, tax and totals only; commission and profit are visible only to the owner.

### 12.3 Manual non-stock line (opened pack sold in part)
The owner sells 3 litres of thinner from an opened drum as a manual line: quantity 3 LTR, selling price 120.00 per litre including GST, GST rate chosen from the approved list (illustrative 18%).
- Line value 360.00; taxable = 360.00 / 1.18 = **305.08**; GST **54.92**
- No stock movement is created (the owner adjusts the drum's stock separately through Stock Update if needed)
- With internal cost 80.00 per litre entered: cost 240.00, line profit = 305.08 - 240.00 = **65.08**
- With no internal cost: line profit is **unknown**, the invoice shows "profit incomplete", and `unknown_cost_taxable_value` = 305.08 is reported separately (it is not treated as zero cost)
- The 360.00 is part of the invoice grand total, so it is included in the commission base like every other line

### 12.4 Customer returns 2 tins of A (from 12.2)
- Invoice line A: discounted value 4,940.00 over 10 tins; returning 2 tins = 988.00 incl. GST
- Returned taxable = round(4,186.44 x 2/10) = **837.29**; returned GST = 150.71 (CGST 75.36, SGST 75.35); **credit note total 988.00**
- Stock +2 tins at the cost snapshot 350; COGS reversed 700.00
- Gross profit becomes 953.11 - (837.29 - 700.00) = **815.82**
- Commission reversal = 10% x 988.00 = **98.80**; commission becomes 627.00 - 98.80 = **528.20**
- Profit after commission = 815.82 - 528.20 = **287.62**
- Invoice payable 6,270.00 - 988.00 = 5,282.00; paid 5,000.00; balance due **282.00**

### 12.5 Receive payment across invoices; overpayment blocked
Customer has INV/26-27/0010 balance 1,270 (older) and INV/26-27/0014 balance 500 (outstanding 1,770).
- Customer pays 1,500: one receipt, two allocations: 0010 cleared (1,270) and 0014 receives 230 (balance 270).
- If the customer tried to pay 2,000 against outstanding 1,770, the server rejects it with `PAYMENT_EXCEEDS_DUE` (maximum 1,770). Customer advances are a future enhancement.

### 12.6 Invoice numbering
`INV/26-27/0001` ... `INV/26-27/0007` (cancelled, number kept, never reused) ... `INV/26-27/0008` next. From 1 April 2027: `INV/27-28/0001`. If the owner continues paper invoices and sets the starting number to 215, the first system invoice is `INV/26-27/0215`.

### 12.7 Back-dated and future dates
Entering 28 October 2026 on 5 November 2026 (same financial year) is accepted, flagged `is_backdated` and written to the audit log. Entering 6 November 2026 on 5 November is rejected (`FUTURE_DATE_NOT_ALLOWED`). Entering 20 March 2026 (previous financial year) is rejected by default (`PRIOR_FY_BACKDATE_BLOCKED`, assumption 13.15).

### 12.8 Salary on calendar days
Base salary 20,000; a 30-day month; attendance: Present 24, Holiday 2, Half-day 2, Paid leave 1, Unpaid leave 1 (default weights P 1, H 1, HD 0.5, PL 1, UL 0).
- Paid days = 24 + 2 + (2 x 0.5) + 1 + 0 = **28**
- Salary = 20,000 / 30 x 28 = **18,666.67**; bonus 1,000.00, advance deducted 2,000.00
- Net payable = 18,666.67 + 1,000.00 - 2,000.00 = **17,666.67**; when paid, one Salaries expense of this amount is created
