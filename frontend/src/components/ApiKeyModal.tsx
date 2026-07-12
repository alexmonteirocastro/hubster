import { type FormEvent, useEffect, useId, useState } from "react";
import { ApiHttpError, ApiNetworkError, verifyApiKey } from "../api/client";
import { setStoredApiKey } from "../api/authStorage";
import styles from "./ApiKeyModal.module.css";

type ModalPhase = "entry" | "success";

interface ApiKeyModalProps {
  isOpen: boolean;
  onClose: () => void;
  onVerified: () => void;
}

export function ApiKeyModal({ isOpen, onClose, onVerified }: ApiKeyModalProps) {
  const titleId = useId();
  const inputId = useId();
  const [apiKey, setApiKey] = useState("");
  const [phase, setPhase] = useState<ModalPhase>("entry");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) {
      setApiKey("");
      setPhase("entry");
      setErrorMessage(null);
      setIsSubmitting(false);
    }
  }, [isOpen]);

  if (!isOpen) {
    return null;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = apiKey.trim();
    if (!trimmed) {
      setErrorMessage("Enter an API key before submitting.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      await verifyApiKey(trimmed);
      setStoredApiKey(trimmed);
      onVerified();
      setPhase("success");
    } catch (error) {
      if (error instanceof ApiHttpError && error.status === 401) {
        setErrorMessage(error.message || "That API key was rejected.");
      } else if (error instanceof ApiNetworkError) {
        setErrorMessage(error.message);
      } else if (error instanceof ApiHttpError) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("Something went wrong. Please try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className={styles.backdrop}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <h2 id={titleId} className={styles.title}>
          API access
        </h2>

        {phase === "success" ? (
          <>
            <p className={styles.success}>
              API key verified. You can use Hubster for this browser session.
            </p>
            <button type="button" className={styles.button} onClick={onClose}>
              Close
            </button>
          </>
        ) : (
          <>
            <p className={styles.description}>
              Enter your Hubster API key to use the chat and job search endpoints.
            </p>
            <form className={styles.form} onSubmit={handleSubmit}>
              <label htmlFor={inputId} className={styles.label}>
                API key
              </label>
              <input
                id={inputId}
                className={styles.input}
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                disabled={isSubmitting}
              />
              {errorMessage && (
                <p className={styles.error} role="alert">
                  {errorMessage}
                </p>
              )}
              <button type="submit" className={styles.button} disabled={isSubmitting}>
                {isSubmitting ? "Verifying…" : "Submit"}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
