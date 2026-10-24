## 16. Diagrams

All diagrams below are written as **Mermaid** code, which draws pictures automatically in GitHub, GitLab, VS Code (Markdown preview), Notion, Obsidian and most Markdown viewers. The same diagrams are also supplied as separate image files (PNG) for viewers that do not draw Mermaid. Plain-text screen wireframes are included at the end.

### 16.1 System architecture

```mermaid
flowchart LR
    subgraph Client["Owner device: phone or computer"]
        UI["React PWA<br/>pages, forms, charts"]
        QC["TanStack Query cache"]
    end
    subgraph Server["Backend server: Django + DRF"]
        API["REST API /api/v1"]
        AUTH["Login, token check, throttling"]
        SVC["Business services<br/>stock, GST, commission, numbering"]
        XLS["Excel import and export"]
        AUD["Audit logger"]
    end
    DB[("PostgreSQL<br/>daily backups")]
    OBJ[("Object storage<br/>backup files, logo")]
    MON["Sentry and uptime monitor"]

    UI --> QC --> API
    API --> AUTH --> SVC
    SVC --> DB
    XLS --> DB
    SVC --> AUD --> DB
    DB -. nightly dump .-> OBJ
    API -. errors .-> MON
```

### 16.2 Deployment view

```mermaid
flowchart TB
    OWNER["Owner: browser or installed PWA"]
    subgraph Vercel["Vercel"]
        FE["Static React build"]
    end
    subgraph AWS["AWS or Render/Railway"]
        NGINX["Nginx + HTTPS"]
        GUN["Gunicorn + Django"]
        RDS[("Managed PostgreSQL<br/>backups, point-in-time recovery")]
        S3[("S3 backup bucket")]
    end
    CI["GitHub Actions<br/>lint, test, build, deploy"]

    OWNER -->|"opens app"| FE
    OWNER -->|"API calls, JSON over HTTPS"| NGINX
    NGINX --> GUN --> RDS
    RDS -. encrypted backups .-> S3
    CI --> FE
    CI --> GUN
```

### 16.3 Site map (menus and pages)

```mermaid
flowchart LR
    LOGIN["Login"] --> DASH["Dashboard"]
    DASH --> INV["Invoices"]
    DASH --> BRK["Brokers"]
    DASH --> CUS["Customers"]
    DASH --> STK["Inventory"]
    DASH --> ORD["Orders"]
    DASH --> SAL["Sales"]
    DASH --> REP["Reports"]
    DASH --> EMP["Employees"]
    DASH --> EXP["Expenses"]
    DASH --> SET["Settings"]

    INV --> I1["All Invoices"]
    INV --> I2["Create Invoice"]
    INV --> I3["Today Billings"]
    INV --> I4["Past Billings"]
    BRK --> B1["Broker Sales Performance"]
    BRK --> B2["Broker Profiles"]
    CUS --> C1["Customer list and bills"]
    STK --> S1["Inventory Items"]
    STK --> S2["Product Catalog"]
    STK --> S3["Stock Update and Stock Take"]
    STK --> S4["Companies"]
    ORD --> O1["Purchase Items"]
    ORD --> O2["Return Items"]
    SAL --> A1["Sales Analysis"]
    SAL --> A2["Broker Commissions"]
    REP --> R1["Weekly, monthly, quarterly, annual"]
    REP --> R2["Item min and max sold"]
    REP --> R3["P and L, GST, dues, stock sheet"]
    EMP --> E1["Attendance"]
    EMP --> E2["Salary"]
    EMP --> E3["Employee Profiles"]
    EXP --> X1["Rent, Power, Salaries, Misc"]
    SET --> T1["Shop, GST, numbering, import, backups, audit log"]
```

### 16.4 Data flow diagram, level 0 (who talks to the system)

