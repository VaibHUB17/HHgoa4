export function usd(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

export function pct2(n: number): string {
  // Never imply more precision than the underlying float carries — always exactly 2 decimals.
  return n.toFixed(2);
}

export function probabilityBand(p: number): { label: string; tone: "fraud" | "clear" | "warn" } {
  if (p >= 0.85) return { label: "likely fraud", tone: "fraud" };
  if (p <= 0.15) return { label: "likely legitimate", tone: "clear" };
  return { label: "uncertain", tone: "warn" };
}
