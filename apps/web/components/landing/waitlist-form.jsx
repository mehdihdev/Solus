"use client";

import { useWaitlist } from "./waitlist-context";

const CONFIRMATION = "✓ You're on the list — we'll be in touch.";

export default function WaitlistForm({ variant = "hero" }) {
  const { email, isDone, hint, onEmailChange, submit } = useWaitlist();
  const isCta = variant === "cta";

  if (isDone) {
    return (
      <div className={isCta ? "ln-cta-done" : "ln-wl-done"}>{CONFIRMATION}</div>
    );
  }

  return (
    <>
      <div className={isCta ? "ln-cta-fields" : "ln-wl-fields"}>
        <input
          type="email"
          value={email}
          onChange={onEmailChange}
          placeholder="you@company.com"
          aria-label="Email address"
          className={`ln-wl-input is-${variant}`}
        />
        <button
          type="button"
          onClick={submit}
          className={`ln-wl-button is-${variant}`}
        >
          Join the waitlist
        </button>
      </div>
      {isCta ? <div className="ln-cta-hint">{hint}</div> : null}
    </>
  );
}
