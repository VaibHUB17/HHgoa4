import type { Metadata } from "next";
import { Fraunces, Inter_Tight, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// Fraunces is a variable font; asking for several weights AND both styles makes
// Turbopack's next/font resolver fail with "queries have exactly one entry". The
// italic face was never used, so requesting normal only keeps the display face and
// lets the dev server boot.
const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["500", "600"],
});

const interTight = Inter_Tight({
  variable: "--font-inter-tight",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "HHGoa Case Console",
  description: "Fraud investigation case console — case review, evidence, and approval gate.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${interTight.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-slate text-paper">{children}</body>
    </html>
  );
}
