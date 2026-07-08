import type { ChatSource } from "../api/types";
import styles from "./SourceList.module.css";

interface SourceListProps {
  sources: ChatSource[];
}

function formatScore(score: number): string {
  return score.toFixed(2);
}

export function SourceList({ sources }: SourceListProps) {
  if (sources.length === 0) {
    return null;
  }

  return (
    <div className={styles.wrapper}>
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
                {[source.company, source.location, source.country].filter(Boolean).join(" · ")}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
