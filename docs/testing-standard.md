# Testing standard

This document defines the single standard every new test in this repository
must follow. It is infrastructure only: it adds no behaviour to the
application.

## The four test kinds

Tests are grouped by kind, not by size. Each kind maps to a flat file suffix
inside the app package:

| Kind   | File suffix         | Purpose                                  | Database |
|--------|---------------------|------------------------------------------|----------|
| unit   | `test_<feature>_unit.py`   | Pure logic, no database (calc.py helpers, validators, costing) | No |
| db     | `test_<feature>_db.py`     | Model/service behaviour that needs the DB | Yes |
| api    | `test_<feature>_api.py`    | HTTP endpoint tests through the test client | Yes |
| concurrency | `test_<feature>_concurrency.py` | Threads, locks, deadlock-safe behaviour; slow | Yes |

`backend/acceptance/` holds cross-app gate tests that span more than one app
(for example a stock movement followed by a product API pack-change rejection).

Pure-logic tests are plain pytest functions with **no database**. pytest-django
will fail them if they touch the database, which enforces the boundary.

## File naming and layout

- Flat files named `test_<feature>_<kind>.py`, placed directly inside the app
  package (e.g. `apps/stock/test_stock_service_db.py`).
- About 500 lines per file maximum.
- About 60 lines per test maximum.
- One behaviour per test.
- Parametrise tables instead of copying tests.

## Markers

Every test file must have a module-level `pytestmark` line, for example:

```python
pytestmark = pytest.mark.db
```

Registered markers (see `backend/pytest.ini`):

- `unit` — pure logic, no database
- `db` — needs the database
- `api` — HTTP endpoint tests
- `concurrency` — threads or locks; slow
- `acceptance` — cross-app gate tests
- `slow` — slow-running tests

## Helpers

Use `backend/testsupport` factories (`make_company`, `make_product`,
`make_owner`, `approve_gst_rate`, `billing_ready_product`, `give_opening_stock`)
instead of building data by hand. Use the conftest fixtures (`owner_user`,
`api_client`, `auth_client`, `default_settings`) for API tests. `testsupport`
must never be imported by production code (`apps/`, `config/`, `common/`).

## Independence

Tests never depend on another test. Each test creates the data it needs and
leaves no data behind. Seeded rows (the single `AppSettings` row, pk=1, and the
`0.00` GST rate) come from migrations; if a `TransactionTestCase` flush removes
them, call `testsupport.factories.ensure_seed_data()` to recreate exactly those
two rows.

## Legacy test files

`apps/core/tests.py`, `apps/catalog/tests.py` and `apps/accounts/tests.py` are
legacy and will be split by a move-only task. Do not add new tests to them.

## Commands

Fast loop (excludes slow/acceptance/concurrency):

```
python -m pytest -m "not concurrency and not acceptance"
```

Single kind:

```
python -m pytest -m unit
python -m pytest -m db
```

Full run before every commit:

```
python -m pytest
```

## Stock field rule

`Product.qty_on_hand`, `avg_buying_price` and `last_buying_price` change only
through `StockService` in `apps/stock/services.py`. Every `Product.save()` in
an update path must pass explicit `update_fields`. Never write those fields
anywhere else, in code or tests, except by creating fixtures through
`StockService` or, where a test simulates stock history without the engine,
with a queryset update and a comment.