```mermaid
flowchart LR
    CUST["Customer"]
    BROK["Broker"]
    COMP["Companies: suppliers"]
    ACC["Accountant"]
    OWN["Owner: only user"]
    SYS(("Paint Shop<br/>Management<br/>System"))

    OWN -->|"products, purchases, bills, payments, expenses, settings"| SYS
    SYS -->|"dashboard, reports, alerts"| OWN
    CUST -->|"order and payment"| SYS
    SYS -->|"printed invoice, receipt, statement"| CUST
    BROK -->|"brings customer"| SYS
    SYS -->|"commission statement and payout"| BROK
    COMP -->|"supply bills and stock"| SYS
    SYS -->|"payments to company"| COMP
    SYS -->|"GST summary, P and L in Excel"| ACC
```

### 16.5 Data flow diagram, level 1 (processes and data stores)

```mermaid
flowchart LR
    OWN["Owner"]
    CUST["Customer"]
    COMP["Company"]

    P1("1 Product and stock<br/>management")
    P2("2 Purchases and<br/>company dues")
    P3("3 Billing and GST")
    P4("4 Payments and<br/>customer dues")
    P5("5 Commission<br/>calculation and payout")
    P6("6 Returns and<br/>cancellations")
    P7("7 Employees<br/>and expenses")
    P8("8 Dashboard<br/>and reports")

    D1[("D1 Products and<br/>stock movements")]
    D2[("D2 Purchases and<br/>company payments")]
    D3[("D3 Invoices<br/>and items")]
    D4[("D4 Customer<br/>payments")]
    D5[("D5 Commissions<br/>and payouts")]
    D6[("D6 Employees,<br/>salaries, expenses")]
    D7[("D7 Audit log")]

    OWN -->|"item details, Excel file"| P1 --> D1
    COMP -->|"supply bills"| P2
    OWN -->|"purchase entry, company payment"| P2
    P2 --> D2
    P2 -->|"stock in, new average cost"| D1
    CUST -->|"order"| P3
    OWN -->|"prices, discount, broker"| P3
    D1 -->|"stock, default prices"| P3
    P3 -->|"invoice"| D3
    P3 -->|"stock out, cost snapshot"| D1
    P3 --> P5
    P5 --> D5
    CUST -->|"payment"| P4
    P4 --> D4
    D3 -->|"balance due"| P4
    OWN -->|"return or cancel"| P6
    D3 --> P6
    P6 -->|"stock back"| D1
    P6 -->|"commission reversed"| D5
    OWN -->|"attendance, salary, expenses"| P7 --> D6
    D1 --> P8
    D2 --> P8
    D3 --> P8
    D4 --> P8
    D5 --> P8
    D6 --> P8
    P8 -->|"charts, reports, Excel"| OWN
    P1 -.-> D7
    P3 -.-> D7
    P6 -.-> D7
```

### 16.6 Entity relationship diagram: trading core

