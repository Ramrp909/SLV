## 10. Roadmap

Estimates assume one full-stack developer (about 19 weeks in the first version, about 20 to 21 weeks after the v3 additions in 15.9; the Gantt chart is in 16.16) or two developers, frontend and backend in parallel (about 11-13 weeks). The order delivers a usable inventory entry tool first, as you asked.

| Phase | Name | Duration |
|---|---|---|
| 0 | Discovery and design | 1 week |
| 1 | Foundation | 1.5 weeks |
| 2 | Inventory master (**first usable release**) | 2 weeks |
| 3 | Purchases and stock engine | 1.5 weeks |
| 4 | Customers and brokers | 1 week |
| 5 | Billing core | 3 weeks |
| 6 | Payments, dues, returns, cancellations | 1.5 weeks |
| 7 | Commissions and broker performance | 1 week |
| 8 | Dashboard and sales analysis | 1.5 weeks |
| 9 | Reports and Excel import/export | 1.5 weeks |
| 10 | Employees and expenses | 1.5 weeks |
| 11 | Hardening, UAT, go-live | 2 weeks |

### Phase 0: Discovery and design (1 week)
| Track | Work |
|---|---|
| Backend | Confirm open items (Section 13), finalise ER diagram and API contract, set up repository, environments, CI |
| Frontend | Convert the reference image into design tokens (colours, fonts, radius), build a static mock of shell, dashboard and billing screen for sign-off, repository and CI |
| Database | Finalise schema, naming, constraints, seed list |
| Done when | Written sign-off on open items, schema and screen mocks |

### Phase 1: Foundation (1.5 weeks)
| Track | Work |
|---|---|
| Backend | Django project, single owner login, JWT with refresh, throttling, settings model and API, number series service, audit log service, error format, pagination base |
| Frontend | Vite app, routing, login page, shell (15% menu, header, search placeholder, calendar placeholder), API client with token refresh, shared components (table, inputs, toast) |
| Database | Users, settings, number_series, audit_log, migrations, seed |
| Done when | Owner can log in, see the empty shell, and every change is audited |

### Phase 2: Inventory master (2 weeks) **First release**
| Track | Work |
|---|---|
| Backend | Companies and products CRUD, uniqueness, lookup and autocomplete endpoints, opening stock movement, deactivate, product import (validate/commit), export |
| Frontend | Inventory Items list with filters, **Add/Edit item screen**, Product Catalog (company dropdown), Excel import wizard, item detail |
| Database | companies, products, stock_movements, import_jobs, trigram indexes |
| Done when | You can enter and import all your inventory items and search by product code instantly |

### Phase 3: Purchases and stock engine (1.5 weeks)
| Track | Work |
|---|---|
| Backend | Stock engine (weighted average, row locking, movements), purchases, purchase returns, adjustments, concurrency tests |
| Frontend | Stock Update screen, Purchase Items list and form, adjustment form, return to company, movement history |
| Database | purchases, purchase_items, purchase_returns (+items), constraints |
| Done when | Your 10 at 300 plus 10 at 400 example yields 350, and tests prove stock never goes wrong under parallel saves |

### Phase 4: Customers and brokers (1 week)
| Track | Work |
|---|---|
| Backend | Customers and brokers CRUD, deactivation, import, search |
| Frontend | Customer list/detail shell, Broker Profiles add/edit/deactivate, inline new-customer dialog |
| Database | customers, brokers |
| Done when | All customers and brokers can be added and found quickly |

### Phase 5: Billing core (3 weeks)
| Track | Work |
|---|---|
| Backend | Invoice calculation service (discount allocation, GST inclusive/exclusive, CGST/SGST/IGST, rounding), atomic invoice creation, cost snapshots, commission record, invoice numbering, idempotency, print serializer without commission, day summary |
| Frontend | **Create Invoice screen**, invoice list (All/Today/Past), invoice view, print layout, header calendar jump, previous-day popover |
| Database | invoices, invoice_items, commissions, payments (initial payment), indexes |
| Done when | A full invoice with GST, discount, shade code and broker saves correctly; printed copy shows no commission; totals match the worked examples |

### Phase 6: Payments, dues, returns, cancellations (1.5 weeks)
| Track | Work |
|---|---|
| Backend | Add payments, receive-payment splitting, customer statement, sales returns with credit note numbers, invoice cancellation, commission reversal |
| Frontend | Add payment dialog, customer detail with dues and Receive payment, return and cancel flows with effect preview, WhatsApp reminder link |
| Database | sales_returns (+items), payment receipt groups |
| Done when | Partial payments, returns and cancellations keep stock, dues and commission consistent |

### Phase 7: Commissions and broker performance (1 week)
| Track | Work |
|---|---|
| Backend | Commission listing, payouts with allocation, broker ledger, performance ranking endpoints |
| Frontend | Broker detail ledger, record payout, Sales Performance page with ranking and chart, Sales > Broker Commissions |
| Database | broker_payouts, broker_payout_items |
| Done when | You can see per broker: bills, sales, profit, commission earned, paid and pending, by quarter and year |

### Phase 8: Dashboard and sales analysis (1.5 weeks)
| Track | Work |
|---|---|
| Backend | Aggregated dashboard endpoint with short cache, notifications endpoint, sales analysis queries |
| Frontend | Dashboard exactly as the reference image (cards, pie, top 10 brokers, expense vs profit), bell, Sales Analysis page |
| Database | Query tuning, additional indexes, summary view only if needed |
| Done when | Dashboard loads in under about a second with real data and matches the reference layout |

### Phase 9: Reports and Excel import/export (1.5 weeks)
| Track | Work |
|---|---|
| Backend | Period reports, item min/max, P&L, GST summary, dues ageing, stock valuation, Excel exports for every list/report, imports for customers, brokers, employees, opening stock |
| Frontend | Reports pages with filters and charts, export buttons, import wizards |
| Database | Report indexes, export performance check |
| Done when | Weekly/monthly/quarterly/annual reports and item min/max reconcile with invoice totals |

### Phase 10: Employees and expenses (1.5 weeks)
| Track | Work |
|---|---|
| Backend | Employees, attendance (bulk), salary calculation and payment, expenses, categories, recurring templates, auto salary expense |
| Frontend | Employee profiles, attendance screen and monthly grid, salary screen, expenses with category totals, recurring prompts |
| Database | employees, attendance, salaries, expenses, expense_categories, recurring_expenses |
| Done when | Salary paid appears as an expense, and expenses feed Net Profit and the dashboard chart |

### Phase 11: Hardening, UAT, go-live (2 weeks)
| Track | Work |
|---|---|
| Backend | Security review, throttling checks, load test with realistic data, backup automation and restore test, monitoring, production deployment, data migration scripts |
| Frontend | PWA install, mobile layout polish, dark theme toggle, accessibility basics, bundle size check, cross-browser check |
| Database | Production tuning, backup retention, restore drill, final data load (items, customers, brokers, opening dues) |
| Done when | User acceptance sign-off, a restore drill passes, owner trained, handover document delivered |

> **v4 note:** for AI-assisted development the phases above are broken into small build, run and test tasks in Section 18 and in `ai-build-task-planner.md`, with backend and database first and the frontend last.

### Milestones
- **M1 (end of Phase 2):** inventory entry and import usable
- **M2 (end of Phase 5):** billing usable (shop can start invoicing)
- **M3 (end of Phase 7):** dues and broker commissions complete
- **M4 (end of Phase 11):** full go-live
