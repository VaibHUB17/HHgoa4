"use client";

import Link from "next/link";
import { useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";

// Minimal, on purpose: chrome should not compete with the case data beneath
// it. The one motion cue is the bottom hairline gaining weight and warming
// toward the phosphor tone as the page scrolls — a cheap, honest signal that
// content is moving underneath a fixed instrument bezel. Written straight to
// the element's style on scroll, no setState, so it costs nothing per frame.
export function TopNav() {
  const headerRef = useRef<HTMLElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    const el = headerRef.current;
    if (!el || reduce) return;
    let ticking = false;
    const update = () => {
      ticking = false;
      const depth = Math.min(window.scrollY / 120, 1);
      el.style.setProperty("--nav-seam", depth.toString());
    };
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [reduce]);

  return (
    <header ref={headerRef} className="nav-seam px-6 py-3.5">
      <div className="mx-auto flex max-w-6xl items-center justify-between">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="font-display text-lg text-bright">Tracewise</span>
          <span className="readout text-xs uppercase tracking-widest text-ink-faint">
            Case Console
          </span>
        </Link>
        <span className="readout text-[11px] text-ink-faint">Fraud Investigation Agent</span>
      </div>
    </header>
  );
}
