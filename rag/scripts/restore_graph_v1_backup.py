#!/usr/bin/env python3
"""Restore the pre-migration Graph relation schema v1 backup."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from documents.graph_store import (
        DEFAULT_DB_PATH,
        DEFAULT_V1_BACKUP_PATH,
        restore_graph_v1_backup,
    )

    parser = argparse.ArgumentParser(
        description="Restore Graph schema v1 backup; the service must be stopped."
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--backup", default=DEFAULT_V1_BACKUP_PATH)
    args = parser.parse_args()
    try:
        restore_graph_v1_backup(args.db, args.backup)
    except Exception as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Graph v1 backup restored. Observation-window v2 graph writes are not present; "
        "start the old service only after verifying the restored database."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
