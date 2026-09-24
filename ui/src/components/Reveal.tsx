"use client";

import { motion, useReducedMotion } from "motion/react";

/* Scroll-triggered reveal, the same mechanism the event's own site uses —
   Framer Motion driving opacity and a small translate off an IntersectionObserver,
   with no smooth-scroll library and no WebGL. Cheap, and it suits the argument:
   each section resolves into view rather than being simply present.

   `whileInView` with `once` so a section settles and stays settled; re-animating
   on every scroll pass is the thing that makes reveal choreography feel cheap.
   Content is visible by default under reduced motion — the reveal enhances an
   already-rendered default rather than gating it, so nothing ships blank. */
export function Reveal({
  children,
  delay = 0,
}: {
  children: React.ReactNode;
  delay?: number;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className="mt-8">{children}</div>;

  return (
    <motion.div
      className="mt-8"
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.65, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}
