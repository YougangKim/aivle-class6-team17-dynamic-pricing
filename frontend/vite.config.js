import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  /* 상대 경로 빌드 — GitHub Pages 하위 경로, S3, Netlify 어디에 올려도 동작 */
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    // 백엔드 붙일 때 주석 해제
    // proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
});
