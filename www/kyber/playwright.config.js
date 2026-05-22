import { defineConfig, devices } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");

export default defineConfig({
  testDir: "./tests/ui",
  outputDir: "./screenshots",
  snapshotDir: "./tests/ui/snapshots",

  use: {
    baseURL: "http://localhost:7878",
    // Always capture a screenshot — saved to outputDir
    screenshot: "on",
    // Record a video on failure for extra context
    video: "retain-on-failure",
    // Give the panel time to render
    actionTimeout: 10_000,
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Use system Chromium on Alpine Linux (musl libc); falls back to
        // Playwright's downloaded binary on glibc systems (e.g. ubuntu CI).
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
          : {},
      },
    },
  ],

  // Serve the repo root so tests can access both www/ and custom_components/kyber/www/
  webServer: {
    command: `npx serve ${repoRoot} -p 7878 --no-clipboard`,
    port: 7878,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
