import styles from "./LoadingIndicator.module.css";

export function LoadingIndicator() {
  return (
    <div className={styles.wrapper} role="status" aria-live="polite">
      <span className={styles.dots} aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className={styles.label}>Searching jobs and generating an answer…</span>
    </div>
  );
}
