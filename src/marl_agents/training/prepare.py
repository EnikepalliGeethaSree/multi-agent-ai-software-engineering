"""Build the classifier dataset: python -m marl_agents.training.prepare [--max-train 20000]."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from marl_agents.config import PROJECT_ROOT, load_settings
from marl_agents.training.data import SEED, prepare


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "classifier" / "py")
    parser.add_argument("--max-train", type=int, help="balanced training examples to keep")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--max-per-project",
        type=int,
        default=1500,
        help="cap on records from one named project (0 = no cap)",
    )
    parser.add_argument(
        "--keep-low-information",
        action="store_true",
        help="keep positives whose review comment is empty or a one-word remark",
    )
    parser.add_argument(
        "--python-only",
        action="store_true",
        help="leave out the same-source records of other languages",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = load_settings()
    manifest = prepare(
        PROJECT_ROOT / s.datasets.root,
        args.out,
        PROJECT_ROOT / s.datasets.cache_dir,
        args.max_train,
        args.seed,
        args.keep_low_information,
        args.max_per_project or None,
        not args.python_only,
    )
    for split in manifest.splits:
        print(
            f"{split.name}: {split.records} read, {split.kept} kept "
            f"({split.positives} positive, {split.negatives} negative), dropped {split.dropped}"
        )
    print(f"python filter check: {manifest.python_filter_check}")
    print(f"saved: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
