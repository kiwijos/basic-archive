import { defineConfig } from "vite";

// For local development only: `npm run dev` forwards API calls to the cluster's Ingress.
export default defineConfig({
  server: {
    proxy: { "/api": process.env.ARCHIVE_URL ?? "http://localhost" },
  },
});
