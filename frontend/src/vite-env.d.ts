/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_SHOW_SOURCES?: string;
  readonly VITE_SHOW_DEBUG_SOURCES?: string;
  readonly VITE_LOADING_MESSAGE?: string;
  readonly VITE_CHAT_REQUEST_TIMEOUT_MS?: string;
  readonly VITE_CHAT_QUESTION_MAX_LENGTH?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
