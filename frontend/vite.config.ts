import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// خادم Django المحلي؛ أثناء التطوير يمرَّر إليه /api و/admin و/static
const BACKEND = "http://127.0.0.1:8765";

export default defineConfig({
  base: "/app/",
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // هوية المشروع: المصدر الوحيد للألوان والخطوط والثيم
      "@brand": fileURLToPath(new URL("../docs/assets", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    fs: { allow: [".."] },
    proxy: { "/api": BACKEND, "/admin": BACKEND, "/static": BACKEND },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
