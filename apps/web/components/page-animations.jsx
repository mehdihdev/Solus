"use client";

import { useLayoutEffect } from "react";
import Lenis from "lenis";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

export default function PageAnimations() {
  useLayoutEffect(() => {
    const lenis = new Lenis({
      lerp: 0.1,
      smoothWheel: true,
    });

    const onTick = (time) => {
      lenis.raf(time * 1000);
    };

    lenis.on("scroll", ScrollTrigger.update);
    gsap.ticker.add(onTick);
    gsap.ticker.lagSmoothing(0);

    const ctx = gsap.context(() => {
      const hasEnteredViewport = (element, threshold) =>
        element.getBoundingClientRect().top <= window.innerHeight * threshold;

      // Clear any inline state left by a previous client-side visit before
      // calculating the next reveal state.
      gsap.set(
        [
          "[data-reveal-lines] .rl > span",
          "[data-fade-up]",
          "[data-stagger] > *",
          ".line-sep",
          ".product-mockup",
        ],
        { clearProps: "all" },
      );

      gsap.utils.toArray("[data-reveal-lines]").forEach((element) => {
        const lines = element.querySelectorAll(".rl > span");

        if (hasEnteredViewport(element, 0.86)) {
          gsap.set(lines, { yPercent: 0 });
          return;
        }

        gsap.set(lines, { yPercent: 112 });
        gsap.to(lines, {
          scrollTrigger: {
            trigger: element,
            start: "top 86%",
            once: true,
          },
          yPercent: 0,
          duration: 0.9,
          stagger: 0.08,
          ease: "expo.out",
        });
      });

      gsap.utils.toArray("[data-fade-up]").forEach((element) => {
        if (hasEnteredViewport(element, 0.88)) {
          gsap.set(element, { opacity: 1, y: 0 });
          return;
        }

        gsap.fromTo(
          element,
          { opacity: 0, y: 20 },
          {
            scrollTrigger: {
              trigger: element,
              start: "top 88%",
              once: true,
            },
            opacity: 1,
            y: 0,
            duration: 0.7,
            ease: "power3.out",
          },
        );
      });

      gsap.utils.toArray("[data-stagger]").forEach((container) => {
        const children = [...container.children];

        if (hasEnteredViewport(container, 0.84)) {
          gsap.set(children, { opacity: 1, y: 0 });
          return;
        }

        gsap.fromTo(
          children,
          { opacity: 0, y: 28 },
          {
            scrollTrigger: {
              trigger: container,
              start: "top 84%",
              once: true,
            },
            opacity: 1,
            y: 0,
            duration: 0.65,
            stagger: 0.08,
            ease: "power3.out",
          },
        );
      });

      gsap.utils.toArray(".line-sep").forEach((element) => {
        if (hasEnteredViewport(element, 0.92)) {
          gsap.set(element, { scaleX: 1, transformOrigin: "left center" });
          return;
        }

        gsap.fromTo(
          element,
          {
            scaleX: 0,
            transformOrigin: "left center",
          },
          {
            scrollTrigger: {
              trigger: element,
              start: "top 92%",
              once: true,
            },
            scaleX: 1,
            duration: 1.1,
            ease: "expo.out",
          },
        );
      });

      gsap.to(".product-mockup", {
        scrollTrigger: {
          trigger: ".product-mockup-wrap",
          start: "top bottom",
          end: "bottom top",
          scrub: 1.2,
        },
        y: -40,
        ease: "none",
      });

      ScrollTrigger.refresh();
    });

    return () => {
      ctx.revert();
      lenis.destroy();
      gsap.ticker.remove(onTick);
    };
  }, []);

  return null;
}
