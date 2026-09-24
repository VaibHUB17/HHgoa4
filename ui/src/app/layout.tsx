import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

/* Geist Sans + Geist Mono, one family in two cuts rather than a serif/sans
   pairing. This surface is almost entirely labels, IDs, amounts and scores, and
   product UI does not need a display face — a well-tuned sans carries headings,
   buttons and body alike. The mono is doing signal work, not decoration: it is
   what makes a probability or a transaction id read as measured data.
   Geist over JetBrains Mono deliberately; JetBrains is now the everywhere
   default and reads as the unconsidered choice. */

export const metadata: Metadata = {
  title: "Case Console — Fraud Investigation",
  description:
    "Analyst console for an agentic fraud investigation: evidence, graph relationships, recommendation history and the approval gate.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
      style={
        {
          "--font-body-face": "var(--font-geist-sans)",
          "--font-data-face": "var(--font-geist-mono)",
          "--font-display-face": "var(--font-geist-sans)",
        } as React.CSSProperties
      }
    >
      <body className="min-h-full">
        <div id="app-root" className="flex min-h-dvh flex-col">
          {children}
        </div>
      </body>
    </html>
  );
}
