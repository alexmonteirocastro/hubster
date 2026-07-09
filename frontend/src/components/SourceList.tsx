import type { ChatSource } from "../api/types";
import styles from "./SourceList.module.css";

interface SourceListProps {
  sources: ChatSource[];
  variant?: "compact" | "debug";
}

function formatScore(score: number): string {
  return score.toFixed(2);
}

function isDebugSourcesEnabled(): boolean {
  const value = import.meta.env.VITE_SHOW_DEBUG_SOURCES;
  return value === "true";
}

function resolveVariant(variant: SourceListProps["variant"]): "compact" | "debug" {
  if (variant) {
    return variant;
  }
  return isDebugSourcesEnabled() ? "debug" : "compact";
}

export function SourceList({ sources, variant }: SourceListProps) {
  if (sources.length === 0) {
    return null;
  }

  const resolvedVariant = resolveVariant(variant);

  if (resolvedVariant === "debug") {
    return (
      <div className={`${styles.wrapper} ${styles.debug}`}>
        <p className={styles.heading}>Retrieved sources</p>
        <ul className={styles.list}>
          {sources.map((source) => (
            <li key={source.job_id} className={styles.item}>
              <div className={styles.header}>
                <a
                  className={styles.role}
                  href={source.job_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {source.job_title ?? source.job_role}
                </a>
                <span className={styles.score}>score {formatScore(source.score)}</span>
              </div>
              {(source.company || source.location || source.country) && (
                <p className={styles.meta}>
                  {[source.company, source.location, source.country]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              )}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className={`${styles.wrapper} ${styles.compact}`}>
      <p className={styles.heading}>Sources</p>
      <ul className={styles.chipList}>
        {sources.map((source) => (
          <li key={source.job_id} className={styles.chip}>
            <a
              className={styles.chipLink}
              href={source.job_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {source.job_title ?? source.job_role}
            </a>
            <span className={styles.chipScore}>{formatScore(source.score)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
