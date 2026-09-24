"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion, animate } from "motion/react";
import type { CaseAnswer } from "@/lib/types";

// Tool calls / tokens / latency are the agent's own receipts — ticking them up on mount
// reads as "these are measured, live values" rather than static labels. Reduced motion
// renders the final number immediately.
function CountUp({ to, decimals = 0, suffix = "" }: { to: number; decimals?: number; suffix?: string }) {
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(reduce ? to : 0);
  const started = useRef(false);

  useEffect(() => {
    if (reduce || started.current) return;
    started.current = true;
    const controls = animate(0, to, {
      duration: 0.9,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [to, reduce]);

  return (
    <>
      {display.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
      {suffix}
    </>
  );
}

export function InstrumentationStrip({ c }: { c: CaseAnswer }) {
  const reduce = useReducedMotion();
  const items: { label: string; node: React.ReactNode }[] = [
    { label: "Stop reason", node: c.stop_reason },
    { label: "Tool calls", node: <CountUp to={c.tool_calls} /> },
    { label: "Tokens", node: <CountUp to={c.tokens} /> },
    { label: "Latency", node: <CountUp to={c.latency_s} decimals={1} suffix="s" /> },
  ];
  return (
    <motion.div
      initial={reduce ? undefined : { opacity: 0, y: 6 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-20px" }}
      transition={reduce ? { duration: 0 } : { duration: 0.35 }}
      className="flex flex-wrap items-start gap-x-6 gap-y-2 rounded-lg border border-line bg-panel/60 px-4 py-2.5 text-xs"
    >
      {items.map(({ label, node }) => (
        <div key={label} className={label === "Stop reason" ? "max-w-md flex-1" : ""}>
          <span className="mr-1.5 font-data uppercase tracking-wide text-faint">{label}</span>
          <span className={label === "Stop reason" ? "text-dim" : "font-data text-paper tabular-nums"}>
            {node}
          </span>
        </div>
      ))}
    </motion.div>
  );
}
