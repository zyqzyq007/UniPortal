#!/usr/bin/env python3
"""Explicitly prepare a ColPali model directory for offline runtime use."""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_MODEL = "vidore/colpali-v1.3"
DEFAULT_OUTPUT = Path("models/local_models/colpali")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download ColPali assets explicitly; runtime never downloads models."
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=None)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)

    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=args.model,
        revision=args.revision,
        local_dir=output,
    )
    print(
        {
            "model": args.model,
            "revision": args.revision or "default",
            "saved_to": str(output),
            "runtime_env": f"COLPALI_MODEL_PATH={output}",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
