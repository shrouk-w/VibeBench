import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 300_000,
  use: {
    baseURL: process.env.VB_BASE_URL ?? "http://localhost:8080",
    browserName: "chromium",
  },
  workers: 1,
  reporter: "list",
  webServer:
    process.env.VB_PLAYWRIGHT_START === "1"
      ? {
          command: "pnpm dev --hostname 127.0.0.1 --port 8080",
          url: "http://localhost:8080",
          wait: { stdout: /Ready/ },
        }
      : undefined,
});