```mermaid
erDiagram
    COMPANIES ||--o{ PRODUCTS : "supplies"
    PRODUCTS ||--o{ STOCK_MOVEMENTS : "has"
    COMPANIES ||--o{ PURCHASES : "sells to shop"
    PURCHASES ||--|{ PURCHASE_ITEMS : "contains"
    PRODUCTS ||--o{ PURCHASE_ITEMS : "bought as"
    COMPANIES ||--o{ COMPANY_PAYMENTS : "is paid by"
    CUSTOMERS ||--o{ INVOICES : "buys"
    BROKERS |o--o{ INVOICES : "refers"
    INVOICES ||--|{ INVOICE_ITEMS : "contains"
    PRODUCTS |o--o{ INVOICE_ITEMS : "sold as, empty for manual lines"
    INVOICES ||--o{ PAYMENTS : "paid by"
    CUSTOMERS ||--o{ RECEIPTS : "pays through"
    RECEIPTS ||--|{ PAYMENTS : "allocated as"
    COMMISSIONS ||--o{ COMMISSION_ADJUSTMENTS : "reduced by"
    INVOICES ||--o| COMMISSIONS : "earns"
    BROKERS ||--o{ COMMISSIONS : "receives"
    BROKERS ||--o{ BROKER_PAYOUTS : "paid by"
    BROKER_PAYOUTS ||--o{ BROKER_PAYOUT_ITEMS : "allocates"
    COMMISSIONS ||--o{ BROKER_PAYOUT_ITEMS : "settled by"
    INVOICES ||--o{ SALES_RETURNS : "returned through"
    SALES_RETURNS ||--|{ SALES_RETURN_ITEMS : "contains"
    INVOICE_ITEMS ||--o{ SALES_RETURN_ITEMS : "returned as"

    COMPANIES {
        bigint id PK
        string name UK
        string gstin
        boolean is_local
        boolean is_active
    }
    PRODUCTS {
        bigint id PK
        string product_code UK
        bigint company_id FK
        string category
        string product_type
        string sub_type
        string sub_sub_type
        decimal pack_size
        string pack_unit
        decimal qty_on_hand
        decimal avg_buying_price
        decimal selling_price
        decimal gst_rate
        string hsn_code
        decimal min_stock
        boolean track_stock
        boolean is_active
        json custom_fields
    }
    STOCK_MOVEMENTS {
        bigint id PK
        bigint product_id FK
        string movement_type
        decimal quantity
        decimal unit_cost
        decimal qty_after
        decimal avg_cost_after
        string reference_type
        bigint reference_id
        date movement_date
    }
    PURCHASES {
        bigint id PK
        string purchase_no UK
        bigint company_id FK
        string supplier_invoice_no
        date purchase_date
        decimal grand_total
        decimal paid_amount
    }
    COMPANY_PAYMENTS {
        bigint id PK
        bigint company_id FK
        bigint purchase_id FK
        decimal amount
        date payment_date
        string mode
    }
    CUSTOMERS {
        bigint id PK
        string name
        string phone
        string gstin
        string state
        decimal opening_balance
        boolean is_active
    }
    BROKERS {
        bigint id PK
        string name
        string phone
        decimal default_commission_percent
        boolean is_active
    }
    INVOICES {
        bigint id PK
        string invoice_no UK
        date invoice_date
        bigint customer_id FK
        bigint broker_id FK
        string status
        decimal subtotal
        decimal discount_amount
        decimal taxable_total
        decimal cgst_total
        decimal sgst_total
        decimal igst_total
        decimal round_off
        decimal grand_total
        decimal paid_amount
        decimal balance_due
        decimal commission_percent
        decimal commission_amount
        decimal gross_profit
        decimal profit_after_commission
        boolean profit_complete
        boolean is_backdated
    }
    INVOICE_ITEMS {
        bigint id PK
        bigint invoice_id FK
        bigint product_id FK
        boolean is_manual
        string description
        string shade_code
        decimal quantity
        decimal selling_price
        decimal gst_rate
        decimal taxable_value
        decimal cost_snapshot
        decimal line_profit
    }
    PAYMENTS {
        bigint id PK
        bigint invoice_id FK
        bigint receipt_id FK
        decimal amount
        date payment_date
        string mode
    }
    RECEIPTS {
        bigint id PK
        string receipt_no UK
        string idempotency_key UK
        bigint customer_id FK
        decimal total_amount
        date receipt_date
    }
    COMMISSIONS {
        bigint id PK
        bigint invoice_id FK
        bigint broker_id FK
        decimal percent
        decimal base_amount
        decimal amount
        decimal adjusted_amount
        decimal paid_amount
        string status
    }
    COMMISSION_ADJUSTMENTS {
        bigint id PK
        bigint commission_id FK
        string source_type
        bigint source_id
        decimal amount
    }
    BROKER_PAYOUTS {
        bigint id PK
        bigint broker_id FK
        decimal amount
        date payout_date
    }
    BROKER_PAYOUT_ITEMS {
        bigint id PK
        bigint payout_id FK
        bigint commission_id FK
        decimal amount
    }
    PURCHASE_ITEMS {
        bigint id PK
        bigint purchase_id FK
        bigint product_id FK
        decimal quantity
        decimal unit_price
        decimal taxable_value
        decimal gst_rate
        decimal recoverable_gst
        decimal non_recoverable_gst
        decimal inventory_cost_per_unit
        decimal avg_before
        decimal avg_after
    }
    SALES_RETURNS {
        bigint id PK
        string return_no UK
        bigint invoice_id FK
        date return_date
        decimal total
    }
    SALES_RETURN_ITEMS {
        bigint id PK
        bigint return_id FK
        bigint invoice_item_id FK
        decimal quantity
        decimal line_total
    }
```

