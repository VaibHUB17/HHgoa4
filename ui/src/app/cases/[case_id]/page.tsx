import { notFound } from "next/navigation";
import Link from "next/link";
import { loadCase, loadCases } from "@/lib/data";
import { buildCaseGraph } from "@/lib/graph";
import { usd } from "@/lib/format";
import { DataSourceBanner } from "@/components/DataSourceBanner";
import { TopNav } from "@/components/TopNav";
import { VerdictBadge, StatusBadge } from "@/components/Badges";
import { ProbabilityMeter } from "@/components/ProbabilityMeter";
import { RecommendationDelta } from "@/components/RecommendationDelta";
import { EvidenceList } from "@/components/EvidenceList";
import { SimilarCases } from "@/components/SimilarCases";
import { SarPanel } from "@/components/SarPanel";
import { InstrumentationStrip } from "@/components/InstrumentationStrip";
import { CaseGraphView } from "@/components/CaseGraphView";
import { RuleTrace } from "@/components/RuleTrace";
import { PrecedentPanel } from "@/components/PrecedentPanel";

export function generateStaticParams() {
  const { cases } = loadCases();
  return cases.map((c) => ({ case_id: c.case_id }));
}

export default async function CaseDetailPage(props: PageProps<"/cases/[case_id]">) {
  const { case_id } = await props.params;
  const { case: c, source } = loadCase(case_id);
  if (!c) notFound();

  // The answer schema does not carry the flagged card as a top-level field, so derive
  // a focal card from the connected set, falling back to a placeholder so a legitimate
  // case with no connections still renders a graph rather than an empty frame.
  const primaryCardId = c.case.connected_card_ids[0] ?? `${c.case_id}-CARD`;
  const graph = buildCaseGraph(c, primaryCardId);

  const pattern =
    c.case.pattern === "none" ? "no pattern identified" : c.case.pattern.replace(/_/g, " ");

  return (
    <>
      <DataSourceBanner source={source} />
      <TopNav />

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-7 sm:px-8">
        <Link
          href="/"
          className="readout mb-5 inline-flex items-center gap-1.5 text-[0.7rem] uppercase tracking-[0.12em] text-ink-faint transition-colors hover:text-phosphor"
        >
          <span aria-hidden>←</span> all cases
        </Link>

        {/* ── Masthead ────────────────────────────────────────────────────────
            The case id is set large in mono: it is an identifier, and treating it
            as one rather than as a heading is what makes this read as a record
            rather than a web page. */}
        <header className="instrument mb-6 overflow-hidden">
          <div className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[1fr_auto] lg:items-start">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="readout text-[2rem] font-medium leading-none text-bright">
                  {c.case_id}
                </h1>
                <VerdictBadge verdict={c.case.verdict} />
                <StatusBadge status={c.case.status} />
              </div>

              <p className="readout mt-2 text-[0.72rem] uppercase tracking-[0.13em] text-ink-faint">
                {pattern}
              </p>

              {c.case.pattern === "undocumented" && c.case.pattern_description && (
                <p className="mt-3 max-w-[68ch] text-[0.85rem] leading-relaxed text-ink">
                  {c.case.pattern_description}
                </p>
              )}

              <p className="mt-4 max-w-[68ch] text-[0.88rem] leading-relaxed text-ink">
                {c.case.summary}
              </p>

              <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-3">
                <Figure label="exposure" value={usd(c.case.exposure_usd)} />
                <Figure
                  label="affected txns"
                  value={String(c.case.affected_txn_ids.length)}
                />
                <Figure
                  label="connected cards"
                  value={String(c.case.connected_card_ids.length)}
                  emphasise={c.case.connected_card_ids.length > 2}
                />
                <Figure
                  label="prior cases cited"
                  value={String(c.case.similar_prior_cases.length)}
                />
              </dl>
            </div>

            {/* The reading. Given its own bay so it is never competing with prose. */}
            <div className="w-full border-t border-seam pt-5 lg:w-[22rem] lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
              <ProbabilityMeter value={c.case.fraud_probability} />
              <p className="mt-4 text-[0.76rem] leading-relaxed text-ink-dim">
                <span className="readout text-ink-faint">stop_reason — </span>
                {c.stop_reason}
              </p>
            </div>
          </div>
        </header>

        {/* ── The argument ───────────────────────────────────────────────────
            Recommendation history first: it is what the submission is judged on,
            and it is the part a reader should meet before the supporting detail. */}
        <div className="mb-6">
          <RecommendationDelta
            initial={c.next_best_actions.initial}
            final={c.next_best_actions.final}
            whatChanged={c.next_best_actions.what_changed}
            evidenceRequests={c.evidence_requests}
          />
        </div>

        {/* ── The graph ──────────────────────────────────────────────────────── */}
        <div className="mb-6">
          <CaseGraphView graph={graph} primaryCardId={primaryCardId} />
        </div>

        {/* ── The policy, evaluated ──────────────────────────────────────────
            Showing the rules that did NOT fire matters as much as the ones that
            did: it demonstrates the whole policy was evaluated, rather than an
            outcome being asserted. */}
        <div className="mb-6 grid gap-6 lg:grid-cols-2">
          <RuleTrace finalActions={c.next_best_actions.final} />
          <PrecedentPanel
            similarPriorCases={c.case.similar_prior_cases}
            evidence={c.case.evidence}
          />
        </div>

        {/* ── Supporting record ─────────────────────────────────────────────── */}
        <div className="mb-6 grid gap-6 lg:grid-cols-2">
          <EvidenceList evidence={c.case.evidence} />
          <SimilarCases caseAnswer={c} />
        </div>

        {c.sar.file && (
          <div className="mb-6">
            <SarPanel sar={c.sar} />
          </div>
        )}

        <InstrumentationStrip c={c} />
      </main>
    </>
  );
}

function Figure({
  label,
  value,
  emphasise,
}: {
  label: string;
  value: string;
  emphasise?: boolean;
}) {
  return (
    <div>
      <dt className="readout text-[0.62rem] uppercase tracking-[0.13em] text-ink-faint">
        {label}
      </dt>
      <dd
        className={`readout mt-1 text-[1.15rem] ${
          emphasise ? "text-hold glow-hold" : "text-bright"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
