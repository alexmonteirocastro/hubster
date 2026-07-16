import ReactMarkdown, { type Components } from "react-markdown";
import type { ChatSource } from "../api/types";
import { SourceList } from "./SourceList";
import styles from "./ChatMessage.module.css";

const assistantMarkdownComponents: Components = {
  a: ({ href, children, ...props }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
      {children}
    </a>
  ),
};

export interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
  generated?: boolean;
  isError?: boolean;
}

interface ChatMessageProps {
  message: DisplayMessage;
}

/**
 * Explicit env gate — do not use import.meta.env.PROD / DEV
 * (same reasoning as ADR-0009 Decision 5's VITE_SHOW_DEBUG_SOURCES;
 * see ADR-0009 implementation note for this flag's own rationale / ALE-155).
 * Default true when unset.
 */
function isShowSourcesEnabled(): boolean {
  return import.meta.env.VITE_SHOW_SOURCES !== "false";
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";
  const sources = !isUser ? message.sources : undefined;
  const showSources = isShowSourcesEnabled() && Boolean(sources?.length);

  return (
    <article
      className={`${styles.message} ${isUser ? styles.user : styles.assistant} ${message.isError ? styles.error : ""}`}
      aria-label={isUser ? "Your message" : "Assistant reply"}
    >
      {isUser ? (
        <p className={styles.content}>{message.content}</p>
      ) : (
        <div className={styles.contentMarkdown}>
          <ReactMarkdown
            disallowedElements={["img"]}
            components={assistantMarkdownComponents}
          >
            {message.content}
          </ReactMarkdown>
        </div>
      )}
      {!isUser && message.generated === false && !message.isError && (
        <p className={styles.badge}>No matching jobs — answer from search, not generated</p>
      )}
      {showSources && sources && <SourceList sources={sources} />}
    </article>
  );
}
