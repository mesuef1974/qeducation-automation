import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// خادم Django المحلي؛ أثناء التطوير يمرَّر إليه /api و/admin و/static و/docs
const BACKEND = "http://127.0.0.1:8777";

// منطق الثيم ومناطق التمرير مصدره الوحيد docs/assets (theme.js وscroll-regions.js): يُدمجان في <head> كما في صفحات docs
// (الثيم قبل الرسم بلا وميض)
const SHARED = ["theme.js", "scroll-regions.js"];
const inlineTheme = () => ({
  name: "inline-shared-scripts",
  transformIndexHtml: (html: string) =>
    html.replace("<!--theme-core-->",
      SHARED.map((f) => `<script>${readFileSync(fileURLToPath(new URL(`../docs/assets/${f}`, import.meta.url)), "utf-8")}</script>`)
        .join(String.fromCharCode(10))),
});

export default defineConfig({
  base: "/app/",
  plugins: [vue(), inlineTheme()],
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
    proxy: { "/api": BACKEND, "/admin": BACKEND, "/static": BACKEND, "/docs": BACKEND },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
