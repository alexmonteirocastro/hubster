import { type FormEvent, useState } from "react";
import { CHAT_QUESTION_MAX_LENGTH } from "../api/client";
import styles from "./ChatInput.module.css";

interface ChatInputProps {
  onSubmit: (question: string) => void;
  disabled: boolean;
}

/** Flag the counter when the input is within the last 10% of the limit. */
const NEAR_LIMIT_RATIO = 0.9;

export function ChatInput({ onSubmit, disabled }: ChatInputProps) {
  const [question, setQuestion] = useState("");
  const used = question.length;
  const nearLimit = used >= Math.floor(CHAT_QUESTION_MAX_LENGTH * NEAR_LIMIT_RATIO);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || disabled) {
      return;
    }
    onSubmit(trimmed);
    setQuestion("");
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.field}>
        <label htmlFor="chat-question" className={styles.srOnly}>
          Ask a question about jobs
        </label>
        <textarea
          id="chat-question"
          className={styles.input}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="e.g. Frontend developer roles in Sweden"
          rows={2}
          maxLength={CHAT_QUESTION_MAX_LENGTH}
          disabled={disabled}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSubmit(event);
            }
          }}
        />
        <p
          className={`${styles.counter}${nearLimit ? ` ${styles.counterNearLimit}` : ""}`}
          aria-live="polite"
        >
          {used}/{CHAT_QUESTION_MAX_LENGTH}
        </p>
      </div>
      <button type="submit" className={styles.button} disabled={disabled || !question.trim()}>
        Ask
      </button>
    </form>
  );
}
