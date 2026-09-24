import Link from "next/link";

export function TopNav() {
  return (
    <header className="border-b border-seam px-6 py-3.5">
      <div className="mx-auto flex max-w-6xl items-center justify-between">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="font-display text-lg text-bright">HHGoa</span>
          <span className="readout text-xs uppercase tracking-widest text-ink-faint">
            Case Console
          </span>
        </Link>
        <span className="readout text-[11px] text-ink-faint">Fraud Investigation Agent</span>
      </div>
    </header>
  );
}
