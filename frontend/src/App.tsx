import { useCallback, useEffect, useState } from "react";
import { setUnauthorizedHandler } from "./api/client";
import { hasStoredApiKey } from "./api/authStorage";
import { ApiKeyModal } from "./components/ApiKeyModal";
import { Chat } from "./components/Chat";
import { LockIcon } from "./components/LockIcon";
import styles from "./App.module.css";

export default function App() {
  const [hasApiKey, setHasApiKey] = useState(() => hasStoredApiKey());
  const [isModalOpen, setIsModalOpen] = useState(() => !hasStoredApiKey());

  const openModal = useCallback(() => {
    setIsModalOpen(true);
  }, []);

  const handleAuthRequired = useCallback(() => {
    setHasApiKey(false);
    setIsModalOpen(true);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(handleAuthRequired);
    return () => setUnauthorizedHandler(null);
  }, [handleAuthRequired]);

  return (
    <div className={styles.app}>
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>Hubster</h1>
          <button
            type="button"
            className={styles.lockButton}
            onClick={openModal}
            aria-label={hasApiKey ? "Change API key" : "Enter API key"}
          >
            <LockIcon locked={!hasApiKey} />
          </button>
        </div>
        <p className={styles.subtitle}>Job search assistant for Nordic &amp; European startups</p>
        <p className={styles.notice}>
          Each question is answered independently — the assistant does not remember previous
          messages. Follow-up questions like &ldquo;any others?&rdquo; won&apos;t work.
        </p>
      </header>
      <main className={styles.main}>
        <Chat />
      </main>
      <ApiKeyModal
        isOpen={isModalOpen}
        allowDismiss={hasApiKey}
        onClose={() => setIsModalOpen(false)}
        onVerified={() => setHasApiKey(true)}
      />
    </div>
  );
}
