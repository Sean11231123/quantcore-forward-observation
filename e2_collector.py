import csv
import json
import os
import urllib.request
from datetime import datetime, timezone

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "BNBUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "APTUSDT",
    "ARBUSDT",
    "OPUSDT",
    "SUIUSDT",
    "POLUSDT",
    "NEARUSDT",
    "DOTUSDT",
    "TRXUSDT",
]

OUTPUT_FILE = os.path.expanduser(
    "~/quantcore-forward-observation/data/forward/crypto_derivatives/bybit_hourly.csv"
)

URL_TEMPLATE = (
    "https://api.bybit.com/v5/market/tickers"
    "?category=linear&symbol={symbol}"
)

os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

existing_keys = set()

if os.path.exists(OUTPUT_FILE):
    with open(OUTPUT_FILE, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing_keys.add(
                (row["data_timestamp_utc"], row["symbol"])
            )

fieldnames = [
    "fetch_timestamp_utc",
    "data_timestamp_utc",
    "symbol",
    "last_price",
    "mark_price",
    "index_price",
    "open_interest",
    "funding_rate",
]

rows_to_append = []

for symbol in SYMBOLS:
    try:
        url = URL_TEMPLATE.format(symbol=symbol)

        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))

        row = data["result"]["list"][0]

        fetch_ts = datetime.now(timezone.utc)

        data_ts = fetch_ts.replace(
            minute=0,
            second=0,
            microsecond=0
        )

        key = (data_ts.isoformat(), symbol)

        if key in existing_keys:
            print(f"{symbol}: DUPLICATE_SKIPPED")
            continue

        rows_to_append.append({
            "fetch_timestamp_utc": fetch_ts.isoformat(),
            "data_timestamp_utc": data_ts.isoformat(),
            "symbol": symbol,
            "last_price": row.get("lastPrice"),
            "mark_price": row.get("markPrice"),
            "index_price": row.get("indexPrice"),
            "open_interest": row.get("openInterest"),
            "funding_rate": row.get("fundingRate"),
        })

        print(f"{symbol}: READY")

    except Exception as e:
        print(f"{symbol}: ERROR: {e}")

file_exists = os.path.exists(OUTPUT_FILE)

with open(OUTPUT_FILE, "a", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)

    if not file_exists:
        writer.writeheader()

    writer.writerows(rows_to_append)

print("=" * 60)
print("ROWS_WRITTEN:", len(rows_to_append))
print("OUTPUT:", OUTPUT_FILE)
