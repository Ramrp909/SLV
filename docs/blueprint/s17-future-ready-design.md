## 17. Future-Ready Design

You said more requirements will come later. The design keeps the cost of change low in these ways.

| Area | What is built in now | What it allows later |
|---|---|---|
| API-first | Every screen uses the same versioned REST API (`/api/v1`) with an auto-generated OpenAPI document | A native mobile app, a WhatsApp bot or an accountant tool can use the same API without backend changes |
| Versioning | New behaviour goes into `/api/v2` while v1 keeps working | Safe changes without breaking installed PWAs |
| Business rules in one place | All stock, GST, commission and numbering rules live in backend services (not in screens or database triggers) | Changing a rule means editing one service and its tests |
| Single stock entry point | All stock changes pass through one `StockService` | Adding branches or a godown later means extending this service and adding a stock location, with a documented migration |
| Users and roles | Login uses standard Django users and a central permission check; the shop runs with one owner now | Staff logins with limited permissions (billing only, view only) can be added without redesigning tables; audit log already records the actor |
| Custom fields | `custom_fields` (JSON) on products, customers, brokers and invoices | New information (warranty, vehicle number, site address) without a new table or migration |
| Settings in the database | Rates, rules, number formats and switches are settings, not code | Owner changes behaviour from the Settings screen |
| Controlled lists | Units, expense categories, payment modes are tables or lists | New unit or category without a release |
| Number series | Series table per document type and financial year | Quotation, delivery challan or purchase order series can be added |
| Import and export framework | One import wizard (validate, preview, commit) and one export layer | New Excel templates (customers, purchases, stock count) are configuration, not new screens |
| Background work slot | Imports, backups and reports run as simple commands today | A job queue (for email, WhatsApp, reminders) can be plugged in later |
| Document storage | Files (logo, backups, later invoice PDFs) go through a storage layer | Switch to S3, add attachments to purchases or expenses |
| Notifications | Alerts are computed by one notification service | Add WhatsApp or SMS reminders by adding a sender |
| Reports | Reports are defined as queries plus export, with date filters in one place | New reports are added quickly; heavy ones can use summary tables |
| Language | Screen texts are kept in one translation file | Telugu or other languages for screens and printed invoices later |
| Tests and migrations | Automated tests for money and stock logic; every database change is a versioned migration | Safe, repeatable changes |
| Monitoring and audit | Error tracking, uptime checks, append-only audit log | Faster diagnosis as the app grows |

**Likely future additions and where they would plug in:** staff logins (roles), quotations and estimates (new document type, same invoice engine), supplier purchase orders, branch or godown stock, WhatsApp invoice sharing, barcode scanning (the product code field already accepts scanner input), payment gateway or UPI QR on invoices, e-invoice integration, customer ledger statements by email, tinting machine records, and a native mobile app.
