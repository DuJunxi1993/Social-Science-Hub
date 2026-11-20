import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri 开发时把前端跑在 5173，Rust 侧通过 devUrl 连过来。
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    watch: {
      // Rust 侧改动由 cargo 自己管，这里只盯前端。
      ignored: ["**/src-tauri/**"],
    },
  },
  build: {
    target: "es2021",
    sourcemap: false,
  },
});
