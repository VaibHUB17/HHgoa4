import { loadCases } from "@/lib/data";
import { DataSourceBanner } from "@/components/DataSourceBanner";
import { TopNav } from "@/components/TopNav";
import { VerdictFilter } from "@/components/VerdictFilter";

export default function CaseListPage() {
  const { cases, source } = loadCases();

  const counts = { fraud: 0, legitimate: 0, uncertain: 0 };
  let exposure = 0;
  for (const c of cases) {
    counts[c.case.verdict]++;
    exposure += c.case.exposure_usd;
  }

  return (
    <>
      <DataSourceBanner source={source} />
      <TopNav />
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        <div className="mb-6">
          <h1 className="font-display text-2xl text-bright">Case list</h1>
          <p className="mt-1 text-sm text-ink-dim">
            {cases.length} case{cases.length === 1 ? "" : "s"} investigated. Filter by verdict,
            open a case for the full record.
          </p>
        </div>

        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="instrument px-4 py-3">
            <p className="readout text-[10px] uppercase tracking-wide text-ink-faint">Fraud</p>
            <p className="glow-fraud readout mt-1 text-2xl">{counts.fraud}</p>
          </div>
          <div className="instrument px-4 py-3">
            <p className="readout text-[10px] uppercase tracking-wide text-ink-faint">Legitimate</p>
            <p className="readout mt-1 text-2xl text-clear">{counts.legitimate}</p>
          </div>
          <div className="instrument px-4 py-3">
            <p className="readout text-[10px] uppercase tracking-wide text-ink-faint">Uncertain</p>
            <p className="readout mt-1 text-2xl text-hold">{counts.uncertain}</p>
          </div>
          <div className="instrument px-4 py-3">
            <p className="readout text-[10px] uppercase tracking-wide text-ink-faint">Total exposure</p>
            <p className="readout mt-1 text-2xl text-bright">
              {exposure.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}
            </p>
          </div>
        </div>

        <VerdictFilter cases={cases} />
      </main>
    </>
  );
}
