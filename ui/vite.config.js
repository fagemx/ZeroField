import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/projects/",
  plugins: [react()],
  build: {
    outDir: "../static/projects",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
});
