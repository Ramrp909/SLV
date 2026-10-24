## 1. Project Overview and Scope

### 1.1 Business context
- The shop sells paints (company-branded products in tins/packs measured in litres).
- Customers who want to paint a house usually come through a **broker** (a paint worker/painter who brings customers to the shop).
- At the shop: product list is shown, price is **negotiated**, final bill is made, customer pays (fully or partly), work starts.
- The broker earns a **commission** on the final invoice amount, including GST, after all discounts (default 10-12%, variable per broker and per bill).
- The commission is **never printed on the customer invoice**. It is tracked only inside the app (broker section).

### 1.2 Users
- **One user only:** the shop owner (superadmin). No other logins, no registration, no roles.
- Customers, brokers and employees are **records** in the system, not users.

### 1.3 In scope
Login, dashboard, invoices (create, list, print), customers and dues, brokers and commissions, inventory (items, catalog, stock updates), purchases and returns, sales analysis, reports, employees (attendance, salary), expenses, GST on invoices, shade/colour codes, audit log, invoice numbering, backups, Excel import/export, settings.

### 1.4 Out of scope (version 1)
- Multi-user logins and roles
- Online ordering / e-commerce / customer portal
- Native mobile apps (a PWA is used instead)
- Payment gateway integration
- GST return filing, e-invoice (IRN) and e-way bill integration (the app provides GST summary exports for your accountant)
- Barcode hardware integration (the UI is kept barcode-ready: product code search field accepts scanner input)
