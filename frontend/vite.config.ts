import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "url";

const frontendDir = path.resolve(fileURLToPath(new URL(".", import.meta.url)));
const repoRoot = path.resolve(frontendDir, "..");
const apiTarget = process.env.GALLERY_API_URL || "http://127.0.0.1:8787";

export default defineConfig({
  root: frontendDir,
  publicDir: path.resolve(frontendDir, "public"),
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(frontendDir, "src"),
      "@webppt/html-to-pptx": path.resolve(
        repoRoot,
        "packages/html-to-pptx/src/index.ts",
      ),
    },
  },
  css: {
    postcss: path.resolve(frontendDir, "postcss.config.js"),
    preprocessorOptions: {
      less: {
        javascriptEnabled: true,
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      "/embed": { target: apiTarget, changeOrigin: true },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      "/embed": { target: apiTarget, changeOrigin: true },
    },
  },
  optimizeDeps: {
    include: ["lodash", "zustand"],
  },
  build: {
    outDir: path.resolve(frontendDir, "dist"),
    emptyOutDir: true,
    sourcemap: true,
  },
});
