import { useCallback, useRef, useState } from "react";
import { ApiHttpError, ApiNetworkError, postChat } from "../api/client";
import { ChatInput } from "./ChatInput";
import { ChatMessage, type DisplayMessage } from "./ChatMessage";
import { LoadingIndicator } from "./LoadingIndicator";
import styles from "./Chat.module.css";

function nextMessageId(): string {
  return crypto.randomUUID();
}

export function Chat() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      const el = listRef.current;
      if (el && typeof el.scrollTo === "function") {
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      }
    });
  }, []);

  const handleSubmit = useCallback(
    async (question: string) => {
      const userMessage: DisplayMessage = {
        id: nextMessageId(),
        role: "user",
        content: question,
      };

      setMessages((prev) => [...prev, userMessage]);
      setIsLoading(true);
      scrollToBottom();

      try {
        const response = await postChat({ question });
        const assistantMessage: DisplayMessage = {
          id: nextMessageId(),
          role: "assistant",
          content: response.answer,
          sources: response.sources,
          generated: response.generated,
        };
        setMessages((prev) => [...prev, assistantMessage]);
      } catch (error) {
        const content =
          error instanceof ApiNetworkError || error instanceof ApiHttpError
            ? error.message
            : "Something went wrong. Please try again.";
        const errorMessage: DisplayMessage = {
          id: nextMessageId(),
          role: "assistant",
          content,
          isError: true,
        };
        setMessages((prev) => [...prev, errorMessage]);
      } finally {
        setIsLoading(false);
        scrollToBottom();
      }
    },
    [scrollToBottom],
  );

  return (
    <div className={styles.chat}>
      <div className={styles.messages} ref={listRef} aria-live="polite">
        {messages.length === 0 && !isLoading && (
          <p className={styles.empty}>
            Ask about Nordic and European startup jobs — for example, &ldquo;backend engineer in
            Denmark&rdquo; or &ldquo;remote frontend roles in Sweden&rdquo;.
          </p>
        )}
        {messages.map((message) => (
          <ChatMessage key={message.id} message={message} />
        ))}
        {isLoading && <LoadingIndicator />}
      </div>
      <ChatInput onSubmit={handleSubmit} disabled={isLoading} />
    </div>
  );
}
