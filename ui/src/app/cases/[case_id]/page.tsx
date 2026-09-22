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

export function generateStaticParams() {
  const { cases } = loadCases();
  return cases.map((c) => ({ case_id: c.case_id }));
}

export default async function CaseDetailPage(props: PageProps<"/cases/[case_id]">) {
  const { case_id } = await props.params;
  const { case: c, source } = loadCase(case_id);
  if (!c) notFound();

  // Primary card id: cards mentioned in evidence/connected list aren't the flagged card
  // itself in the answer schema, so derive it from the first affected transaction's card
  // where available, falling back to the first connected card, else a placeholder built
  // from the case id so the graph view still renders something for a legitimate case.
  const primaryCardId = c.case.connected_card_ids[0] ?? `${c.case_id}-CARD`;
  const graph = buildCaseGraph(c, primaryCardId);

  return (
    <>
      <DataSourceBanner source={source} />
      <TopNav />
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
        <Link href="/" className="mb-4 inline-block text-xs text-dim hover:text-paper">
          &larr; All cases
        </Link>

        {/* Header strip */}
        <div className="mb-8 rounded-xl border border-line-hi bg-panel p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="font-display text-2xl italic text-paper">{c.case_id}</h1>
              <p className="mt-0.5 text-sm text-dim">
                {c.case.pattern === "none" ? "No pattern identified" : c.case.pattern.replace(/_/g, " ")}
                {c.case.pattern === "undocumented" && c.case.pattern_description
                  ? ` — ${c.case.pattern_description}`
                  : ""}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <VerdictBadge verdict={c.case.verdict} />
              <StatusBadge status={c.case.status} />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-5 sm:grid-cols-[1fr_auto]">
            <ProbabilityMeter value={c.case.fraud_probability} />
            <div className="text-right">
              <p className="font-data text-[10px] uppercase tracking-wide text-faint">Exposure</p>
              <p className="font-data text-xl text-paper">{usd(c.case.exposure_usd)}</p>
            </div>
          </div>

          <p className="mt-4 border-t border-line pt-4 text-sm leading-relaxed text-paper/90">
            {c.case.summary}
          </p>
        </div>

        {/* Recommendation delta — signature view */}
        <section className="mb-8">
          <h2 className="mb-4 font-display text-lg italic text-paper">
            Recommendation: before &amp; after evidence
          </h2>
          <RecommendationDelta
            initial={c.next_best_actions.initial}
            final={c.next_best_actions.final}
            whatChanged={c.next_best_actions.what_changed}
            evidenceRequests={c.evidence_requests}
          />
        </section>

        {/* Evidence */}
        <section className="mb-8">
          <h2 className="mb-3 font-display text-lg italic text-paper">Evidence</h2>
          <EvidenceList evidence={c.case.evidence} />
        </section>

        {/* Graph view */}
        <section className="mb-8">
          <CaseGraphView graph={graph} />
        </section>

        {/* Similar prior cases */}
        <section className="mb-8">
          <h2 className="mb-3 font-display text-lg italic text-paper">Similar prior cases</h2>
          <SimilarCases caseAnswer={c} />
        </section>

        {/* SAR */}
        {c.sar.file && (
          <section className="mb-8">
            <SarPanel sar={c.sar} />
          </section>
        )}

        {/* Instrumentation */}
        <section>
          <InstrumentationStrip c={c} />
        </section>
      </main>
    </>
  );
}
