import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 构建产物输出到 ../static，由 FastAPI 提供；开发时 /api 代理到后端
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../static", emptyOutDir: true },
  server: { port: 5176, proxy: { "/api": "http://127.0.0.1:8781" } },
});
