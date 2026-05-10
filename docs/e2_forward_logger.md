# E2 Forward Logger

Layer 1 derivatives forward logging for QuantCore. This is data infrastructure only:
no signals, no strategy logic, no V12 integration, no execution, and no backtest.

## Scope

The logger records hourly public derivatives snapshots for the 19 non-BTC
QuantCore symbols:

`ADA_USDT, APT_USDT, ARB_USDT, AVAX_USDT, BCH_USDT, BNB_USDT, DOGE_USDT,
DOT_USDT, ETH_USDT, FTM_USDT, LINK_USDT, LTC_USDT, NEAR_USDT, OP_USDT,
POL_USDT, SOL_USDT, SUI_USDT, TRX_USDT, XRP_USDT`.

`config.py` is checked first. If its non-BTC symbols exactly match this set,
it is treated as the source of truth. If not, the logger uses the Claude-approved
E2 universe and prints the mismatch.

## Data

Primary mode uses Bybit public linear ticker data:

- Funding rate
- Open interest
- Open interest value when provided
- Mark price
- Index price
- Premium absolute and percentage

Optional mode `--exchange binance` or `--exchange both` uses Binance public
premium index data for funding, mark, index, and premium. Binance OI is not used
in E2 because historical depth was not approved as primary.

## Output

Append-only monthly CSVs under the E2 unified layout:

- `data/forward/crypto_derivatives/funding/funding_YYYY_MM.csv`
- `data/forward/crypto_derivatives/open_interest/open_interest_YYYY_MM.csv`
- `data/forward/crypto_derivatives/mark_index_premium/mark_index_premium_YYYY_MM.csv`
- `data/forward/crypto_derivatives/health/e2_health_YYYY_MM.csv`
- `data/forward/health/e2_crypto_derivatives_health_report.txt`
- `data/forward/health/e2_unified_daily_health_report.txt`

All timestamps are UTC ISO strings. If an exchange does not provide a native data
timestamp, `data_timestamp_utc` is set to the fetch timestamp.

## Duplicate Prevention

Before append, each monthly file is scanned for existing rows with:

`exchange, symbol, data_timestamp_utc, source_name`

Existing keys are skipped and counted in the health row as
`duplicate_rows_prevented`.

## Commands

Dry run without writing:

```powershell
python scripts/e2_forward_logger.py --exchange bybit --dry-run
```

Normal run:

```powershell
python scripts/e2_forward_logger.py --exchange bybit
```

Health check:

```powershell
python scripts/e2_health_check.py --hours 24
```

## GitHub Actions

`.github/workflows/e2_forward_logger.yml` runs hourly at minute 5 UTC, executes
the crypto derivatives logger, runs crypto and unified health checks, and commits
updated CSV rows back to the repo.

The workflow uses public endpoints only and requires no private API keys.

Repository setting required:

- Actions permissions must allow `contents: write`.

## Limitations

- No liquidation stream.
- No order book or book depth.
- No long/short ratio.
- No paid vendor integration.
- No backfill.
- No interpolation or forward fill.
- Bybit ticker timestamps may be fetch-time snapshots when the endpoint does not
  provide a native data timestamp.
