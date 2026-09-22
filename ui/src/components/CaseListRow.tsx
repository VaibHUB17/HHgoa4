import Link from "next/link";
import type { CaseAnswer } from "@/lib/types";
import { usd } from "@/lib/format";
import { VerdictBadge, StatusBadge } from "./Badges";
import { ProbabilityMeter } from "./ProbabilityMeter";

export function CaseListRow({ c }: { c: CaseAnswer }) {
  return (
    <Link
      href={`/cases/${c.case_id}`}
      className="group grid grid-cols-[110px_1fr_170px_120px_140px] items-center gap-4 rounded-lg border border-line px-4 py-3 transition-colors hover:border-line-hi hover:bg-panel focus-visible:outline-2 focus-visible:outline-signal"
    >
      <span className="font-data text-sm text-paper">{c.case_id}</span>

      <div className="min-w-0">
        <p className="truncate text-sm text-paper">
          {c.case.pattern === "none" ? "No pattern" : c.case.pattern.replace(/_/g, " ")}
        </p>
        <p className="mt-0.5 truncate text-xs text-faint">{c.case.summary}</p>
      </div>

      <div className="w-full">
        <ProbabilityMeter value={c.case.fraud_probability} size="compact" />
      </div>

      <span className="font-data text-sm text-paper">{usd(c.case.exposure_usd)}</span>

      <div className="flex flex-col items-start gap-1.5">
        <VerdictBadge verdict={c.case.verdict} />
        <StatusBadge status={c.case.status} />
      </div>
    </Link>
  );
}
