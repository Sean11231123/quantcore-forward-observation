# E2 Traditional Futures Data Sources

Traditional futures support is integrated under E2 Unified Forward Data Logger. It is not a separate E3 project.

## Yahoo Finance

Yahoo Finance exposes public futures quote pages and chart history for symbols such as:

- `ES=F`
- `NQ=F`
- `RTY=F`
- `CL=F`
- `GC=F`
- `HG=F`
- `ZN=F`
- `ZB=F`
- `BTC=F`
- `ETH=F`

`BTC=F` was verified as a visible Yahoo Finance CME Bitcoin futures symbol during the data-source audit. `ETH=F` must still be verified by live fetch before production activation.

### ToS Caveat

Yahoo Finance usage is subject to Yahoo terms. This audit did not establish that unattended automated downloading is clearly permitted. For that reason, the traditional futures logger is conditional and requires explicit user confirmation via `--confirm-yahoo-tos`.

## Continuous Futures Limitation

Yahoo symbols such as `ES=F`, `NQ=F`, `GC=F`, and `BTC=F` are continuous or front-month proxy symbols. They may roll at contract expiry and may not be back-adjusted.

Implications:

- daily close can contain rollover artifacts
- price levels should not be compared precisely across rolls
- data is acceptable only as broad cross-asset risk proxy data
- data is not suitable for precise contract-level futures research

## CME Delayed Quotes

CME delayed quote pages are useful as official reference context. CME delayed quotes are delayed by at least 10 minutes, and CME website market data should be treated as reference-only rather than as a high-quality automated historical research feed.

## Databento

Databento is a possible future paid source for better futures data. It may support contract-level historical data and cleaner roll handling, but no paid API or purchase was used in this task.

## Why No Outcome Testing

Traditional futures are included only as cross-asset risk proxy data. E2 does not test whether futures explain crypto returns, does not merge with crypto returns, and does not create signals.
