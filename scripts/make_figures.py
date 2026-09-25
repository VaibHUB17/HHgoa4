"""Render the README / blog figures into docs/images/ (PNG + SVG).

    python -m scripts.make_figures

The two data figures (HHG-006 structuring, HHG-014 device ring) are drawn from the real
loaded slice (artifacts/load/txn_slim.csv, produced by `python -m src.graph.load`); the
diagrams are drawn from what the code actually does. Colours follow one fixed role map
(validated palette, light surface): blue = TigerGraph, orange = LLM, green/aqua =
deterministic policy; text always wears text ink, never a series colour.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
SLICE = ROOT / "artifacts" / "load" / "txn_slim.csv"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8a8984"
GRID = "#e6e5e1"
# role colours (validated categorical slots 1-3) and pale tints for box fills
GRAPH, GRAPH_T = "#2a78d6", "#e3eefb"
LLM, LLM_T = "#eb6834", "#fde9e0"
POLICY, POLICY_T = "#1baf7a", "#dff4ec"
NEUTRAL_T = "#f0efec"
CRITICAL = "#d03b3b"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "text.color": INK,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK2,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})


# ---------------------------------------------------------------------------
# drawing helpers
# ---------------------------------------------------------------------------

def _canvas(w=16, h=9):
    fig = plt.figure(figsize=(w, h))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, title, body="", edge=MUTED, fill=NEUTRAL_T, title_size=12.5,
        body_size=10, lw=1.6, align="center"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.14",
                                linewidth=lw, edgecolor=edge, facecolor=fill))
    if body:
        ax.text(x + w / 2 if align == "center" else x + 0.18, y + h - 0.3, title,
                ha=align, va="top", fontsize=title_size, fontweight="bold", color=INK)
        ax.text(x + w / 2 if align == "center" else x + 0.18, y + h - 0.72, body,
                ha=align, va="top", fontsize=body_size, color=INK2, linespacing=1.45)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center",
                fontsize=title_size, fontweight="bold", color=INK)


def arrow(ax, x1, y1, x2, y2, label="", color=MUTED, rad=0.0, lw=1.6, style="-|>",
          label_dx=0.0, label_dy=0.14, label_size=9.5, ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=15,
                                 linewidth=lw, color=color, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2))
    if label:
        ax.text((x1 + x2) / 2 + label_dx, (y1 + y2) / 2 + label_dy, label, ha="center",
                va="bottom", fontsize=label_size, color=INK2)


def legend_row(ax, x, y, items, size=10.5):
    for color, fill, text in items:
        ax.add_patch(FancyBboxPatch((x, y - 0.13), 0.34, 0.26, boxstyle="round,pad=0,rounding_size=0.06",
                                    linewidth=1.4, edgecolor=color, facecolor=fill))
        ax.text(x + 0.46, y, text, va="center", fontsize=size, color=INK2)
        x += 0.62 + len(text) * 0.095


def title(ax, x, y, text, sub=""):
    ax.text(x, y, text, fontsize=19, fontweight="bold", color=INK, va="top")
    if sub:
        ax.text(x, y - 0.5, sub, fontsize=11.5, color=INK2, va="top")


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=160)
    fig.savefig(OUT / f"{name}.svg")
    plt.close(fig)
    print("wrote", OUT / f"{name}.png")


# ---------------------------------------------------------------------------
# 1. system architecture
# ---------------------------------------------------------------------------

def architecture():
    fig, ax = _canvas(16, 9.4)
    title(ax, 0.5, 9.05, "Tracewise — system architecture",
          "The LLM decides where to look and when to stop. The ledger and policy rules decide what is true.")

    # triggers
    box(ax, 0.5, 5.2, 2.6, 2.4, "Trigger",
        "case_pack.csv\n\n• risk score alert\n• customer report\n• analyst request")

    # agent frame
    ax.add_patch(FancyBboxPatch((3.6, 1.5), 7.4, 6.65, boxstyle="round,pad=0,rounding_size=0.18",
                                linewidth=1.2, edgecolor=GRID, facecolor="#f7f7f5"))
    ax.text(3.8, 7.98, "Investigation agent  (LangGraph state machine)", fontsize=12.5,
            fontweight="bold", color=INK, va="top")

    box(ax, 3.9, 5.05, 3.3, 2.35, "Iterative investigator",
        "Assess → Plan → Execute → Integrate\npicks the next query + entity\nstops on CONCLUDE / no new\nevidence / max depth",
        edge=LLM, fill=LLM_T, body_size=9.5)
    box(ax, 7.5, 5.05, 3.2, 2.35, "Detectors",
        "card testing · CNP burst\nnew device · out of region\naccount takeover · shared origin\n$500 structuring (undocumented)",
        edge=POLICY, fill=POLICY_T, body_size=9.5)
    box(ax, 3.9, 1.8, 3.3, 2.75, "Evidence ledger",
        "fixed evidence keys → weights\np = sigmoid(Σ w)\n≥ 2 independent sources to stop\nevidence-set hash per snapshot",
        edge=POLICY, fill=POLICY_T, body_size=9.5)
    box(ax, 7.5, 1.8, 3.2, 2.75, "Policy engine  R1–R10",
        "14 exact actions\nauto / L1 / L2 routing\nbefore → evidence request → after\nSAR gate (FinCEN)",
        edge=POLICY, fill=POLICY_T, body_size=9.5)
    arrow(ax, 7.2, 6.2, 7.5, 6.2)
    arrow(ax, 5.55, 5.05, 5.55, 4.55, "evidence items", label_dx=0.75, label_dy=-0.12)
    arrow(ax, 9.1, 5.05, 7.2, 3.9, "", rad=0.0)
    arrow(ax, 7.2, 3.2, 7.5, 3.2)
    arrow(ax, 3.1, 6.4, 3.9, 6.4)

    # TigerGraph
    box(ax, 11.6, 2.5, 3.9, 5.65, "TigerGraph Savanna 4.2.5",
        "590,742 transactions · 14,780 cards\n13,553 customers · 9,704 devices\n5,565 closed cases\n\n"
        "6 installed GSQL queries\ntg_wcc community detection\nHNSW vectors (1536-d, cosine)\n"
        "on ClosedCase.notesEmb\nand PolicyChunk.textEmb",
        edge=GRAPH, fill=GRAPH_T, body_size=9.8)
    arrow(ax, 11.0, 6.7, 11.6, 6.7)
    ax.text(11.3, 6.85, "TigerGraph\nMCP", ha="center", va="bottom", fontsize=9, color=GRAPH,
            fontweight="bold")
    arrow(ax, 11.6, 5.9, 11.0, 5.9, "rows", label_dy=-0.42)

    # external models
    box(ax, 11.6, 0.35, 3.9, 1.5, "Gemini embeddings",
        "gemini-embedding-001 · 1536-d · L2-normalized\nclosed-case notes indexed on the graph",
        edge=LLM, fill=LLM_T, title_size=11, body_size=9)
    arrow(ax, 13.55, 1.85, 13.55, 2.5, color=LLM)
    ax.text(7.05, 7.25, "Groq LLM", ha="right", va="center", fontsize=9, color=INK,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=LLM, lw=1.2))

    # outputs
    box(ax, 0.5, 1.8, 2.6, 2.75, "Outputs",
        "cases/HHG-*.json\n  case · SAR\n  initial + final NBA\ncases/traces/*.md\n(case also written\nback to the graph)",
        edge=MUTED, fill=NEUTRAL_T, body_size=9.5)
    arrow(ax, 3.9, 3.1, 3.1, 3.1)
    arrow(ax, 10.7, 2.9, 11.6, 2.9, "write_case", color=GRAPH, label_dy=-0.42, lw=1.4)

    legend_row(ax, 0.5, 0.75, [(GRAPH, GRAPH_T, "TigerGraph"), (LLM, LLM_T, "LLM: where to look, prose, embeddings"),
                               (POLICY, POLICY_T, "Deterministic: what is true")])
    save(fig, "architecture")


# ---------------------------------------------------------------------------
# 2. agent state machine
# ---------------------------------------------------------------------------

def agent_flow():
    fig, ax = _canvas(16, 8.2)
    title(ax, 0.5, 7.85, "The investigation loop",
          "Twelve LangGraph nodes. The recommendation is frozen before and after the evidence request.")
    W, H = 2.1, 1.05
    row1 = [("trigger", "seed case,\ncustomer report = denial", None),
            ("investigate", "LLM-directed\ngraph queries", LLM),
            ("gather_evidence", "ledger → p", POLICY),
            ("assess", "stop rule §6", POLICY),
            ("snapshot_initial", "NBA before", POLICY),
            ("request_evidence", "customer / step-up", None)]
    row2 = [("reassess", "fold the reply\ninto the ledger", POLICY),
            ("snapshot_final", "NBA after", POLICY),
            ("policy_gate", "interrupt() for\nL1 / L2 approval", GRAPH),
            ("explain", "LLM prose,\nid-guarded", LLM),
            ("write_case", "InvestigationCase\n→ TigerGraph", GRAPH),
            ("emit", "answer file\n+ trace", None)]
    xs = [0.5 + i * 2.6 for i in range(6)]
    fills = {LLM: LLM_T, POLICY: POLICY_T, GRAPH: GRAPH_T, None: NEUTRAL_T}
    edges = {LLM: LLM, POLICY: POLICY, GRAPH: GRAPH, None: MUTED}
    for (name, body, role), x in zip(row1, xs):
        box(ax, x, 4.6, W, 1.45, name, body, edge=edges[role], fill=fills[role], title_size=11,
            body_size=9)
    for (name, body, role), x in zip(row2, reversed(xs)):
        box(ax, x, 1.7, W, 1.45, name, body, edge=edges[role], fill=fills[role], title_size=11,
            body_size=9)
    for i in range(5):
        arrow(ax, xs[i] + W, 5.32, xs[i + 1], 5.32)
        arrow(ax, xs[5 - i], 2.42, xs[4 - i] + W, 2.42)
    arrow(ax, xs[5] + W / 2, 4.6, xs[5] + W / 2, 3.15)
    # gather_more loop: assess -> investigate
    arrow(ax, xs[3] + W / 2, 6.05, xs[1] + W / 2, 6.05, "", rad=0.3, color=POLICY)
    ax.text((xs[1] + xs[3]) / 2 + W / 2, 6.95, "gather_more  (evidence still thin, loop capped)",
            ha="center", fontsize=9.5, color=INK2)
    # skip request when already decisive
    ax.text(xs[5] - 0.25, 3.85, "request skipped when already decisive:\nfinal = initial, what_changed = \"nothing\"",
            ha="right", fontsize=9.3, color=INK2)
    legend_row(ax, 0.5, 0.75, [(LLM, LLM_T, "LLM involved"), (POLICY, POLICY_T, "Deterministic"),
                               (GRAPH, GRAPH_T, "Graph / human gate"), (MUTED, NEUTRAL_T, "I/O")])
    save(fig, "agent-flow")


# ---------------------------------------------------------------------------
# 3. data pipeline
# ---------------------------------------------------------------------------

def data_pipeline():
    fig, ax = _canvas(16, 7.4)
    title(ax, 0.5, 7.05, "Loading 590,742 transactions into TigerGraph",
          "A GSQL loading job fed by chunked POSTs to /ddl: TigerGraph's bulk path, 0 rejected rows.")
    box(ax, 0.5, 3.5, 2.9, 1.9, "Raw dataset", "transactions.csv  700 MB\nidentity.csv\nclosed_cases_history.csv\ncase_pack.csv",
        body_size=9.5)
    box(ax, 4.1, 3.5, 3.1, 1.9, "Slice (pandas)", "structural columns only\njoin identity → device key\ncard_id per card tuple\n(20/20 exam ids verified)",
        edge=POLICY, fill=POLICY_T, body_size=9.5)
    box(ax, 7.9, 4.55, 2.9, 1.25, "txn_slim.csv", "168 MB · 590,742 rows", body_size=9.5)
    box(ax, 7.9, 3.1, 2.9, 1.25, "next_edges.csv", "575,962 time-ordered pairs", body_size=9.5)
    box(ax, 7.9, 1.65, 2.9, 1.25, "closed cases", "5,565 vertices · 14,955 edges", body_size=9.5)
    box(ax, 4.1, 1.1, 3.1, 1.5, "V1–V339 sidecar", "parquet, local only —\nno published meaning,\nnever in the graph",
        body_size=9.2)
    box(ax, 11.5, 2.3, 4.0, 3.5, "TigerGraph Savanna",
        "LOADING JOB load_fraud\n24 MB header-less chunks\n→ POST /ddl per FILENAME\n\n0 rejected lines\n10 vertex types · 17 edge types",
        edge=GRAPH, fill=GRAPH_T, body_size=9.8)
    arrow(ax, 3.4, 4.45, 4.1, 4.45)
    arrow(ax, 7.2, 4.9, 7.9, 5.15)
    arrow(ax, 7.2, 4.3, 7.9, 3.75)
    arrow(ax, 7.2, 3.8, 7.9, 2.3)
    arrow(ax, 5.65, 3.5, 5.65, 2.6, "V columns", label_dx=0.7, label_dy=-0.1)
    for y in (5.15, 3.75, 2.3):
        arrow(ax, 10.8, y, 11.5, 4.05 + (y - 3.75) * 0.45, color=GRAPH)
    legend_row(ax, 0.5, 0.55, [(POLICY, POLICY_T, "Transform"), (GRAPH, GRAPH_T, "TigerGraph"),
                               (MUTED, NEUTRAL_T, "Files")])
    save(fig, "data-pipeline")


# ---------------------------------------------------------------------------
# 4. graph schema
# ---------------------------------------------------------------------------

def graph_schema():
    fig, ax = _canvas(16, 9.4)
    title(ax, 0.5, 9.05, "Graph schema", "Closed cases hang off the same cards and transactions they involve, so memory is traversable.")
    V = {
        "Customer": (1.2, 5.6, "13,553"),
        "Card": (4.4, 5.6, "14,780"),
        "Transaction": (8.2, 5.6, "590,742"),
        "DeviceProfile": (12.4, 7.35, "9,704"),
        "BillingRegion": (12.4, 5.85, "332"),
        "EmailDomain": (12.4, 4.35, "60"),
        "ProductCategory": (12.4, 2.85, "5"),
        "ClosedCase": (4.4, 2.2, "5,565 · notesEmb"),
        "InvestigationCase": (9.3, 2.2, "agent-written case"),
    }
    w, h = 2.55, 1.0
    fill = {"ClosedCase": LLM_T, "InvestigationCase": POLICY_T}
    edge = {"ClosedCase": LLM, "InvestigationCase": POLICY}
    for name, (x, y, n) in V.items():
        box(ax, x, y, w, h, name, n, edge=edge.get(name, GRAPH), fill=fill.get(name, GRAPH_T),
            title_size=11.5, body_size=9.5)

    def c(name, side):
        x, y, _ = V[name]
        return {"r": (x + w, y + h / 2), "l": (x, y + h / 2), "t": (x + w / 2, y + h),
                "b": (x + w / 2, y)}[side]

    def line(p1, p2, label="", lx=None, ly=None, ha="center", rad=0.0):
        arrow(ax, *p1, *p2, color=INK2, lw=1.3, rad=rad)
        if label:
            ax.text(lx, ly, label, ha=ha, va="center", fontsize=9.5, color=INK2,
                    bbox=dict(boxstyle="round,pad=0.15", fc=SURFACE, ec="none"))

    line(c("Customer", "r"), c("Card", "l"), "OWNS", 4.05, 6.35)
    line(c("Card", "r"), c("Transaction", "l"), "MADE", 7.55, 6.35)
    line(c("Transaction", "r"), c("DeviceProfile", "l"), "FROM_DEVICE", 11.05, 7.35)
    line(c("Transaction", "r"), c("BillingRegion", "l"), "BILLED_IN", 11.55, 6.5)
    line(c("Transaction", "r"), c("EmailDomain", "l"), "PURCHASER / RECIPIENT_EMAIL", 13.675, 5.62)
    line(c("Transaction", "r"), c("ProductCategory", "l"), "IN_CATEGORY", 13.675, 4.12)
    ax.annotate("", xy=(9.9, 6.6), xytext=(9.0, 6.6),
                arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1.3, connectionstyle="arc3,rad=-1.6"))
    ax.text(9.45, 7.45, "NEXT  (time order per card)", ha="center", fontsize=9.5, color=INK2)
    line(c("ClosedCase", "t"), c("Card", "b"), "ON_CARD\nCONNECTED_TO", 5.5, 4.25, ha="left")
    line((6.95, 2.95), (8.75, 5.6), "INVOLVES", 7.55, 4.3)
    line((10.4, 3.2), (10.4, 5.6), "CASE_INVOLVES", 10.25, 4.6, ha="right")
    ax.text(10.575, 2.05, "also CASE_ON_CARD · CASE_CONNECTED_TO → Card", ha="center", va="top",
            fontsize=9.3, color=INK2)
    box(ax, 0.6, 0.45, 3.2, 1.25, "PolicyChunk", "fraud policy R1–R10 · textEmb", edge=LLM, fill=LLM_T,
        title_size=11, body_size=9.2)
    legend_row(ax, 4.6, 0.95, [(GRAPH, GRAPH_T, "Entities (loaded)"), (LLM, LLM_T, "Vector-bearing memory"),
                               (POLICY, POLICY_T, "Written by the agent")])
    save(fig, "graph-schema")


# ---------------------------------------------------------------------------
# 5. approval routing
# ---------------------------------------------------------------------------

def approval_routing():
    fig, ax = _canvas(16, 6.9)
    title(ax, 0.5, 6.6, "Permissions: the agent executes auto actions only",
          "Every recommended action passes one finalize_action() chokepoint that resolves its route from policy.")
    lanes = [
        ("auto", "executed by the agent", POLICY, POLICY_T,
         "ALLOW_TRANSACTION · MONITOR_CARD · MONITOR_CONNECTED_CARDS · WARN_CUSTOMER\n"
         "VERIFY_WITH_CUSTOMER · STEP_UP_AUTH · GENERATE_REPORT · CREATE_CASE\n"
         "ESCALATE_TO_ANALYST · CLOSE_NO_FRAUD"),
        ("L1", "fraud analyst approves", "#eda100", "#fdf3dc",
         "DECLINE_TRANSACTION\nBLOCK_CARD  when exposure ≤ $2,500"),
        ("L2", "senior / compliance approves", CRITICAL, "#fbe4e4",
         "BLOCK_CARD  when exposure > $2,500\nBLOCK_ALL_CARDS  (R10: only if 2+ cards confirmed or credentials compromised)\nFILE_REPORT  (SAR)"),
    ]
    y = 4.55
    for name, who, color, tint, actions in lanes:
        box(ax, 0.5, y, 2.2, 1.35, name, who, edge=color, fill=tint, title_size=15, body_size=9.5)
        ax.add_patch(FancyBboxPatch((3.0, y), 12.5, 1.35, boxstyle="round,pad=0,rounding_size=0.14",
                                    linewidth=1.2, edgecolor=GRID, facecolor="white"))
        ax.text(3.3, y + 0.675, actions, va="center", fontsize=10.2, color=INK, linespacing=1.55)
        y -= 1.75
    ax.text(0.5, 0.45, "R7 (disputed charge matching the customer's own recurring pattern) forbids BLOCK_CARD, "
            "DECLINE_TRANSACTION and FILE_REPORT outright.", fontsize=10, color=INK2)
    save(fig, "approval-routing")


# ---------------------------------------------------------------------------
# 6. HHG-006 structuring (real data)
# ---------------------------------------------------------------------------

def structuring_chart():
    import pandas as pd

    t = pd.read_csv(SLICE, usecols=["TransactionID", "ts", "TransactionAmt", "channel", "card_id"],
                    parse_dates=["ts"])
    a = t[(t.card_id == "C07297-K1") & (t.ts >= "2016-11-21 19:40") & (t.ts <= "2016-11-21 20:50")
          & (t.channel == "online")].sort_values("ts")
    fig, ax = plt.subplots(figsize=(12, 6.2))
    fig.subplots_adjust(left=0.09, right=0.97, top=0.8, bottom=0.14)
    ax.axhline(500, color=CRITICAL, lw=2, ls=(0, (5, 4)))
    ax.text(a.ts.iloc[0] - pd.Timedelta(minutes=17), 503, "\\$500 authorization threshold", color=INK2,
            fontsize=10.5, va="bottom")
    ax.axhspan(450, 500, color="#fbe4e4", zorder=0)
    ax.text(a.ts.iloc[-1] + pd.Timedelta(minutes=2), 452, "detector band\n\\$450 – \\$500", color=INK2, fontsize=9.5,
            va="bottom")
    ax.vlines(a.ts, 0, a.TransactionAmt, color=GRAPH, lw=2)
    ax.scatter(a.ts, a.TransactionAmt, s=90, color=GRAPH, edgecolor=SURFACE, linewidth=2, zorder=3)
    for ts, amt, tid in zip(a.ts, a.TransactionAmt, a.TransactionID):
        ax.text(ts, amt - 34, f"\\${amt:,.2f}\nT{tid}", ha="center", va="top", fontsize=9.5, color=INK,
                bbox=dict(boxstyle="round,pad=0.25", fc=SURFACE, ec=GRID), zorder=4)
    ax.set_ylim(0, 560)
    ax.set_xlim(a.ts.iloc[0] - pd.Timedelta(minutes=18), a.ts.iloc[-1] + pd.Timedelta(minutes=18))
    ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("${x:,.0f}"))
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.set_xlabel("21 Nov 2016, card C07297-K1 (online, new device each time)")
    fig.text(0.09, 0.93, "HHG-006: four purchases in 30 minutes, each just under $500",
             fontsize=16, fontweight="bold", color=INK)
    fig.text(0.09, 0.87, "Authorization-threshold structuring. Not one of the five documented patterns; "
             "matches closed cases CC-3748, CC-3841, CC-3907, CC-4086, CC-4124.", fontsize=10.5, color=INK2)
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "hhg006-structuring.png", dpi=160)
    fig.savefig(OUT / "hhg006-structuring.svg")
    plt.close(fig)
    print("wrote", OUT / "hhg006-structuring.png")


# ---------------------------------------------------------------------------
# 7. HHG-014 device ring (real data)
# ---------------------------------------------------------------------------

def device_ring():
    import math

    import pandas as pd

    t = pd.read_csv(SLICE, usecols=["TransactionID", "ts", "card_id", "customer_id", "device_key", "id_23"],
                    parse_dates=["ts"])
    dev = t.loc[t.TransactionID == 3478561, "device_key"].iloc[0]
    end = pd.Timestamp("2016-11-22 16:11:00")
    w = t[(t.device_key == dev) & (t.ts >= end - pd.Timedelta(days=7)) & (t.ts <= end)]
    cards = w.groupby("card_id").agg(n=("TransactionID", "size"), first=("ts", "min"),
                                     cust=("customer_id", "first")).sort_values("first")
    fig, ax = _canvas(13, 11.6)
    ax.set_xlim(-6.5, 6.5)
    ax.set_ylim(-6.3, 5.3)
    ax.text(-6.2, 5.05, "HHG-014: one device fingerprint, 18 cardholders, 7 days", fontsize=18,
            fontweight="bold", va="top")
    ax.text(-6.2, 4.5, f"Every one of the {len(w)} transactions: new device for the account, behind an anonymous proxy.",
            fontsize=11, color=INK2, va="top")
    R = 3.35
    for i, (card, row) in enumerate(cards.iterrows()):
        ang = math.pi / 2 - 2 * math.pi * i / len(cards)
        x, y = R * math.cos(ang), R * math.sin(ang) - 0.55
        flagged = card == "C13487-K1"
        ax.plot([0, x], [-0.55, y], color=CRITICAL if flagged else GRAPH, lw=1 + row.n, alpha=0.9, zorder=1)
        ax.scatter([x], [y], s=520 if flagged else 300, color=CRITICAL if flagged else GRAPH,
                   edgecolor=SURFACE, linewidth=2.5, zorder=3)
        lx, ly = (R + 0.95) * math.cos(ang), (R + 0.95) * math.sin(ang) - 0.55
        ax.text(lx, ly, f"{card}\n{row['first']:%d %b %H:%M}" + (f"  ×{row.n}" if row.n > 1 else ""),
                ha="center", va="center", fontsize=8.6, color=INK, fontweight="bold" if flagged else "normal")
    ax.scatter([0], [-0.55], s=6200, color=LLM_T, edgecolor=LLM, linewidth=2, zorder=4)
    ax.text(0, -0.55, "SM-G935F\nAndroid 7.0\nChrome 62\n1920×1080", ha="center", va="center", fontsize=9,
            zorder=5)
    ax.text(-6.2, -5.75, "Red: the case's own card (flagged purchase T3478561). Time = first transaction in the "
            "window; ×2 = two transactions.\nSource: TigerGraph device_neighbors, 15–22 Nov 2016.",
            fontsize=9.5, color=INK2, va="center")
    save(fig, "hhg014-device-ring")


def main() -> None:
    architecture()
    agent_flow()
    data_pipeline()
    graph_schema()
    approval_routing()
    if SLICE.exists():
        structuring_chart()
        device_ring()
    else:
        print(f"skipping data figures: {SLICE} not found (run python -m src.graph.load first)")


if __name__ == "__main__":
    main()
