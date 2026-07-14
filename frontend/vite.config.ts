import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Dev-only proxy timeout — local Ollama generation can exceed 3 minutes on CPU (ALE-111). */
const DEV_PROXY_TIMEOUT_MS = 600_000;

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
        timeout: DEV_PROXY_TIMEOUT_MS,
      },
    },
  },
});
