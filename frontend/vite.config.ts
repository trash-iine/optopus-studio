import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `npm run dev` serves the app on :5173 and forwards the API to the backend on :8765.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8765", ws: true } },
  },
  // ECharts is most of the bundle; the app is served locally, so one chunk is fine.
  build: { chunkSizeWarningLimit: 2000 },
  test: { environment: "jsdom" },
});
