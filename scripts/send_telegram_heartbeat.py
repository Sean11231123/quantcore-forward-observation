from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notifications.telegram_bot import send_message


def main() -> int:
    result = send_message("QuantCore GitHub Actions Online \u2705", parse_mode=None)
    print("telegram_heartbeat:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"OK", "skipped_missing_env"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
