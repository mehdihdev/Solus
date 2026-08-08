"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export default function WaitlistTrigger({
  className = "",
  label,
  variant = "plain",
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [email, setEmail] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [toastMessage, setToastMessage] = useState("");
  const [isMounted, setIsMounted] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isOpen) {
      document.body.style.overflow = "";
      return undefined;
    }

    document.body.style.overflow = "hidden";
    inputRef.current?.focus();

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };

    window.addEventListener("keydown", onKeyDown);

    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!toastMessage) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setToastMessage("");
    }, 4200);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [toastMessage]);

  const openModal = () => {
    setErrorMessage("");
    setIsOpen(true);
  };

  const closeModal = () => {
    setErrorMessage("");
    setIsOpen(false);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const nextEmail = email.trim();

    if (!nextEmail) {
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");

    try {
      const response = await fetch("/api/waitlist", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email: nextEmail,
        }),
      });

      const payload = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(payload?.message || "Unable to join the waitlist.");
      }

      setEmail("");
      closeModal();
      setToastMessage(
        payload?.message || "Thanks for joining the Solus waitlist.",
      );
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Unable to join the waitlist right now.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const trigger =
    variant === "cta" ? (
      <button
        type="button"
        className={`cta ${className}`.trim()}
        onClick={openModal}
      >
        {label}
      </button>
    ) : (
      <button type="button" className={className} onClick={openModal}>
        {label}
      </button>
    );

  return (
    <>
      {trigger}

      {isMounted && isOpen
        ? createPortal(
            <div className="modal-backdrop" onClick={closeModal}>
              <div
                className="waitlist-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="waitlist-title"
                onClick={(event) => event.stopPropagation()}
              >
                <button
                  type="button"
                  className="modal-close"
                  onClick={closeModal}
                  aria-label="Close waitlist modal"
                >
                  ×
                </button>
                <p className="modal-eyebrow">Solus</p>
                <h2 id="waitlist-title">Join the waitlist</h2>
                <p className="modal-copy">
                  Enter your email and we&apos;ll reach out when Solus is ready
                  for early access.
                </p>
                <form className="waitlist-form" onSubmit={handleSubmit}>
                  <label className="sr-only" htmlFor="waitlist-email">
                    Email address
                  </label>
                  <input
                    ref={inputRef}
                    id="waitlist-email"
                    type="email"
                    name="email"
                    placeholder="you@company.com"
                    autoComplete="email"
                    value={email}
                    disabled={isSubmitting}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                  />
                  <button
                    type="submit"
                    className="cta modal-submit"
                    disabled={isSubmitting}
                  >
                    {isSubmitting
                      ? "Joining waitlist..."
                      : "Join early access waitlist"}
                  </button>
                </form>
                {errorMessage ? (
                  <p className="modal-error">{errorMessage}</p>
                ) : null}
              </div>
            </div>,
            document.body,
          )
        : null}

      {isMounted && toastMessage
        ? createPortal(
            <div className="waitlist-toast" role="status" aria-live="polite">
              <span>{toastMessage}</span>
              <button
                type="button"
                className="waitlist-toast-close"
                aria-label="Dismiss waitlist message"
                onClick={() => setToastMessage("")}
              >
                ×
              </button>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
