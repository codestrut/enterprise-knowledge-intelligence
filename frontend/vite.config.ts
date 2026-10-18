import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const target = env.EKIP_API_PROXY_TARGET || "http://127.0.0.1:8001";
  const targetUrl = new URL(target);

  if (
    targetUrl.protocol !== "http:" ||
    targetUrl.port !== "8001" ||
    !["127.0.0.1", "localhost", "[::1]"].includes(targetUrl.hostname) ||
    targetUrl.pathname !== "/" ||
    targetUrl.search !== "" ||
    targetUrl.hash !== ""
  ) {
    throw new Error("The EKIP Vite dev proxy requires an isolated loopback API at http://127.0.0.1:8001.");
  }

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": {
          target,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api(?=\/|$)/, ""),
        },
      },
    },
    test: {
      environment: "jsdom",
      clearMocks: true,
      include: ["src/**/*.{test,spec}.{ts,tsx}"],
    },
  };
});
