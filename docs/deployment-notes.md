# Deployment Notes

## Database extensions

The `pg_trgm` extension is required for trigram GIN indexes on product and company text fields (used by case-insensitive search and suggest endpoints).

### How to enable

The extension is installed automatically by migration `0004_product_trigram_indexes` using `CREATE EXTENSION IF NOT EXISTS pg_trgm;`. It can also be enabled manually:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

`pg_trgm` is a trusted extension in PostgreSQL 13 and later, so any database user with `CREATE` rights can install it.

### What happens if it is missing

Migration `0004_product_trigram_indexes` fails loudly if `pg_trgm` cannot be installed. There is no silent fallback: without the extension, trigram indexes cannot be created and case-insensitive trigram search will not be available.
