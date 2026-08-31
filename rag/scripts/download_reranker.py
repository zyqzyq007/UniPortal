#!/usr/bin/env python3
"""Download and save the configured cross-encoder reranker for offline use."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentence_transformers import CrossEncoder

from utils.env_utils import PROJECT_ROOT, RERANKER_DEVICE, RERANKER_MODEL, RERANKER_MODEL_PATH


def _safe_model_name(model_name: str) -> str:
    return model_name.replace("/", "_").replace(":", "_")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=RERANKER_MODEL_PATH
        or str(
            PROJECT_ROOT / "models" / "local_models" / "reranker" / _safe_model_name(RERANKER_MODEL)
        ),
        help="Directory to save the reranker model for offline loading.",
    )
    args = parser.parse_args()

    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = PROJECT_ROOT / output

    source = str(output) if output.is_dir() else RERANKER_MODEL
    model = CrossEncoder(source, device=RERANKER_DEVICE)
    output.mkdir(parents=True, exist_ok=True)
    model.save(str(output))
    print(
        {
            "model": RERANKER_MODEL,
            "saved_to": str(output),
            "device": RERANKER_DEVICE,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
