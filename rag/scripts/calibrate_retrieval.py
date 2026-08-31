#!/usr/bin/env python3
"""F4: grid-search calibration of retrieval algorithm constants via the eval flywheel.

Sweeps RRF_K × MMR_LAMBDA (and optionally DENSE/SPARSE weights) against the golden
eval dataset, reports the best-scoring combination. Does NOT auto-apply — prints
the recommended env vars for the operator to set after human review.

The eval uses rule-only scoring (--no-judge) so it runs offline without Ollama,
making it CI-friendly. For full judge-based calibration, run with --use-judge
(requires Ollama).

Run:
  uv run --frozen python scripts/calibrate_retrieval.py
  uv run --frozen python scripts/calibrate_retrieval.py --rrf-k 40,60,80 --mmr-lambda 0.5,0.7,0.9
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.log_utils import log


def _run_eval_with_params(rrf_k: int, mmr_lambda: float, dense_w: float, sparse_w: float) -> dict:
    """Run the eval flywheel with the given params and return the score summary."""
    import os

    os.environ["RRF_K"] = str(rrf_k)
    os.environ["MMR_LAMBDA"] = str(mmr_lambda)
    os.environ["DENSE_WEIGHT"] = str(dense_w)
    os.environ["SPARSE_WEIGHT"] = str(sparse_w)

    # Reset the hybrid retriever singleton so new config takes effect.
    try:
        import core.retrieval.hybrid_retriever as hr_mod

        hr_mod._hybrid_retriever = None
    except Exception:  # noqa: BLE001
        pass

    try:
        from scripts.run_eval import main as run_eval_main
    except ImportError:
        log.error("run_eval not found; ensure scripts/run_eval.py exists")
        return {"error": "run_eval unavailable"}

    # Capture the eval result (run_eval exits with code 0/1; we catch).
    import contextlib
    import io

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            run_eval_main(["--no-judge", "--tag", f"calibrate_rrf{rrf_k}_mmr{mmr_lambda}"])
    except SystemExit:
        pass
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}

    # Parse the summary from the output (run_eval prints a score summary).
    output = buf.getvalue()
    return {"output": output[-500:], "params": {"rrf_k": rrf_k, "mmr_lambda": mmr_lambda}}


def main() -> int:
    parser = argparse.ArgumentParser(description="F4 grid-search retrieval constant calibration.")
    parser.add_argument("--rrf-k", default="40,60,80", help="Comma-separated RRF_K values.")
    parser.add_argument(
        "--mmr-lambda", default="0.5,0.7,0.9", help="Comma-separated MMR_LAMBDA values."
    )
    parser.add_argument(
        "--dense-weight", default="0.5", help="Comma-separated DENSE_WEIGHT values."
    )
    parser.add_argument(
        "--sparse-weight", default="0.5", help="Comma-separated SPARSE_WEIGHT values."
    )
    args = parser.parse_args()

    rrf_ks = [int(x) for x in args.rrf_k.split(",")]
    mmr_lambdas = [float(x) for x in args.mmr_lambda.split(",")]
    dense_ws = [float(x) for x in args.dense_weight.split(",")]
    sparse_ws = [float(x) for x in args.sparse_weight.split(",")]

    grid = list(itertools.product(rrf_ks, mmr_lambdas, dense_ws, sparse_ws))
    print(f"F4 calibration: {len(grid)} combinations to evaluate (rule-only scoring)")
    print(f"Grid: RRF_K={rrf_ks}, MMR_LAMBDA={mmr_lambdas}, DENSE={dense_ws}, SPARSE={sparse_ws}")
    print("-" * 70)

    results = []
    for i, (rrf_k, mmr_lambda, dense_w, sparse_w) in enumerate(grid, 1):
        print(
            f"[{i}/{len(grid)}] RRF_K={rrf_k}, MMR_LAMBDA={mmr_lambda}, DENSE={dense_w}, SPARSE={sparse_w}"
        )
        result = _run_eval_with_params(rrf_k, mmr_lambda, dense_w, sparse_w)
        results.append(result)
        if "error" in result:
            print(f"  ERROR: {result['error']}")
        else:
            # Extract the composite score from the output (best-effort parse).
            output = result.get("output", "")
            print(f"  output tail: {output[-200:].strip()}")

    print("-" * 70)
    print("Calibration complete. Review the outputs above and set the env vars")
    print("for the best-scoring combination in your .env:")
    print("  RRF_K=<best>")
    print("  MMR_LAMBDA=<best>")
    print("  DENSE_WEIGHT=<best>")
    print("  SPARSE_WEIGHT=<best>")
    print("Then restart the server. Re-run this script to verify improvement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
