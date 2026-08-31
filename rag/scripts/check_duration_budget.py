"""Fail a CI step when a measured duration exceeds its declared budget."""

from __future__ import annotations

import re
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: check_duration_budget.py <metric> <elapsed-seconds> <budget-seconds>")
        return 2

    metric, elapsed_raw, budget_raw = argv
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", metric):
        print("metric must be a simple identifier")
        return 2

    try:
        elapsed = int(elapsed_raw)
        budget = int(budget_raw)
    except ValueError:
        print("elapsed and budget must be integers")
        return 2

    if elapsed < 0 or budget <= 0:
        print("elapsed must be non-negative and budget must be positive")
        return 2

    print(f"{metric}_seconds={elapsed}")
    if elapsed > budget:
        print(f"{metric} exceeded its {budget}s budget", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