### 16.7 Entity relationship diagram: supporting tables

```mermaid
erDiagram
    EMPLOYEES ||--o{ ATTENDANCE : "marked daily"
    EMPLOYEES ||--o{ SALARIES : "paid monthly"
    SALARIES |o--o| EXPENSES : "creates expense when paid"
    EXPENSE_CATEGORIES ||--o{ EXPENSES : "groups"
    EXPENSE_CATEGORIES ||--o{ RECURRING_EXPENSES : "groups"
    STOCK_TAKES ||--|{ STOCK_TAKE_ITEMS : "contains"
    PRODUCTS ||--o{ STOCK_TAKE_ITEMS : "counted"
    PRODUCTS ||--o{ STOCK_SNAPSHOTS : "month-end value"
    USERS ||--o{ AUDIT_LOG : "actions recorded"

    EMPLOYEES {
        bigint id PK
        string name
        decimal base_salary
        date joining_date
        boolean is_active
    }
    ATTENDANCE {
        bigint id PK
        bigint employee_id FK
        date attendance_date
        string status
    }
    SALARIES {
        bigint id PK
        bigint employee_id FK
        string month
        decimal net_payable
        string status
        bigint expense_id FK
    }
    EXPENSE_CATEGORIES {
        bigint id PK
        string name UK
    }
    EXPENSES {
        bigint id PK
        bigint category_id FK
        decimal amount
        date expense_date
        string source
    }
    RECURRING_EXPENSES {
        bigint id PK
        bigint category_id FK
        decimal amount
        int day_of_month
    }
    STOCK_TAKES {
        bigint id PK
        string take_no UK
        date take_date
        string status
    }
    STOCK_TAKE_ITEMS {
        bigint id PK
        bigint take_id FK
        bigint product_id FK
        decimal system_qty
        decimal counted_qty
    }
    STOCK_SNAPSHOTS {
        bigint id PK
        date snapshot_date
        bigint product_id FK
        decimal qty
        decimal avg_cost
    }
    USERS {
        bigint id PK
        string username UK
        boolean is_active
    }
    AUDIT_LOG {
        bigint id PK
        datetime timestamp
        string action
        string entity_type
        bigint entity_id
        json before_json
        json after_json
    }
    APP_SETTINGS {
        bigint id PK
        string shop_name
        string gstin
        boolean prices_include_gst
        boolean purchase_gst_recoverable_default
    }
    GST_RATES {
        bigint id PK
        decimal rate UK
        boolean is_active
    }
    NUMBER_SERIES {
        bigint id PK
        string series_code
        string financial_year
        int last_number
    }
    IMPORT_JOBS {
        bigint id PK
        string entity
        string status
        int total_rows
        int error_rows
    }
    BACKUP_LOG {
        bigint id PK
        string backup_type
        string status
    }
```

### 16.8 Invoice creation flow (what happens on the billing screen)

