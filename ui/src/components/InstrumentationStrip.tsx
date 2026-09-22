import type { CaseAnswer } from "@/lib/types";

export function InstrumentationStrip({ c }: { c: CaseAnswer }) {
  const items: [string, string][] = [
    ["Stop reason", c.stop_reason],
    ["Tool calls", String(c.tool_calls)],
    ["Tokens", c.tokens.toLocaleString("en-US")],
    ["Latency", `${c.latency_s.toFixed(1)}s`],
  ];
  return (
    <div className="flex flex-wrap items-start gap-x-6 gap-y-2 rounded-lg border border-line bg-panel/60 px-4 py-2.5 text-xs">
      {items.map(([label, value]) => (
        <div key={label} className={label === "Stop reason" ? "max-w-md flex-1" : ""}>
          <span className="mr-1.5 font-data uppercase tracking-wide text-faint">{label}</span>
          <span className={label === "Stop reason" ? "text-dim" : "font-data text-paper"}>
            {value}
          </span>
        </div>
      ))}
    </div>
  );
}
