"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

const DEFAULT_HINT = "No spam — one email when your invite is ready.";
const INVALID_HINT = "Please enter a valid email address.";
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const WaitlistContext = createContext(null);

/**
 * Holds the waitlist state shared by the hero form and the closing CTA form —
 * submitting either one flips both, matching the source design.
 */
export function WaitlistProvider({ children }) {
  const [email, setEmail] = useState("");
  const [isDone, setIsDone] = useState(false);
  const [hint, setHint] = useState(DEFAULT_HINT);

  const onEmailChange = useCallback((event) => {
    setEmail(event.target.value);
  }, []);

  const submit = useCallback(() => {
    if (!EMAIL_PATTERN.test(email.trim())) {
      setHint(INVALID_HINT);
      return;
    }

    setIsDone(true);
  }, [email]);

  const value = useMemo(
    () => ({ email, isDone, hint, onEmailChange, submit }),
    [email, isDone, hint, onEmailChange, submit],
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
