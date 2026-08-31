#!/usr/bin/env python3
"""
Candidate curation CLI — review promoted candidates and promote them into the
golden dataset.

Workflow:
    # List candidates awaiting review
    python scripts/curate_golden.py --list

    # Inspect one candidate
    python scripts/curate_golden.py --show <candidate_id>

    # Promote a correction candidate (its corrected_answer becomes the golden)
    python scripts/curate_golden.py --promote <candidate_id>

    # Promote with a manually-written golden answer (for thumbs_down/flag)
    python scripts/curate_golden.py --promote <candidate_id> \
        --reference "【诊断结论】...expected answer..."

    # Discard a candidate
    python scripts/curate_golden.py --discard <candidate_id>
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.eval.candidates import (  # noqa: E402
    list_candidates,
    load_candidate,
    promote_candidate_to_golden,
)
from agent.eval.flywheel import get_retrieval_misses  # noqa: E402


def _print_candidate(c, verbose: bool = False):
    print(f"\n[{c.candidate_id}] feedback={c.feedback_type} source={c.source}")
    print(f"  trace={c.trace_id[:16]}  session={c.session_id[:16]}")
    print(f"  Q: {c.query}")
    print(f"  A: {c.answer[:200]}{'...' if len(c.answer) > 200 else ''}")
    if c.corrected_answer:
        print(f"  corrected: {c.corrected_answer[:200]}")
    if verbose:
        for d in (c.retrieved_docs or [])[:3]:
            src = d.get("source") if isinstance(d, dict) else "?"
            snippet = (d.get("content", "") if isinstance(d, dict) else str(d))[:120]
            print(f"  ctx[{src}]: {snippet}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Curate eval candidates into the golden dataset.")
    p.add_argument("--list", action="store_true", help="List candidates awaiting review.")
    p.add_argument("--show", metavar="ID", help="Show a single candidate in detail.")
    p.add_argument("--promote", metavar="ID", help="Promote a candidate to golden.yaml.")
    p.add_argument("--reference", help="Manual golden answer (for promote without a correction).")
    p.add_argument("--case-id", help="Explicit eval-case id for the promoted case.")
    p.add_argument("--dataset", default="data/eval/golden.yaml", help="Target dataset.")
    p.add_argument("--discard", metavar="ID", help="Delete a candidate without promoting.")
    p.add_argument("--misses", action="store_true", help="Show recent retrieval-miss signals.")
    args = p.parse_args(argv)

    if args.list:
        cands = list_candidates()
        if not cands:
            print("No candidates awaiting review.")
            return 0
        print(f"{len(cands)} candidate(s) awaiting review:")
        for c in cands:
            _print_candidate(c)
        return 0

    if args.show:
        c = load_candidate(args.show)
        if c is None:
            print(f"Candidate not found: {args.show}")
            return 2
        _print_candidate(c, verbose=True)
        return 0

    if args.promote:
        promoted = promote_candidate_to_golden(
            args.promote,
            dataset_path=args.dataset,
            case_id=args.case_id or "",
            reference_answer_override=args.reference,
        )
        if promoted is None:
            print(
                "Promotion failed: candidate not found, or has no reference "
                "answer (pass --reference to supply one)."
            )
            return 2
        print(f"Promoted -> {args.dataset} as case id={promoted.id}")
        return 0

    if args.discard:
        from agent.eval.candidates import CANDIDATES_DIR

        path = CANDIDATES_DIR / f"{args.discard}.json"
        if path.exists():
            path.unlink()
            print(f"Discarded candidate {args.discard}")
            return 0
        print(f"Candidate not found: {args.discard}")
        return 2

    if args.misses:
        rows = get_retrieval_misses()
        if not rows:
            print("No retrieval-miss signals recorded.")
            return 0
        print(f"{len(rows)} retrieval-miss signal(s):")
        for r in rows[:20]:
            print(
                f"  faith={r.get('faithfulness')}  fb={r.get('feedback_type')}  "
                f"Q: {r.get('query', '')[:60]}"
            )
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
