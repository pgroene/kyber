import { defineConfig } from "vite";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  build: {
    lib: {
      entry: path.resolve(__dirname, "src/kyber-panel.js"),
      name: "KyberPanel",
      fileName: () => "kyber-panel.js",
      formats: ["es"],
    },
    outDir: ".",
    emptyOutDir: false,
    rollupOptions: {
      // codemirror-bundle is served separately — treat as external
      external: [/codemirror-bundle/],
      output: {
        // Preserve the external import path as-is
        paths: { "./codemirror-bundle.js": "./codemirror-bundle.js" },
      },
    },
  },
});
