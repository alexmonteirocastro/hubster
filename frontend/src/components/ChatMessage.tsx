import type { ChatSource } from "../api/types";
import { SourceList } from "./SourceList";
import styles from "./ChatMessage.module.css";

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

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <article
      className={`${styles.message} ${isUser ? styles.user : styles.assistant} ${message.isError ? styles.error : ""}`}
      aria-label={isUser ? "Your message" : "Assistant reply"}
    >
      <p className={styles.content}>{message.content}</p>
      {!isUser && message.generated === false && !message.isError && (
        <p className={styles.badge}>No matching jobs — answer from search, not generated</p>
      )}
      {!isUser && message.sources && message.sources.length > 0 && (
        <SourceList sources={message.sources} />
      )}
    </article>
  );
}
