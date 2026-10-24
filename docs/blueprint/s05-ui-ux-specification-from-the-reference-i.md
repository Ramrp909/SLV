## 5. UI/UX Specification (from the reference image)

The reference is an "Inventory Management Dashboard" design with a dark teal-blue left sidebar, soft rounded cards on a light blue background, and muted blue/green/orange chart colours. Your application keeps this **visual style and dashboard layout**, with **your menu structure and header requirements**.

### 5.1 What the reference image contains

| Region | In the image | In our app |
|---|---|---|
| Sidebar | Dark teal-blue panel, profile photo, name and email at top, menu list, active item shown as a light pill that merges into the page, Logout at bottom | Same style. Width about 15%. Profile name goes in the header (per your requirement); sidebar top shows shop logo and name area on small screens. Menu items as per Section 5.4. Logout at bottom |
| Header | "Welcome Nirmal!" greeting, search box with icon, light/dark toggle, notification bell | Shop logo + shop name (left), date calendar, global search, **Create Invoice** icon, **previous day sales** icon, notification bell, theme toggle, profile name (right) |
| Overview row | 4 cards: Total Products, Orders, Total Stock, Out of Stock (orange tint, info icon) | Total Products, Invoices, Total Stock, Out of Stock (info tooltip lists items) |
| Customers card | "No of users: Total Customers 583K" | Total Customers |
| Pie chart | "Inventory Values", Sold units vs Total units (32% / 68%) | Sold vs Remaining stock |
| Bar list | "Top 10 Stores by sales" horizontal bars with values | **Top 10 Brokers by sales** (with period switch) |
| Area/line chart | "Expense vs Profit, Last 6 months", with "Highest Expense" and "Highest Profit" markers | Same, with real expense and profit data |

### 5.2 Visual style (approximate, sampled by eye; refine from the design file)

| Item | Value |
|---|---|
| Sidebar background | Dark teal-blue `#27566B` |
| Page background | Light blue `#D9E9F2` (the poster uses a light-to-mid blue gradient; use flat colour in the app) |
| Card background | Near white `#F5FAFD`, radius 12-16 px, thin border, very light shadow |
| Primary text | Dark navy-teal `#1F4457` |
| Muted text | `#5F7F91` |
| Active menu pill | Light `#EAF3F8` text dark teal |
| Chart colours | Dark slate blue `#4F7A93`, light blue `#A9C3D3`, green `#4E9C86`, brown-orange `#C2784F` |
| Overview card accents | Green outline for normal cards, orange/red tint (`#FBEAE2`, border `#E8A98A`) for Out of Stock |
| Font | Rounded humanist sans (Nunito-like). Use `Nunito` via Google Fonts with a system fallback, or system fonts only if you want zero font download |
| Corner radius | Cards 12-16 px, inputs 8 px, buttons 8 px |
| Spacing | 8 px grid |

### 5.3 Layout rules
- Desktop: sidebar fixed at 15% (min 200 px, max 260 px), content scrolls independently; header fixed on top of content.
- Tablet: sidebar collapses to icons.
- Mobile: sidebar becomes a slide-in drawer opened by a menu button; cards stack in one column; tables turn into compact card lists.
- Page content max width about 1400 px.

### 5.4 Navigation structure (final)

```
Dashboard
Invoices
  - All Invoices
  - Create Invoice
  - Today Billings
  - Past Billings
Brokers
  - Broker Sales Performance
  - Broker Profiles (add / edit / deactivate)
Customers
  - Customer list and bill details
Inventory
  - Inventory Items
  - Product Catalog (company dropdown -> company items)
  - Stock Update (purchases, adjustments, stock take)
  - Companies (profiles, purchases, payments, dues, company-wise sales)
Orders
  - Purchase Items
  - Return Items
Sales
  - Sales Analysis
  - Broker Commissions
Reports
  - Weekly / Monthly / Quarterly / Annual
  - Item Min/Max Sold
  - (plus GST, P&L, dues, stock valuation: see 9.12)
Employees
  - Attendance
  - Salary
  - Employee Profiles (add / edit / deactivate)
Expenses
  - Rent, Power, Salaries, Miscellaneous (and custom categories)
Settings (bottom, above Logout)
  - Shop profile, GST, numbering, backups, import/export, audit log, password
Logout
```

The reference image also shows "Purchase", "Reporting" and "Support" items. These map to **Orders > Purchase Items**, **Reports** and (not needed for a one-owner app, so omitted).

### 5.5 Header behaviour
- **Shop logo + name:** loaded from settings. Clicking goes to Dashboard.
- **Calendar (date jump):** a small date picker. Choosing a date opens **Invoices > Past Billings filtered to that date** with a day summary strip (invoices count, sales, collected, profit). The shortcut keeps it a one-step action.
- **Global search:** one box searching product code/name, customer name/phone, broker name, invoice number, shade code. Results grouped (Products, Customers, Brokers, Invoices), top 5 each, with 300 ms debounce.
- **Create Invoice icon:** goes straight to the billing screen.
- **Previous day sales icon:** opens a small popover with yesterday's invoices count, total sales, collected amount and profit, plus a "View invoices" link.
- **Notification bell:** shows counts for out-of-stock/low-stock items, overdue customer dues, pending broker commission and any failed backup. Computed on request; no separate notifications table.
- **Theme toggle:** light/dark using CSS variables (delivered in the polish phase).
- **Profile name:** shows the owner's username; dropdown with Change Password and Logout.

### 5.6 Performance-oriented UI rules
- No animation libraries; only simple CSS transitions (hover, focus). No page transition animations.
- Charts are lazy loaded (only on Dashboard/Sales/Reports).
- Route-based code splitting.
- Initial JavaScript target below about 200 KB gzipped.
- Tables use server pagination (25 rows default); long dropdown lists use search-as-you-type, not loading everything.
- Skeleton placeholders (static grey blocks) instead of spinners where helpful.