```mermaid
flowchart TD
    A(["Owner opens Create Invoice"]) --> B["Choose or add customer"]
    B --> C["Choose broker, optional"]
    C --> C2{"Invoice date OK?"}
    C2 -->|"Future date"| C3["Blocked"] --> C
    C2 -->|"Today or past"| D["Add item rows"]
    D --> E{"Product from list<br/>or manual line?"}
    E -->|"Product code search"| F0{"Product has price,<br/>GST rate and HSN?"}
    F0 -->|"No"| F1["Cannot add: needs details first"] --> D
    F0 -->|"Yes"| F["Fill GST-inclusive default price,<br/>GST rate, stock shown"]
    E -->|"Manual line, empty row"| G["Type description, quantity, price,<br/>GST rate, optional internal cost"]
    F --> H{"Quantity more<br/>than stock?"}
    H -->|"Yes"| H1["Block, or warn if<br/>negative stock allowed"] --> D
    H -->|"No"| I
    G --> I["Edit selling price per line"]
    I --> J{"Price below cost?"}
    J -->|"Yes"| J1["Show warning"] --> K
    J -->|"No"| K["Apply discount: percent or amount"]
    K --> L["Preview GST per line, round-off, grand total"]
    L --> M["Enter payment received and mode"]
    M --> M2{"Payment more than<br/>grand total?"}
    M2 -->|"Yes"| M3["Blocked: payment exceeds amount due"] --> M
    M2 -->|"No"| N["Owner-only panel: commission percent override<br/>and profit preview"]
    N --> O["Save"]
    O --> P["Server validates and recalculates everything,<br/>ignores any client totals"]
    P --> Q{"All checks OK?"}
    Q -->|"No"| Q1["Show errors on the form"] --> D
    Q -->|"Yes"| R["Atomic save: number, invoice, items with snapshots,<br/>stock out, payment, commission on grand total, audit"]
    R --> S(["Print copy A4: no commission,<br/>no cost, no profit"])
```

### 16.9 Invoice save: sequence between screen, server and database

```mermaid
sequenceDiagram
    autonumber
    actor Owner
    participant UI as React screen
    participant API as Django API
    participant SVC as Billing service
    participant DB as PostgreSQL

    Owner->>UI: Press Save
    UI->>API: POST /invoices with idempotency key
    API->>API: Check login token
    API->>SVC: create_invoice(data)
    SVC->>DB: BEGIN transaction
    SVC->>DB: Lock product rows in fixed order
    SVC->>DB: Next invoice number from locked counter
    SVC->>SVC: Recalculate discount, GST per line, totals, commission from grand total, profit
    SVC->>DB: Insert invoice and items with cost snapshots
    SVC->>DB: Insert stock movements, reduce quantities
    SVC->>DB: Insert payment and commission
    SVC->>DB: Insert audit entry
    SVC->>DB: COMMIT
    SVC-->>API: Saved invoice
    API-->>UI: 201 with final totals
    UI-->>Owner: Show invoice, Print button
    Note over SVC,DB: Any failure rolls back everything
```

### 16.10 Purchase and weighted average cost

```mermaid
flowchart TD
    A(["Owner enters purchase: company, bill no, items"]) --> B["For each item: quantity, unit price excluding GST, GST rate"]
    B --> B2["Split GST: recoverable or non-recoverable<br/>store tax details separately"]
    B2 --> B3["Inventory cost per unit =<br/>(taxable value + non-recoverable GST) / quantity"]
    B3 --> C["Read current quantity and average inventory cost<br/>with the product row locked"]
    C --> D{"Current quantity is 0?"}
    D -->|"Yes"| E["New average = line inventory cost"]
    D -->|"No"| F["New average = (old qty x old avg + new qty x line cost)<br/>divided by (old qty + new qty)"]
    E --> G["Write stock movement: PURCHASE"]
    F --> G
    G --> H["Update product quantity and average"]
    H --> I["Add purchase grand total, including GST, to company dues"]
    I --> J["Write audit entry"]
    J --> K(["Show new average per product"])
```

### 16.11 Sales return and invoice cancellation

```mermaid
flowchart TD
    A(["Owner opens an invoice"]) --> B{"Return some items<br/>or cancel whole invoice?"}
    B -->|"Return"| C["Pick items and quantities"]
    C --> D{"Quantity within sold minus<br/>already returned?"}
    D -->|"No"| D1["Show error"] --> C
    D -->|"Yes"| E["Calculate returned taxable value and GST"]
    B -->|"Cancel"| F["Enter reason, mandatory"]
    F --> E2["All items count as returned"]
    E --> G["Stock goes back at the original cost snapshot"]
    E2 --> G
    G --> H["Reduce commission = rate x credit note total"]
    H --> I{"Broker already paid<br/>more than new commission?"}
    I -->|"Yes"| I1["Broker balance shows a negative amount"]
    I -->|"No"| J
    I1 --> J["Issue credit note number, or mark invoice CANCELLED<br/>number is never reused"]
    J --> K["Refund customer or reduce balance due"]
    K --> L(["Audit entry written"])
```

