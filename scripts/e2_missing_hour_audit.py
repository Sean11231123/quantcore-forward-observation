from __future__ import annotations

import argparse
from pathlib import Path

from e2_forward_health_check import DATA_FILE, analyze


def render_audit(result: dict[str, object]) -> str:
    lines = [
        "E2 Missing-Hour Audit",
        f"generated_at_utc: {result['generated_at_utc']}",
        f"data_file: {result['data_file']}",
        f"classification: {result['classification']}",
        f"expected_symbol_count: {result['expected_symbol_count']}",
        f"total_rows: {result['total_rows']}",
        f"first_data_timestamp_utc: {result['first_data_timestamp_utc']}",
        f"latest_data_timestamp_utc: {result['latest_data_timestamp_utc']}",
        f"latest_data_lag_hours: {result['latest_data_lag_hours']}",
        "",
        "Last 24h Findings",
        f"complete_hours: {result['complete_hours_last_24h']}",
        f"missing_hours: {result['missing_hours_last_24h']}",
        f"incomplete_hours: {result['incomplete_hours_last_24h']}",
        f"duplicate_rows: {result['duplicate_rows_last_24h']}",
        "",
        "Malformed/Unexpected Findings",
        f"malformed_rows: {result['malformed_rows']}",
        f"unexpected_symbols: {result['unexpected_symbols']}",
        f"unexpected_symbol_values: {','.join(result['unexpected_symbol_values'])}",
        "",
        "Missing Hour Values Last 24h",
        *[str(v) for v in result["missing_hour_values_last_24h"]],
        "",
        "Incomplete Hour Values Last 24h",
        *[str(v) for v in result["incomplete_hour_values_last_24h"]],
        "",
        "Duplicate Row Keys Last 24h",
        *[str(v) for v in result["duplicate_row_keys_last_24h"]],
        "",
        "Governance",
        "Existing missing hours remain missing.",
        "No backfill, synthesized rows, overwrite, or historical repair is performed.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit E2 bybit_hourly.csv for missing and incomplete hours.")
    parser.add_argument("--data-file", type=Path, default=DATA_FILE)
    args = parser.parse_args()
    print(render_audit(analyze(args.data_file)))


if __name__ == "__main__":
    main()
