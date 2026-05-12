#!/data/data/com.termux/files/usr/bin/bash

cd ~/quantcore-forward-observation || exit 1

echo "============================================================"
echo "E2 PUSH START UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"

echo "PULL_REBASE_START"
git pull --rebase --autostash
PULL_STATUS=$?

if [ "$PULL_STATUS" -ne 0 ]; then
    echo "PULL_REBASE_FAILED"
    exit 1
fi

echo "ADD_FILES"
git add data/forward/crypto_derivatives/bybit_hourly.csv
git add e2_collector.py
git add .gitignore

if git diff --cached --quiet; then
    echo "NO_CHANGES_TO_COMMIT"
    echo "E2 PUSH END UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    exit 0
fi

echo "COMMIT_START"
git commit -m "E2 Pixel4 hourly data update"

echo "PUSH_START"
git push
PUSH_STATUS=$?

if [ "$PUSH_STATUS" -ne 0 ]; then
    echo "PUSH_FAILED"
    exit 1
fi

echo "PUSH_OK"
echo "E2 PUSH END UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
