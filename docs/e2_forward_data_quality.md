# E2 Forward Data Quality

The E2 forward dataset preserves original collection evidence.

Rules:
- Do not backfill missing hours.
- Do not synthesize rows.
- Do not overwrite historical forward rows.
- Do not change the `bybit_hourly.csv` schema.
- Report gaps through audit and health files.

Expected symbols exclude `FTMUSDT`.

Audit tools:
- `python scripts/e2_forward_health_check.py`
- `python scripts/e2_missing_hour_audit.py`

Generated health report:
- `data/forward/crypto_derivatives/e2_forward_health_report.txt`
