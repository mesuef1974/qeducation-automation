// هوية المشروع أولًا (الألوان والثيم والمكوّنات المشتركة مع صفحات docs)، ثم أنماط التطبيق
import "@brand/tokens.css";
import "@brand/pages.css";
import "@brand/components.css";
import "./styles/app.css";

import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { router } from "./router";

createApp(App).use(createPinia()).use(router).mount("#app");
