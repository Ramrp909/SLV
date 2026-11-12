# Decisions log

Record every approved change to the blueprint here (date, section, decision, reason).

   2026-10-31: API URLs standardised with a trailing slash (Django convention); blueprint paths without slash are equivalent.

   2026-10-31: API URLs end with a trailing slash; missing-slash requests return a clean 404.
2026-11-01: Invoice number includes the invoice date: PREFIX/YYMMDD/NNNN; serial runs through the financial year.
2026-11-02: T-102 produced four core migrations (plus 0005 constraint); squash at the end of Phase 1, before any real data exists.
2026-11-02: T-103: series_start_number applies only to the first INV series row ever created; later years start at 1.

2026-11-02: T-103 passed a two-round second-model review; bounded retry (5), validation before save, stored series prefix, invoice_prefix limited to 1-4 letters/digits and stored uppercase.
2026-11-02: A rolled-back transaction rolls the serial back too (no gap, no reuse of a committed number).