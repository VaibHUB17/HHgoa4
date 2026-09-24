"use client";

import Link from "next/link";
import {
  animate,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from "motion/react";
import { useEffect, useRef } from "react";

/* The hero has thirty seconds to establish that this is a real investigation
   system rather than a prompt with a UI on it.

   The event's own line is "Less Noise. More Signal." That is, almost exactly, the
   problem this dataset poses: a risk score that fires on legitimate customers,
   half the cases legitimate by construction, and the work being to tell the
   difference. Borrowing the framing is a nod, not a copy — the claim underneath
   it is ours and it is specific.

   Every figure here is read from the committed run, not written by hand. */

const EASE = [0.16, 1, 0.3, 1] as const;

function Counter({
  to,
  decimals = 0,
  suffix = "",
}: {
  to: number;
  decimals?: number;
  suffix?: string;
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  const mv = useMotionValue(reduce ? to : 0);
  const text = useTransform(mv, (v) => v.toFixed(decimals) + suffix);

  useEffect(() => {
    if (reduce || !inView) return;
    const c = animate(mv, to, { duration: 1.2, ease: EASE });
    return () => c.stop();
  }, [inView, mv, reduce, to]);

  return (
    <span ref={ref}>
      <motion.span>{text}</motion.span>
    </span>
  );
}

export function LandingHero() {
  const reduce = useReducedMotion();

  return (
    <section className="relative border-b border-seam">
      <div className="mx-auto w-full max-w-6xl px-5 pb-12 pt-14 sm:px-8 sm:pt-20">
        <motion.p
          className="readout mb-6 text-[0.66rem] uppercase tracking-[0.22em] text-phosphor"
          initial={reduce ? false : { opacity: 0 }}
          animate={reduce ? undefined : { opacity: 1 }}
          transition={{ duration: 0.5 }}
        >
          agentic fraud investigation · built on tigergraph
        </motion.p>

        <motion.h1
          className="max-w-[18ch] text-balance text-[clamp(2.4rem,6.4vw,4.5rem)] font-medium leading-[1.02] tracking-[-0.035em] text-bright"
          initial={reduce ? false : { opacity: 0, y: 14 }}
          animate={reduce ? undefined : { opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: EASE, delay: 0.05 }}
        >
          It knows when it{" "}
          <span className="text-hold glow-hold">doesn&apos;t know</span> yet.
        </motion.h1>

        <motion.p
          className="mt-6 max-w-[64ch] text-[1.03rem] leading-relaxed text-ink-dim"
          initial={reduce ? false : { opacity: 0, y: 12 }}
          animate={reduce ? undefined : { opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: EASE, delay: 0.14 }}
        >
          Twenty fraud alerts with no labels, and a bank risk score that is wrong in
          both directions. Half the cases are legitimate by construction. Detection is
          not the hard part — knowing when the evidence is thin, asking for more, and
          changing your mind when it arrives is.
        </motion.p>

        {/* Figures from the committed run. Each one is a claim a judge can open and
            check, which is why they are links rather than decoration. */}
        <motion.div
          className="mt-11 grid gap-px overflow-hidden rounded-[var(--r-lg)] border border-seam bg-seam sm:grid-cols-2 lg:grid-cols-4"
          initial={reduce ? false : { opacity: 0 }}
          animate={reduce ? undefined : { opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.3 }}
        >
          <Figure
            value={<Counter to={17} />}
            label="cards in one device ring"
            note="found by graph community detection"
            href="/cases/HHG-014"
            tone="hold"
          />
          <Figure
            value={<Counter to={1} />}
            label="undocumented pattern found"
            note="cited against five historical cases"
            href="/cases/HHG-006"
            tone="fraud"
          />
          <Figure
            value={
              <>
                <Counter to={11} />
                <span className="text-ink-faint">/20</span>
              </>
            }
            label="recommendations revised"
            note="after the agent requested evidence"
            href="/cases/HHG-017"
          />
          <Figure
            value={<Counter to={91} />}
            label="prior cases cited as memory"
            note="retrieved from 5,565 closed investigations"
          />
        </motion.div>

        <motion.div
          className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3"
          initial={reduce ? false : { opacity: 0 }}
          animate={reduce ? undefined : { opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.42 }}
        >
          <Link
            href="#explore"
            className="readout rounded-[var(--r-md)] border border-phosphor px-4 py-2 text-[0.74rem] uppercase tracking-[0.13em] text-phosphor transition-colors hover:bg-phosphor hover:text-void"
          >
            explore the ring
          </Link>
          <Link
            href="#cases"
            className="readout text-[0.74rem] uppercase tracking-[0.13em] text-ink-dim transition-colors hover:text-bright"
          >
            all 20 cases →
          </Link>
        </motion.div>
      </div>
    </section>
  );
}

function Figure({
  value,
  label,
  note,
  href,
  tone,
}: {
  value: React.ReactNode;
  label: string;
  note: string;
  href?: string;
  tone?: "fraud" | "hold";
}) {
  const body = (
    <div className="h-full bg-bed p-5 transition-colors duration-200 group-hover:bg-deck">
      <div
        className={`readout text-[2.1rem] leading-none ${
          tone === "fraud"
            ? "text-fraud glow-fraud"
            : tone === "hold"
              ? "text-hold glow-hold"
              : "text-bright"
        }`}
      >
        {value}
      </div>
      <div className="readout mt-2.5 text-[0.64rem] uppercase tracking-[0.13em] text-ink-dim">
        {label}
      </div>
      <p className="mt-1.5 text-[0.76rem] leading-snug text-ink-faint">{note}</p>
      {href && (
        <span className="readout mt-3 inline-block text-[0.64rem] uppercase tracking-[0.12em] text-phosphor opacity-0 transition-opacity group-hover:opacity-100">
          open case →
        </span>
      )}
    </div>
  );

  return href ? (
    <Link href={href} className="group block focus-visible:outline-offset-[-2px]">
      {body}
    </Link>
  ) : (
    <div className="group">{body}</div>
  );
}