### 16.12 Status life cycles

```mermaid
stateDiagram-v2
    [*] --> UNPAID : invoice saved, no payment
    [*] --> PAID : invoice saved, paid in full
    UNPAID --> PARTIAL : part payment received
    PARTIAL --> PAID : balance received
    UNPAID --> PAID : full payment received
    UNPAID --> CANCELLED : cancelled with reason
    PARTIAL --> CANCELLED : cancelled with reason
    PAID --> CANCELLED : cancelled with reason
    CANCELLED --> [*]
    PAID --> [*]
```

```mermaid
stateDiagram-v2
    [*] --> PENDING : invoice with broker saved
    PENDING --> PARTIAL : part payout
    PARTIAL --> PAID : rest paid
    PENDING --> PAID : full payout
    PENDING --> REVERSED : invoice cancelled
    PARTIAL --> REVERSED : invoice cancelled
    PAID --> [*]
    REVERSED --> [*]
```

### 16.13 Excel import flow (product and opening stock)

```mermaid
flowchart TD
    A(["Owner fills the Excel template"]) --> B["Upload in Settings, Import"]
    B --> C["Server reads the file"]
    C --> D{"Headers and sheet<br/>match the template?"}
    D -->|"No"| D1["Reject with message"] --> A
    D -->|"Yes"| E["Check every row: required fields, units,<br/>numbers, duplicate codes, approved GST rate"]
    E --> F{"Any errors?"}
    F -->|"Yes"| G["Show row-wise errors, download error report"] --> A
    F -->|"No"| H["Preview: new products, updated products,<br/>new companies, warnings"]
    H --> I{"Owner confirms?"}
    I -->|"No"| A
    I -->|"Yes"| J["One transaction: create new companies and products,<br/>opening stock movements, update existing master data"]
    J --> K["Save import record and audit entry"]
    K --> L(["Done: summary of rows created and updated"])
```

### 16.14 API map

```mermaid
flowchart LR
    ROOT["/api/v1"]
    ROOT --> AU["/auth<br/>login, refresh, logout, change-password, me"]
    ROOT --> SE["/settings, /audit-log,<br/>/notifications, /search, /backups"]
    ROOT --> CO["/companies<br/>CRUD, ledger, payments"]
    ROOT --> PR["/products<br/>CRUD, lookup, suggest, deactivate"]
    ROOT --> ST["/stock<br/>movements, adjustments, takes, valuation"]
    ROOT --> PU["/purchases, /purchase-returns"]
    ROOT --> CU["/customers<br/>CRUD, receive-payment, statement"]
    ROOT --> BR["/brokers<br/>CRUD, ledger, payouts, performance"]
    ROOT --> IV["/invoices<br/>create, list, detail, print, cancel,<br/>payments, returns, day-summary"]
    ROOT --> CM["/commissions, /sales"]
    ROOT --> DA["/dashboard, /reports/..."]
    ROOT --> HR["/employees, /attendance, /salaries"]
    ROOT --> EX["/expenses, /expense-categories,<br/>/recurring-expenses"]
    ROOT --> IM["/import/entity<br/>template, validate, commit"]
```

### 16.15 Login and token refresh

```mermaid
sequenceDiagram
    autonumber
    actor Owner
    participant UI as React app
    participant API as Django API
    participant DB as PostgreSQL

    Owner->>UI: Enter username and password
    UI->>API: POST /auth/login
    API->>DB: Check password and failed-attempt count
    alt Wrong password or locked
        API-->>UI: Error message (generic)
    else Correct
        API-->>UI: Access token in body, refresh token in secure cookie
        UI->>UI: Keep access token in memory only
    end
    Owner->>UI: Use the app
    UI->>API: Request with access token
    alt Token expired (401)
        UI->>API: POST /auth/refresh with cookie
        API-->>UI: New access token
        UI->>API: Repeat the original request
    end
    API-->>UI: Data
```

