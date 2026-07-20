import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, Vite proxies /api -> the FastAPI backend on :8001.
// In prod, Caddy routes /api -> backend, so the frontend always calls relative /api.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8001",
    },
  },
});
