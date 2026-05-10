# E2 Unified Forward Data Logger

E2 is QuantCore Phase 2 data infrastructure. It logs forward data for future research review only.

It does not create signals, merge futures data with crypto returns, run outcome tests, backtest, modify V12, simulate equity, or produce trading recommendations.

## Modules

- Crypto derivatives Layer 1: funding, open interest, mark price, index price, premium/basis.
- Traditional futures proxy data: conditional daily Yahoo Finance continuous/front-month futures proxy logger.
- Unified health check: reports crypto derivatives and traditional futures module status.

## Folders

- `data/forward/crypto_derivatives/funding/`
- `data/forward/crypto_derivatives/open_interest/`
- `data/forward/crypto_derivatives/mark_index_premium/`
- `data/forward/crypto_derivatives/liquidation_forward_optional/`
- `data/forward/crypto_derivatives/taker_flow_optional/`
- `data/forward/traditional_futures/daily/`
- `data/forward/traditional_futures/metadata/`
- `data/forward/health/`
- `data/forward/metadata/`

Legacy local E2 data may still exist under `data/derivatives_forward/`; new unified runs write to `data/forward/`.

## Commands

Crypto derivatives logger:

```powershell
python scripts/e2_forward_logger.py --exchange bybit
```

Crypto derivatives health:

```powershell
python scripts/e2_health_check.py --hours 24
```

Conditional traditional futures logger:

```powershell
python scripts/e2_traditional_futures_logger.py
```

Without explicit Yahoo ToS confirmation, the futures logger writes only conditional metadata/health and does not fetch production data.

After user confirmation:

```powershell
python scripts/e2_traditional_futures_logger.py --confirm-yahoo-tos
```

Unified health:

```powershell
python scripts/e2_unified_health_check.py --hours 24
```

## GitHub Actions

`.github/workflows/e2_forward_logger.yml` runs the active crypto derivatives logger and unified health check hourly. It commits new `data/forward` crypto derivatives data and health reports back to the repo.

`.github/workflows/e2_unified_forward_logger_proposed.yml` is a proposed manual futures workflow. It requires a `confirm_yahoo_tos` input of `YES` before running the futures fetch.

Repository workflow permissions must allow read/write contents for commit-back.

## Governance

Allowed:

- forward logging
- source expansion
- append-only storage
- duplicate prevention
- health reporting
- documentation

Forbidden:

- strategy Tracks
- outcome testing
- forward returns
- alpha labels
- crypto/futures return merge
- signal generation
- backtests
- V12 changes
- SL/TP/BE logic
- equity curves
- paid data purchases
