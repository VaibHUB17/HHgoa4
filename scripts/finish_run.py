"""One command to finish the submission once Savanna is awake.

Everything that has to happen between "the workspace is back" and "the twenty answer
files are correct and committed" is in here, so nobody has to remember the order at
11pm:

  1. wait for the workspace (it takes 1-2 minutes to wake even with Auto Resume on)
  2. verify the graph actually has data, not just a live endpoint
  3. regenerate all twenty cases in agentic mode
  4. validate every file
  5. report what changed against the committed run, in particular whether the two
     known defects are gone

It does not commit or push. A human reads the report and decides.

    python -m scripts.finish_run              # full run
    python -m scripts.finish_run --check      # just say whether the workspace is ready
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases"

# The two defects known to be baked into the committed run. Both are fixed in code; this
# script exists partly to prove the fixes reached the output.
KNOWN_DEFECTS = """
  HHG-014 reported verdict `uncertain` while filing a SAR, which policy 3a forbids.
  No case carried an llm_decision evidence ref, so the agentic path was never exercised.
""".strip("\n")


def _log(msg: str) -> None:
    print(msg, flush=True)


def snapshot() -> dict:
    """Summarise the answer files currently on disk."""
    out: dict = {"verdicts": {}, "llm_refs": 0, "sar": 0, "n": 0, "hhg014": None}
    for f in sorted(CASES.glob("*.json")):
        a = json.loads(f.read_text(encoding="utf-8"))
        c = a["case"]
        out["n"] += 1
        out["verdicts"][c["verdict"]] = out["verdicts"].get(c["verdict"], 0) + 1
        if a["sar"]["file"]:
            out["sar"] += 1
        if any("llm_decision" in e.get("ref", "") for e in c["evidence"]):
            out["llm_refs"] += 1
        if a["case_id"] == "HHG-014":
            out["hhg014"] = {
                "verdict": c["verdict"],
                "p": c["fraud_probability"],
                "sar": a["sar"]["file"],
            }
    return out


def run(cmd: list[str], label: str) -> bool:
    _log(f"\n>>> {label}")
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        _log(f"!!! {label} failed (exit {proc.returncode})")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report whether the workspace is reachable, change nothing")
    ap.add_argument("--wait", type=float, default=300.0,
                    help="seconds to wait for the workspace (default 300)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="    %(levelname)s %(message)s")
    sys.path.insert(0, str(ROOT))
    from src.graph.connection import wake_workspace  # noqa: PLC0415

    _log("Waiting for the Savanna workspace...")
    if not wake_workspace(timeout_s=args.wait):
        _log(
            "\nWorkspace is not available.\n"
            "If the log above says Auto Resume is OFF, that is a console setting nobody\n"
            "can change from here: Savanna -> Workspace Configuration -> Advanced\n"
            "Settings -> Auto Resume, switch it on, then Resume the workspace once.\n"
        )
        return 1
    _log("Workspace is up.")

    if args.check:
        _log("\n--check: workspace is reachable. Re-run without --check to regenerate.")
        return 0

    before = snapshot()
    _log(f"\nBefore: {before['n']} files, verdicts {before['verdicts']}, "
         f"{before['sar']} SARs, {before['llm_refs']}/20 with an llm_decision ref")
    _log(f"  HHG-014 -> {before['hhg014']}")

    # Confirm the graph holds data. A workspace can answer while its graph is empty,
    # and regenerating against an empty graph would quietly produce twenty useless
    # files that still pass schema validation.
    if not run([sys.executable, "-m", "scripts.setup_graph", "--check"],
               "verifying schema and installed queries"):
        _log("The graph is reachable but not ready. Load the data before regenerating.")
        return 1

    if not run([sys.executable, "-m", "src.agent.run", "--all",
                "--evidence-mode", "agentic", "--out", "cases/"],
               "regenerating all 20 cases in agentic mode"):
        return 1

    if not run([sys.executable, "-m", "src.answer.validator", "cases/"],
               "validating the answer files"):
        _log("Validation failed. Do not submit these files.")
        return 1

    after = snapshot()
    _log("\n" + "=" * 62)
    _log(f"After:  {after['n']} files, verdicts {after['verdicts']}, "
         f"{after['sar']} SARs, {after['llm_refs']}/20 with an llm_decision ref")
    _log(f"  HHG-014 -> {after['hhg014']}")

    _log("\nKnown defects in the previous run:")
    _log(KNOWN_DEFECTS)

    ok = True
    h = after["hhg014"] or {}
    if h.get("sar") and h.get("verdict") != "fraud":
        _log("\n  STILL PRESENT: HHG-014 files a SAR on a non-fraud verdict.")
        ok = False
    else:
        _log("\n  FIXED: HHG-014's verdict and its SAR now agree.")

    if after["llm_refs"] == 0:
        _log("  STILL PRESENT: no case carries an llm_decision ref.")
        _log("    The agentic path did not fire. Check that GROQ_API_KEY is set in .env.")
        ok = False
    else:
        _log(f"  FIXED: {after['llm_refs']}/20 cases carry an llm_decision ref.")

    if after["verdicts"].get("fraud", 0) > 12:
        _log(f"\n  WARNING: {after['verdicts']['fraud']}/20 came back fraud. The brief "
             "says about half these cases are legitimate, so this looks like over-blocking.")
        ok = False

    _log("\n" + "=" * 62)
    _log("Files are regenerated and valid. Review a couple by hand, then commit."
         if ok else
         "Regenerated, but the checks above did not all pass. Read them before committing.")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
