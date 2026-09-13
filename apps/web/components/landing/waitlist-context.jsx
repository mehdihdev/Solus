"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";

const DEFAULT_HINT = "No spam — one email when your invite is ready.";
const INVALID_HINT = "Please enter a valid email address.";
const NETWORK_HINT =
  "We could not reach the server. Please check your connection and try again.";
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const WaitlistContext = createContext(null);

/**
 * Holds the waitlist state shared by the hero form and the closing CTA form —
 * submitting either one flips both, matching the source design.
 *
 * `honeypot` is bound to an off-screen field that humans never see; the server
 * silently discards any submission that fills it.
 */
export function WaitlistProvider({ children }) {
  const [email, setEmail] = useState("");
  const [honeypot, setHoneypot] = useState("");
  const [isDone, setIsDone] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [hint, setHint] = useState(DEFAULT_HINT);
  const [hasError, setHasError] = useState(false);
  const inFlight = useRef(false);

  const onEmailChange = useCallback((event) => {
    setEmail(event.target.value);
  }, []);

  const onHoneypotChange = useCallback((event) => {
    setHoneypot(event.target.value);
  }, []);

  const submit = useCallback(async () => {
    if (inFlight.current) {
      return;
    }

    const normalizedEmail = email.trim();

    // Validate before the network call, exactly as the source design does.
    if (!EMAIL_PATTERN.test(normalizedEmail)) {
      setHint(INVALID_HINT);
      setHasError(true);
      return;
    }

    inFlight.current = true;
    setIsSubmitting(true);
    setHasError(false);

    try {
      const response = await fetch("/api/waitlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: normalizedEmail, company: honeypot }),
      });

      const payload = await response.json().catch(() => null);

      if (!response.ok) {
        setHint(payload?.message ?? INVALID_HINT);
        setHasError(true);
        return;
      }

      setIsDone(true);
    } catch {
      setHint(NETWORK_HINT);
      setHasError(true);
    } finally {
      inFlight.current = false;
      setIsSubmitting(false);
    }
  }, [email, honeypot]);

  const value = useMemo(
    () => ({
      email,
      honeypot,
      isDone,
      isSubmitting,
      hint,
      hasError,
      onEmailChange,
      onHoneypotChange,
      submit,
    }),
    [
      email,
      honeypot,
      isDone,
      isSubmitting,
      hint,
      hasError,
      onEmailChange,
      onHoneypotChange,
      submit,
    ],
  );

  return (
    <WaitlistContext.Provider value={value}>
      {children}
    </WaitlistContext.Provider>
  );
}

export function useWaitlist() {
  const waitlist = useContext(WaitlistContext);

  if (!waitlist) {
    throw new Error("useWaitlist must be used inside a WaitlistProvider");
  }

  return waitlist;
}
