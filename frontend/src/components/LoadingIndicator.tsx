import styles from "./LoadingIndicator.module.css";

/** Default matches local Ollama-aware copy; production overrides via VITE_LOADING_MESSAGE. */
const DEFAULT_LOADING_MESSAGE =
  "Searching jobs and generating an answer… Local models may take a few minutes.";

function resolveLoadingMessage(): string {
  const configured = import.meta.env.VITE_LOADING_MESSAGE;
  if (typeof configured === "string" && configured.trim() !== "") {
    return configured;
  }
  return DEFAULT_LOADING_MESSAGE;
}

export function LoadingIndicator() {
  return (
    <div className={styles.wrapper} role="status" aria-live="polite">
      <span className={styles.dots} aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className={styles.label}>{resolveLoadingMessage()}</span>
    </div>
  );
}
