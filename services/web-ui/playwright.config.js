import { defineConfig } from "@playwright/test";

// Runs against the deployed cluster, not a dev server: `make e2e` sets ARCHIVE_URL.
export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.ARCHIVE_URL ?? "http://localhost",
    browserName: "chromium",
  },
});
