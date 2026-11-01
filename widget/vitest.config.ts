import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    environmentOptions: { jsdom: { url: "https://host.test/" } },
    include: ["src/**/__tests__/**/*.test.ts"],
  },
});
