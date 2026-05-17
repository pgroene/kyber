import { defineConfig } from "vitest/config";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const mockPath = path.resolve(__dirname, "tests/mocks/codemirror-bundle.js");

export default defineConfig({
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
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["kyber-panel.js", "src/**/*.js"],
      exclude: ["src/styles.js"],
    },
  },
});
