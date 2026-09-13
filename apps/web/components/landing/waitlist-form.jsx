"use client";

import { useWaitlist } from "./waitlist-context";

const CONFIRMATION = "✓ You're on the list — we'll be in touch.";

export default function WaitlistForm({ variant = "hero" }) {
  const {
    email,
    honeypot,
    isDone,
    isSubmitting,
    hint,
    hasError,
    onEmailChange,
    onHoneypotChange,
    submit,
  } = useWaitlist();
  const isCta = variant === "cta";

  if (isDone) {
    return (
      <div className={isCta ? "ln-cta-done" : "ln-wl-done"}>{CONFIRMATION}</div>
    );
  }

  const onSubmit = (event) => {
    event.preventDefault();
    submit();
  };

  // The source design shows the hint only under the CTA form. The hero keeps
  // that layout until there is an error to report, so the default rendering is
  // unchanged and a hero-side failure is still visible.
  const showHint = isCta || hasError;

  return (
    <form
      className={isCta ? "ln-cta-form" : "ln-wl-form"}
      onSubmit={onSubmit}
      noValidate
    >
      <div className={isCta ? "ln-cta-fields" : "ln-wl-fields"}>
        <input
          type="email"
          name="email"
          value={email}
          onChange={onEmailChange}
          placeholder="you@company.com"
          aria-label="Email address"
          aria-invalid={hasError || undefined}
          autoComplete="email"
          disabled={isSubmitting}
          className={`ln-wl-input is-${variant}`}
        />
        <input
          type="text"
          name="company"
          value={honeypot}
          onChange={onHoneypotChange}
          className="ln-wl-honeypot"
          tabIndex={-1}
          autoComplete="off"
          aria-hidden="true"
        />
        <button
          type="submit"
          disabled={isSubmitting}
          aria-busy={isSubmitting || undefined}
          className={`ln-wl-button is-${variant}`}
        >
          Join the waitlist
        </button>
      </div>
      {showHint ? (
        <div
          className={`${isCta ? "ln-cta-hint" : "ln-hero-hint"}${hasError ? " is-error" : ""}`}
          role={hasError ? "alert" : undefined}
        >
          {hint}
        </div>
      ) : null}
    </form>
  );
}
