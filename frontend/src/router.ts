import { createRouter, createWebHistory } from "vue-router";

const SITE = "أتمتة منصة قطر للتعليم";

// كل شاشة تُحمَّل عند أول زيارة لها (Lazy loading)
export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/", name: "today", component: () => import("@/views/TodayView.vue"), meta: { title: "اليوم" } },
    { path: "/review/:kind(date|assign|publish)?", name: "review", component: () => import("@/views/ReviewView.vue"),
      meta: { title: "المراجعة" } },
    { path: "/lessons", name: "lessons", component: () => import("@/views/LessonsView.vue"), meta: { title: "الدروس" } },
    { path: "/log", name: "log", component: () => import("@/views/LogView.vue"), meta: { title: "السجل" } },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · ${SITE}` : SITE;
});
