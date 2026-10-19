import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/projects/",
  plugins: [react()],
  // Escape Markdown hard-break spaces instead of emitting trailing bundle whitespace.
  esbuild: { supported: { 'template-literal': false } },
  build: {
    outDir: "../static/projects",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
});
