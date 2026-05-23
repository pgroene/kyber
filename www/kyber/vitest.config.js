import { defineConfig } from "vitest/config";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const wwwSrc = path.resolve(repoRoot, "custom_components/kyber/www");
const mockPath = path.resolve(__dirname, "tests/mocks/codemirror-bundle.js");

export default defineConfig({
  resolve: {
    alias: {
      // Map a simple alias to the canonical JS source location
      "kyber-www": wwwSrc,
    },
  },
  server: {
    fs: {
      // Allow Vite to serve files outside the default root (www/kyber)
      allow: [repoRoot],
    },
  },
  plugins: [
    {
      // Intercept the codemirror-bundle import before Vite tries to parse the real 373KB bundle
      name: "mock-codemirror-bundle",
      enforce: "pre",
      resolveId(id) {
        if (id.endsWith("codemirror-bundle.js")) {
          return mockPath;
        }
      },
    },
  ],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.js"],
    // Exclude Playwright UI specs — those are run separately via `npm run test:ui`
    exclude: ["tests/ui/**", "**/node_modules/**"],
    // Use forks pool to isolate test files; each worker gets its own process so
    // timer-based teardown races between test files are avoided.
    pool: "forks",
    teardownTimeout: 10000,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: [`${wwwSrc}/kyber-panel.js`, `${wwwSrc}/src/**/*.js`],
      exclude: [`${wwwSrc}/src/styles.js`],
    },
  },
});
