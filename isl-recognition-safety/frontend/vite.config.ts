import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies REST and WebSocket traffic to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/ws": { target: "http://localhost:8000", ws: true, changeOrigin: true },
    },
  },
  build: {
    target: "es2020",
    sourcemap: false,
    chunkSizeWarningLimit: 4000,
  },
});
