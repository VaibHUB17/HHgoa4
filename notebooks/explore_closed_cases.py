"""First-hour exploration of closed_cases_history.csv (docs/BHAVYA.md).

A plain runnable script, not a notebook -- `python notebooks/explore_closed_cases.py`.
Run it once data/closed_cases_history.csv exists. Does four things, in order:

  1. Outcome counts (confirmed_fraud vs cleared -- the 4665:900 imbalance).
  2. Pattern distribution (the five known patterns + undocumented + none).
  3. Exposure (exposure_usd) distribution, split by outcome.
  4. THE IMPORTANT ONE: prints every analyst_notes where pattern == 'undocumented'.

That last section is the highest value-per-hour task in the whole ML workstream per
docs/BHAVYA.md: "Finding an undocumented pattern in the exam cases is explicitly scored.
The mechanism is described in those notes, in a human's own words. Read them yourself."
This script surfaces them; a person still has to read them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "closed_cases_history.csv"


def main() -> int:
    if not DATA_PATH.exists():
        print(
            f"error: {DATA_PATH} not found. This script is meant to be run once the "
            f"dataset lands in data/ (gitignored, ~700MB total across the CSVs).",
            file=sys.stderr,
        )
        return 1

    cc = pd.read_csv(DATA_PATH)
    print(f"loaded {len(cc)} closed cases from {DATA_PATH}\n")

    # 1. Outcome counts -----------------------------------------------------------------
    print("=" * 70)
    print("1. OUTCOME COUNTS")
    print("=" * 70)
    print(cc["outcome"].value_counts())
    print(f"\nfraud:cleared ratio = {(cc['outcome'] == 'confirmed_fraud').sum()} : "
          f"{(cc['outcome'] == 'cleared').sum()}")
    print("Remember this ratio when training (train.py class weights) and when scoring:")
    print("half the exam cases are legitimate, so recall on 'cleared' matters as much")
    print("as recall on 'confirmed_fraud'.\n")

    # 2. Pattern distribution -------------------------------------------------------------
    print("=" * 70)
    print("2. PATTERN DISTRIBUTION")
    print("=" * 70)
    print(cc["pattern"].value_counts(dropna=False))
    print()

    # 3. Exposure distribution by outcome --------------------------------------------------
    print("=" * 70)
    print("3. EXPOSURE (exposure_usd) DISTRIBUTION BY OUTCOME")
    print("=" * 70)
    print(cc.groupby("outcome")["exposure_usd"].describe())
    print()
    # Same breakdown, by pattern, since exposure varies a lot by fraud type (card testing
    # tends to be small-and-caught-early, account takeover tends to run up higher totals).
    print("Exposure by pattern (confirmed_fraud only):")
    fraud = cc[cc["outcome"] == "confirmed_fraud"]
    print(fraud.groupby("pattern")["exposure_usd"].describe())
    print()

    # 4. THE IMPORTANT SECTION: undocumented-pattern notes, read by hand -------------------
    print("#" * 70)
    print("# 4. UNDOCUMENTED-PATTERN CASES -- READ THESE NOTES YOURSELF")
    print("#" * 70)
    print(
        "# docs/BHAVYA.md: 'Finding an undocumented pattern in the exam cases is\n"
        "# explicitly scored. The mechanism is described in those notes, in a human's\n"
        "# own words. Read them yourself -- genuinely read them, don't just embed them.'\n"
    )
    undocumented = cc[cc["pattern"] == "undocumented"]
    print(f"# {len(undocumented)} undocumented-pattern case(s) found.\n")
    for _, row in undocumented.iterrows():
        print("-" * 70)
        print(f"case_id: {row.get('case_id')}   customer_id: {row.get('customer_id')}   "
              f"card_id: {row.get('card_id')}   exposure_usd: {row.get('exposure_usd')}")
        print(f"opened_at: {row.get('opened_at')}   closed_at: {row.get('closed_at')}")
        print("analyst_notes:")
        print(f"  {row.get('analyst_notes')}")
    print("-" * 70)
    print(
        f"\n# Done. Go read the {len(undocumented)} notes above and write down, in your\n"
        f"# own words, what mechanism they describe -- that becomes pattern_description\n"
        f"# material for any HHG-0xx exam case that matches the same shape.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
