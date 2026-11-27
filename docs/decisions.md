# Decisions log

Record every approved change to the blueprint here (date, section, decision, reason).

   2026-10-31: API URLs standardised with a trailing slash (Django convention); blueprint paths without slash are equivalent.

   2026-10-31: API URLs end with a trailing slash; missing-slash requests return a clean 404.
2026-11-01: Invoice number includes the invoice date: PREFIX/YYMMDD/NNNN; serial runs through the financial year.
2026-11-02: T-102 produced four core migrations (plus 0005 constraint); squash at the end of Phase 1, before any real data exists.
2026-11-02: T-103: series_start_number applies only to the first INV series row ever created; later years start at 1.

2026-11-02: T-103 passed a two-round second-model review; bounded retry (5), validation before save, stored series prefix, invoice_prefix limited to 1-4 letters/digits and stored uppercase.
2026-11-02: A rolled-back transaction rolls the serial back too (no gap, no reuse of a committed number).

2026-11-03: T-105 idempotency record is written in the same transaction as the action; only 2xx responses are stored; unique per (user, key); a lock timeout returns 409 IDEMPOTENCY_IN_PROGRESS.
2026-11-03: Transaction-level advisory lock with a stable SHA-256 key from user id and key; the unique constraint stays the source of correctness; lock_timeout applies only to the lock and insert and is restored before the handler.
2026-11-03: Business tables also carry their own unique idempotency_key column (never purged).
2026-11-03: Database driver switched from psycopg2-binary to psycopg 3 (psycopg[binary] 3.2.4) as the blueprint specifies.

- 2026-11-13: T-202 Product: five required fields only; product_code uppercase, 1-40 chars, letters/digits/hyphen/slash; case-insensitive uniqueness and length/Upper(Trim) checks enforced by the database; pattern checked in code only.
- 2026-11-13: GST rate on a product is validated only when set or changed; a later-deactivated rate makes the product not billing-ready but does not block other edits.
- 2026-11-13: HSN format check: digits only, 2 to 8 digits (format only, no meaning).
- 2026-11-13: Products are never deleted (instance and queryset delete blocked); deactivate instead.
- 2026-11-13: CompanyService was damaged during T-202 and restored from the T-201 commit in T-202c; AGENTS.md now forbids rewriting files from memory and requires git --no-pager diff --stat at the end of each task.

- 2026-11-14: T-203 Products API: stock fields in request bodies are rejected, never ignored; stock changes only through stock operations (T-301).
- 2026-11-14: pack_size and pack_unit cannot change once a product has stock history (PACK_CHANGE_NOT_ALLOWED); has_stock_history is extended in T-301 to check movements.
- 2026-11-14: Duplicate product code returns DUPLICATE_PRODUCT_CODE on the field product_code; unapproved GST rate returns GST_RATE_NOT_APPROVED on the field gst_rate.
- 2026-11-14: Product search matches every term against product_code, labels and company name; wildcard characters match literally (Django icontains escapes them, regression-tested); trigram indexes on UPPER(column) created by migration 0004 and proven usable by EXPLAIN tests.
- 2026-11-14: pg_trgm is created with IF NOT EXISTS and is required (docs/deployment-notes.md); migration reverse drops only its indexes, never the extension.
- 2026-11-14: catalog.urls is mounted at api/v1/ with internal companies/ and products/ prefixes (company URLs unchanged).

- 2026-11-15: T-204 catalog endpoints are read-only; readiness reasons (selling_price, gst_rate, gst_rate_inactive, hsn_code) come from one source shared with the model; summary reason counts overlap by design.
- 2026-11-15: Company product_count counts ACTIVE products only; inactive products are counted separately.

## Phase 3
- 2026-11-16: T-301 stock ledger (StockMovement) is append-only in three layers: model, queryset and a PostgreSQL trigger (TRUNCATE allowed for test cleanup).
- 2026-11-16: StockService is the only code allowed to change Product.qty_on_hand, avg_buying_price and last_buying_price; movements take positive quantities and the service applies the sign by type; it runs inside the caller's transaction in its own savepoint and locks product rows ordered by id.
- 2026-11-16: For SALE and ADJ_OUT the movement unit_cost is the average before the movement (the cost snapshot); outflows never change the average.
- 2026-11-16: Products with track_stock false cannot move stock (STOCK_NOT_TRACKED); inactive products can (adjustments must work); billing refuses inactive products elsewhere.
- 2026-11-16: Product.save() on an existing row without update_fields saves only editable fields plus updated_at, and raises if update_fields names a stock field, so a stale copy can never overwrite stock.
- 2026-11-16: The stock-field write scan is AST-based, has its own self-tests and a minimal allowlist keyed by file and line text.
- 2026-11-16: PURCHASE, SALE_RETURN, CANCEL_REVERSAL, PURCHASE_RETURN and ADJ_IN raise CostingNotImplementedError until T-302 (weighted-average costing).
- 2026-11-27: T-302 weighted-average costing implemented in apps/stock/costing.py (pure functions: after_purchase, after_return, after_adjustment_in, after_sale, after_adjustment_out, after_purchase_return, stock_value); COSTING_PENDING_TYPES kept as a documented constant (referenced by TestCosting.test_pending_types_list) but no service path defers to it. (HISTORY in T-302b: COSTING_PENDING_TYPES and TestCosting.test_pending_types_list were removed; nothing defers to the constant.)
- 2026-11-27: PURCHASE, SALE_RETURN and CANCEL_REVERSAL require unit_cost (Decimal, >= 0, at most 4 decimals, rejected never rounded); ADJ_IN requires a reason, refuses unit_cost when an average exists and requires it to seed a null average; PURCHASE_RETURN unit_cost optional (None = value at current average).
- 2026-11-27: only PURCHASE sets last_buying_price; purchase into zero or negative stock takes the incoming cost; purchase return is provisional (valuation pending accountant approval 13.14) and rejects a negative remaining stock value.
- 2026-11-27: CostingNotImplementedError exception removed (nothing uses it after T-302).
- 2026-11-27: New read-only apps/stock/selectors.py with recompute_from_ledger() and verify_product_ledger(); no schema, OpenAPI, API or serializer change.
