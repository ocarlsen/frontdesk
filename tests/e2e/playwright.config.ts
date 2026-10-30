import { defineConfig, devices } from "@playwright/test";

// Chromium only, in two shapes: a desktop window and an iPhone 15 (touch, mobile viewport and
// user agent). This is Chromium emulating a phone, not iOS Safari.
export default defineConfig({
  testDir: ".",
  globalSetup: "./global-setup.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: { trace: "retain-on-failure" },
  projects: [
    {
      name: "desktop",
      testMatch: /desktop\..*\.spec\.ts/,
      use: { browserName: "chromium", viewport: { width: 1280, height: 800 } },
    },
    {
      name: "iphone",
      testMatch: /iphone\..*\.spec\.ts/,
      use: { ...devices["iPhone 15"], browserName: "chromium" },
    },
  ],
});
