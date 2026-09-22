import type { DataSource } from "@/lib/data";

export function DataSourceBanner({ source }: { source: DataSource }) {
  if (source === "real") return null;
  return (
    <div
      role="status"
      className="w-full border-b border-warn/30 bg-warn/10 px-4 py-1.5 text-center font-data text-xs uppercase tracking-wide text-warn"
    >
      Fixture data — cases/ not found, showing 3 sample cases from ui/fixtures/
    </div>
  );
}
