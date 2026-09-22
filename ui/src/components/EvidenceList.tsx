import type { EvidenceItem } from "@/lib/types";
import { SourceBadge } from "./Badges";

export function EvidenceList({ evidence }: { evidence: EvidenceItem[] }) {
  if (evidence.length === 0) {
    return <p className="text-sm text-faint">No evidence recorded.</p>;
  }
  return (
    <ul className="space-y-2">
      {evidence.map((e, i) => (
        <li key={i} className="rounded-lg border border-line-hi bg-panel-hi px-3 py-2.5">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm text-paper">{e.claim}</p>
            <SourceBadge source={e.source} />
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-faint">
            <span className="font-data">{e.ref}</span>
            {e.entity_ids.length > 0 && (
              <span className="flex flex-wrap gap-1">
                {e.entity_ids.map((id) => (
                  <span
                    key={id}
                    className="rounded bg-slate px-1.5 py-0.5 font-data text-dim"
                  >
                    {id}
                  </span>
                ))}
              </span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
