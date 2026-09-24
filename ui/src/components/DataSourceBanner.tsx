"use client";

import { motion, useReducedMotion } from "motion/react";
import type { DataSource } from "@/lib/data";

export function DataSourceBanner({ source }: { source: DataSource }) {
  const reduce = useReducedMotion();
  if (source === "real") return null;
  return (
    <motion.div
      role="status"
      initial={reduce ? undefined : { height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      transition={reduce ? { duration: 0 } : { duration: 0.3 }}
      className="w-full overflow-hidden border-b border-warn/30 bg-warn/10 px-4 py-1.5 text-center font-data text-xs uppercase tracking-wide text-warn"
    >
      Fixture data — cases/ not found, showing 3 sample cases from ui/fixtures/
    </motion.div>
  );
}
