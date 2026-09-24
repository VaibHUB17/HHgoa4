"use client";

import { motion, useReducedMotion } from "motion/react";

// template.tsx re-mounts on every navigation (unlike layout.tsx), which is exactly what a
// list <-> detail transition needs: a fresh mount animation each time the route changes,
// without touching either page. Kept to opacity + a small y-shift — no layout animation
// across routes, so it can't jank against the fixed header strip on the detail page.
export default function Template({ children }: { children: React.ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? undefined : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={reduce ? { duration: 0 } : { duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}
