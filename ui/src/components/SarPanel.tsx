import type { SarRecord } from "@/lib/types";
import { usd } from "@/lib/format";

export function SarPanel({ sar }: { sar: SarRecord }) {
  if (!sar.file) return null;
  return (
    <div className="rounded-xl border border-fraud/30 bg-fraud/5 p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-display text-lg italic text-paper">Suspicious Activity Report</h3>
        <span className="rounded border border-fraud/40 bg-fraud/10 px-2 py-0.5 font-data text-[10px] uppercase tracking-wide text-fraud">
          Filing required
        </span>
      </div>
      <p className="mb-4 text-xs text-dim">{sar.reason}</p>
      <p className="mb-4 whitespace-pre-wrap text-sm leading-relaxed text-paper/90">
        {sar.narrative}
      </p>
      <div className="grid grid-cols-2 gap-4 border-t border-line-hi pt-3 sm:grid-cols-4">
        <div>
          <p className="font-data text-[10px] uppercase tracking-wide text-faint">Amount</p>
          <p className="font-data text-sm text-paper">{usd(sar.total_amount_usd)}</p>
        </div>
        <div>
          <p className="font-data text-[10px] uppercase tracking-wide text-faint">Activity dates</p>
          <p className="font-data text-sm text-paper">
            {sar.activity_dates.length === 2 ? `${sar.activity_dates[0]} to ${sar.activity_dates[1]}` : "—"}
          </p>
        </div>
        <div className="col-span-2 sm:col-span-2">
          <p className="font-data text-[10px] uppercase tracking-wide text-faint">Subjects</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {sar.subjects.map((s) => (
              <span key={s} className="rounded bg-panel-hi px-1.5 py-0.5 font-data text-xs text-dim">
                {s}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
