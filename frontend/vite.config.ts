import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const target = env.EKIP_API_PROXY_TARGET || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/health": { target, changeOrigin: true },
        "/documents": { target, changeOrigin: true },
        "/query": { target, changeOrigin: true },
      },
    },
    test: {
      environment: "jsdom",
      clearMocks: true,
    },
  };
});
