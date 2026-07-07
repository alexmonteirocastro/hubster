import { type FormEvent, useState } from "react";
import styles from "./ChatInput.module.css";

interface ChatInputProps {
  onSubmit: (question: string) => void;
  disabled: boolean;
}

export function ChatInput({ onSubmit, disabled }: ChatInputProps) {
  const [question, setQuestion] = useState("");

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
        disabled={disabled}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            handleSubmit(event);
          }
        }}
      />
      <button type="submit" className={styles.button} disabled={disabled || !question.trim()}>
        Ask
      </button>
    </form>
  );
}
