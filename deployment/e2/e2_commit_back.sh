#!/usr/bin/env bash
set -euo pipefail

cd /home/quantcore/quantcore-forward-observation

git pull --rebase --autostash
git add data/forward/crypto_derivatives/bybit_hourly.csv
git add data/forward/crypto_derivatives/e2_forward_health_report.txt

if git diff --cached --quiet; then
    echo "E2_COMMIT_BACK_NO_CHANGES"
    exit 0
fi

git commit -m "E2 VPS forward data update"
git push
