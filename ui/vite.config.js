import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const page = name => fileURLToPath(new URL(name, import.meta.url));

export default defineConfig({
  base: "/projects/",
  plugins: [react()],
  // Escape Markdown hard-break spaces instead of emitting trailing bundle whitespace.
  esbuild: { supported: { 'template-literal': false } },
  build: {
    outDir: "../static/projects",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    // previs-solver.html: the 3D Stage's plan code for the server's headless browser (SPEC_20 R27, R28).
    rollupOptions: { input: { index: page("./index.html"), solver: page("./previs-solver.html") } },
  },
});
