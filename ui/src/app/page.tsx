import { loadCases } from "@/lib/data";
import { DataSourceBanner } from "@/components/DataSourceBanner";
import { TopNav } from "@/components/TopNav";
import { VerdictFilter } from "@/components/VerdictFilter";

export default function CaseListPage() {
  const { cases, source } = loadCases();

  return (
    <>
      <DataSourceBanner source={source} />
      <TopNav />
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        <div className="mb-6">
          <h1 className="font-display text-2xl italic text-paper">Case list</h1>
          <p className="mt-1 text-sm text-dim">
            {cases.length} case{cases.length === 1 ? "" : "s"} investigated. Filter by verdict,
            open a case for the full record.
          </p>
        </div>
        <VerdictFilter cases={cases} />
      </main>
    </>
  );
}
