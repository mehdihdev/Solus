"use client";

import { useEffect, useState } from "react";

const WORDS = ["Hardware", "Software", "Electrical", "Simulation"];
const CYCLE_MS = 4500;
const FADE_MS = 380;

export default function CyclingWord() {
  const [index, setIndex] = useState(0);
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    let fadeTimer;

    const cycle = setInterval(() => {
      setIsVisible(false);
      fadeTimer = setTimeout(() => {
        setIndex((current) => (current + 1) % WORDS.length);
        setIsVisible(true);
      }, FADE_MS);
    }, CYCLE_MS);

    return () => {
      clearInterval(cycle);
      clearTimeout(fadeTimer);
    };
  }, []);

  return (
    <span
      className="ln-how-word"
      style={{
        opacity: isVisible ? 1 : 0,
        transform: isVisible ? "translateY(0)" : "translateY(-8px)",
      }}
    >
      {WORDS[index]}
    </span>
  );
}
