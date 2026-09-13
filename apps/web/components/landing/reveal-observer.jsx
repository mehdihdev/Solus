"use client";

import { useEffect } from "react";

/* Matches the source design's trigger point: reveal once the element's top
   crosses 92% of the viewport height. */
const ROOT_MARGIN = "0px 0px -8% 0px";
const VISIBLE_CLASS = "is-visible";

export default function RevealObserver() {
  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll(".ln-reveal"));

    if (nodes.length === 0) {
      return undefined;
    }

    if (typeof IntersectionObserver === "undefined") {
      nodes.forEach((node) => node.classList.add(VISIBLE_CLASS));
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) {
            return;
          }

          entry.target.classList.add(VISIBLE_CLASS);
          observer.unobserve(entry.target);
        });
      },
      { rootMargin: ROOT_MARGIN },
    );

    nodes.forEach((node) => observer.observe(node));

    return () => observer.disconnect();
  }, []);

  return null;
}
