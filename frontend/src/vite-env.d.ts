/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_SHOW_DEBUG_SOURCES?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
