import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    globalSetup: ["test/build-site.ts"],
    testTimeout: 30_000,
    hookTimeout: 180_000,
  },
});
