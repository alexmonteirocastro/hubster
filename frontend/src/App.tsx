import { Chat } from "./components/Chat";
import styles from "./App.module.css";

export default function App() {
  return (
    <div className={styles.app}>
      <header className={styles.header}>
        <h1 className={styles.title}>Hubster</h1>
        <p className={styles.subtitle}>Job search assistant for Nordic &amp; European startups</p>
        <p className={styles.notice}>
          Each question is answered independently — the assistant does not remember previous
          messages. Follow-up questions like &ldquo;any others?&rdquo; won&apos;t work.
        </p>
      </header>
      <main className={styles.main}>
        <Chat />
      </main>
    </div>
  );
}