### 16.16 Roadmap timeline (single developer, about 20 weeks)

```mermaid
gantt
    title Build roadmap (illustrative start 2 Nov 2026, single developer)
    dateFormat  YYYY-MM-DD
    axisFormat  %d %b
    tickInterval 2week
    todayMarker off
    section Setup
    0 Discovery and design           :p0, 2026-11-02, 7d
    1 Foundation                     :p1, after p0, 11d
    section Inventory
    2 Inventory master and Excel import :p2, after p1, 18d
    3 Purchases, companies, stock engine :p3, after p2, 14d
    section Parties
    4 Customers and brokers          :p4, after p3, 7d
    section Billing
    5 Billing core                   :p5, after p4, 21d
    6 Payments, dues, returns        :p6, after p5, 11d
    7 Commissions and broker ranking :p7, after p6, 7d
    section Insight
    8 Dashboard and sales analysis   :p8, after p7, 11d
    9 Reports, stock take, exports   :p9, after p8, 14d
    section Operations
    10 Employees and expenses        :p10, after p9, 11d
    11 Hardening and go-live         :p11, after p10, 14d
```

### 16.17 Screen wireframes (plain text)

**Overall layout (about 15% menu, 85% content)**

```
+----------------+--------------------------------------------------------------------+
| [Logo] SHOP    |  [Logo] Shop name   [Calendar]  [ Search........ ]  [+Invoice]     |
| NAME           |                                   [Yesterday] [Bell] [Theme] [Ram] |
+----------------+--------------------------------------------------------------------+
| Dashboard      |                                                                    |
| Invoices     > |                                                                    |
| Brokers      > |                  PAGE CONTENT (85%)                                |
| Customers      |                                                                    |
| Inventory    > |                                                                    |
| Orders       > |                                                                    |
| Sales        > |                                                                    |
| Reports      > |                                                                    |
| Employees    > |                                                                    |
| Expenses       |                                                                    |
| Settings       |                                                                    |
| Logout         |                                                                    |
+----------------+--------------------------------------------------------------------+
```

**Dashboard (as in the reference image)**

```
+--------------------------------------------------------------------+
| Overview                                                           |
| [Total Products] [Invoices] [Total Stock value] [Out of Stock (i)] |
+--------------------------------------------------------------------+
| [Total Customers] | [Pie: sold vs remaining stock] | [Top 10 Brokers] |
+-------------------+--------------------------------+  (bar list)     |
| [Expense vs Profit, last 6 months (area chart)]    |                 |
+----------------------------------------------------+-----------------+
| Optional strip: Today's sales | Today's profit | Customer dues | Commission pending |
+--------------------------------------------------------------------+
```

**Create Invoice**

```
+--------------------------------------------------------------------+
| Invoice No: Auto    Date: [23-10-2026]   Place of supply: [Telangana]|
| Customer: [search or + new......]     Broker: [search, optional.....]|
+--------------------------------------------------------------------+
| Code        | Item details         | Shade | Qty | Price | Disc | GST | Total |
| [type code] | company / type / sub | [   ] | [ ] | [ ]   | [ ]  | 18  | 0.00  |
| [type code] | ...                                                    |
| [manual line: description .......] | [ ] | [price] | [GST] | [cost?] |
| [+ add row]                                                         |
+---------------------------------------+----------------------------+
| Notes (internal)                      | Subtotal            0.00   |
|                                       | Discount  [% or Rs] 0.00   |
| OWNER ONLY (never printed)            | Taxable             0.00   |
| Broker commission %: [10]  Amount 0   | CGST / SGST         0.00   |
| Expected profit 0   After commission 0| Round-off           0.00   |
|                                       | GRAND TOTAL         0.00   |
| Payment received: [____] Mode: [Cash] | Balance due         0.00   |
+---------------------------------------+----------------------------+
|        [ Save ]    [ Save and Print ]    [ Save and New ]           |
+--------------------------------------------------------------------+
```
