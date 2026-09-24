import { loadCases } from "@/lib/data";
import { DataSourceBanner } from "@/components/DataSourceBanner";
import { TopNav } from "@/components/TopNav";
import { VerdictFilter } from "@/components/VerdictFilter";
import { LandingHero } from "@/components/LandingHero";
import { RingExplorer } from "@/components/RingExplorer";
import { CaseReplay } from "@/components/CaseReplay";
import { PolicySandbox } from "@/components/PolicySandbox";
import { buildReplayCases } from "@/lib/replayData";

/* The landing page has to answer one question in the first thirty seconds: is this
   a real investigation system, or a prompt with a dashboard bolted on?

   Description cannot settle that. So each section below hands the viewer something
   to operate: drag the ring apart, scrub the investigation, move the evidence and
   watch the policy engine recompute. Everything is driven by the committed run and
   by a faithful port of the real scoring code, so anything a judge pokes at holds
   up rather than degrading into a mock. */

export default function LandingPage() {
  const { cases, source } = loadCases();
  // The ring explorer is driven by the real HHG-014 record, not a fixture.
  const ringCase = cases.find((c) => c.case_id === "HHG-014") ?? cases[0];
  const replayCases = buildReplayCases(cases);

  const counts = { fraud: 0, legitimate: 0, uncertain: 0 };
  for (const c of cases) counts[c.case.verdict]++;

  return (
    <>
      <DataSourceBanner source={source} />
      <TopNav />

      <LandingHero />

      {/* ── Drag the ring apart ─────────────────────────────────────────── */}
      <Section
        id="explore"
        eyebrow="the evidence a row-based model cannot see"
        title="One handset. Seventeen cards. Eighteen customers."
        lede="Community detection over the card-to-device subgraph returned a connected component spanning seventeen other cards. A model scoring one payment in isolation cannot reach the second customer — this is two hops. Drag any node; the layout responds."
      >
        {ringCase && <RingExplorer caseAnswer={ringCase} />}
      </Section>

      {/* ── Scrub the investigation ─────────────────────────────────────── */}
      <Section
        id="replay"
        eyebrow="the agent changing its mind"
        title="Watch the recommendation move when evidence arrives."
        lede="The brief requires the next best action recorded before evidence is requested and after it returns, because that is what separates an investigation from a classifier. Scrub the timeline and find the moment it flips."
      >
        <CaseReplay cases={replayCases} />
      </Section>

      {/* ── Operate the policy engine ───────────────────────────────────── */}
      <Section
        id="policy"
        eyebrow="deterministic, and checkable"
        title="The decision is a rule engine, not a model's opinion."
        lede="Probability comes from a weighted evidence ledger; actions come from the bank's own ten rules. Toggle the evidence and move the exposure — the numbers below are computed by a faithful port of the same code that produced the twenty answer files, matching it to four decimal places."
      >
        <PolicySandbox />
      </Section>

      {/* ── The cases ───────────────────────────────────────────────────── */}
      <section id="cases" className="border-t border-seam">
        <div className="mx-auto w-full max-w-6xl px-5 py-14 sm:px-8">
          <p className="readout mb-3 text-[0.64rem] uppercase tracking-[0.18em] text-phosphor">
            the benchmark
          </p>
          <h2 className="max-w-[24ch] text-balance text-[clamp(1.6rem,3.4vw,2.35rem)] font-medium leading-tight tracking-[-0.025em] text-bright">
            Twenty cases. Ten of them legitimate.
          </h2>
          <p className="mt-4 max-w-[62ch] text-[0.95rem] leading-relaxed text-ink-dim">
            An agent that blocks everything scores badly, and the dataset is built to
            punish exactly that. Half these alerts are ordinary customers. Open any case
            for the full record: evidence with provenance, the precedent retrieved, the
            rules that fired, and the approval route.
          </p>

          <div className="mt-8 grid grid-cols-3 gap-px overflow-hidden rounded-[var(--r-lg)] border border-seam bg-seam sm:max-w-md">
            <Tally label="fraud" value={counts.fraud} tone="fraud" />
            <Tally label="legitimate" value={counts.legitimate} tone="clear" />
            <Tally label="uncertain" value={counts.uncertain} tone="hold" />
          </div>

          <div className="mt-8">
            <VerdictFilter cases={cases} />
          </div>
        </div>
      </section>

      <footer className="border-t border-seam">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-6 sm:px-8">
          <p className="readout text-[0.66rem] uppercase tracking-[0.14em] text-ink-faint">
            hacker house goa · agentic fraud investigation
          </p>
          <p className="readout flex items-center gap-2 text-[0.66rem] uppercase tracking-[0.14em] text-ink-faint">
            <span aria-hidden className="h-px w-6" style={{ background: "var(--tg)" }} />
            built on tigergraph
          </p>
        </div>
      </footer>
    </>
  );
}

function Section({
  id,
  eyebrow,
  title,
  lede,
  children,
}: {
  id: string;
  eyebrow: string;
  title: string;
  lede: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="border-t border-seam">
      <div className="mx-auto w-full max-w-6xl px-5 py-14 sm:px-8">
        <p className="readout mb-3 text-[0.64rem] uppercase tracking-[0.18em] text-phosphor">
          {eyebrow}
        </p>
        <h2 className="max-w-[26ch] text-balance text-[clamp(1.6rem,3.4vw,2.35rem)] font-medium leading-tight tracking-[-0.025em] text-bright">
          {title}
        </h2>
        <p className="mt-4 max-w-[68ch] text-[0.95rem] leading-relaxed text-ink-dim">{lede}</p>
        <div className="mt-8">{children}</div>
      </div>
    </section>
  );
}

function Tally({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "fraud" | "clear" | "hold";
}) {
  const cls =
    tone === "fraud" ? "text-fraud" : tone === "clear" ? "text-clear" : "text-hold";
  return (
    <div className="bg-bed px-4 py-3">
      <div className={`readout text-[1.6rem] leading-none ${cls}`}>{value}</div>
      <div className="readout mt-1.5 text-[0.6rem] uppercase tracking-[0.13em] text-ink-faint">
        {label}
      </div>
    </div>
  );
}
