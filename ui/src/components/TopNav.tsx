import Link from "next/link";

export function TopNav() {
  return (
    <header className="border-b border-line px-6 py-3.5">
      <div className="mx-auto flex max-w-6xl items-center justify-between">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="font-display text-lg italic text-paper">HHGoa</span>
          <span className="font-data text-xs uppercase tracking-widest text-faint">
            Case Console
          </span>
        </Link>
        <span className="font-data text-[11px] text-faint">Fraud Investigation Agent</span>
      </div>
    </header>
  );
}
