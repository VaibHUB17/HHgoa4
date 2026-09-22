# Dataset goes here

These files are provided by the organizers and are NOT committed (~700MB, gitignored).

Put these four files in this directory:

- `transactions.csv`          590,742 rows, 393 Vesta columns + customer_id, ts, channel, risk_score
- `identity.csv`              144,432 rows, 41 columns, joins on TransactionID
- `closed_cases_history.csv`  5,565 closed investigations (Jul-Oct), the labelled history
- `case_pack.csv`             the 20 exam cases (Nov-Dec)

Then:

    python -m src.graph.load --data-dir ./data

## Verify on arrival

Before building on it, confirm the shapes match the brief:

    python -c "
    import pandas as pd
    cp = pd.read_csv('data/case_pack.csv'); print(cp.shape, list(cp.columns))
    cc = pd.read_csv('data/closed_cases_history.csv'); print(cc.outcome.value_counts())
    print(sorted(cp.card_id.unique())[:5])   # confirms the C01234-K1 card_id format
    "

The card_id check matters: `src/graph/load.py` derives card_id by grouping each customer's
rows on the full (card1..card6) tuple and numbering them K1, K2... by first appearance.
That is an inference, not a documented rule. Cross-check the derived ids against the real
ones in case_pack.csv and closed_cases_history.csv before trusting any downstream output.
