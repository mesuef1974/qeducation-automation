<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";

import { neo } from "@/api/neo";
import { useConfirm } from "@/composables/useConfirm";
import { THEME_LABEL, useTheme } from "@/composables/useTheme";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";
import { fmtWhen } from "@/utils/format";

const jobs = useJobsStore();
const classes = useClassesStore();
const { theme, next } = useTheme();
const confirm = useConfirm();

const openReview = computed(() => classes.openReview.date + classes.openReview.assign + classes.openReview.publish);
const loginQueued = computed(() => jobs.busy("login"));

// زر «سجّل الدخول» في تنبيه ويندوز يفتح الموقع بـ ?login=1 (الخطوة 0)
const route = useRoute();
const router = useRouter();
onMounted(async () => {
  await router.isReady();
  if (route.query.login !== "1") return;
  const query = { ...route.query };
  delete query.login;
  await router.replace({ query });
  await login();
});

/** مفتاح الإيقاف الآلي: تُعاد الكتابة على المنصة بعد أن يراجع المعلم السبب */
async function resume() {
  const ok = await confirm({
    title: "الكتابة على المنصة موقوفة",
    body: `${jobs.session?.halt_reason ?? ""} (منذ ${fmtWhen(jobs.session?.halted_at)}). `
      + "راجع السبب في «السجل» أو على المنصة أولًا. إعادة التفعيل تسمح بالكتابة والدورة الأسبوعية من جديد.",
    confirm: "أعد تفعيل الكتابة",
    danger: true,
  });
  if (!ok) return;
  await neo.resumeWrites();
  await jobs.refresh();
}

async function login() {
  const ok = await confirm({
    title: "تسجيل الدخول إلى المنصة",
    body: "سيفتح العامل نافذة متصفح على جهازك. سجّل الدخول فيها بنفسك، وتُغلق تلقائيًا عند الوصول إلى الصفحة الرئيسية.",
    confirm: "افتح نافذة الدخول",
  });
  if (ok) await jobs.enqueue("login");
}
</script>

<template>
  <div class="topbar">
    <div class="in">
      <RouterLink class="mark" to="/"><span class="mark-long">أتمتة منصة قطر للتعليم</span><span class="mark-short">أتمتة قطر</span></RouterLink>
      <nav aria-label="الأقسام">
        <RouterLink to="/">اليوم</RouterLink>
        <RouterLink to="/review">
          المراجعة <span v-if="openReview" class="count">{{ openReview }}</span>
        </RouterLink>
        <RouterLink to="/lessons">الدروس</RouterLink>
        <RouterLink to="/content">المحتوى</RouterLink>
        <RouterLink to="/live" class="live-link">
          <i class="live-dot" :class="{ on: jobs.session?.worker_busy, off: jobs.workerDown }" aria-hidden="true" />مباشر
        </RouterLink>
        <RouterLink to="/log">السجل</RouterLink>
        <RouterLink to="/swot">SWOT والأداء</RouterLink>
        <RouterLink to="/usage">الاستهلاك</RouterLink>
        <a href="/admin/">الإدارة</a>
      </nav>

      <button v-if="jobs.session?.halted" class="pill bad as-btn" :title="jobs.session.halt_reason" @click="resume">
        الكتابة موقوفة · راجع السبب
      </button>
      <span v-if="jobs.error" class="pill bad" :title="jobs.error">الخادم لا يستجيب</span>
      <span v-else-if="jobs.workerDown" class="pill warn" title="شغّل في الطرفية: cd backend && python manage.py neo_worker">
        العامل متوقف
      </span>
      <button v-else-if="jobs.session?.expired" class="pill bad as-btn" :disabled="loginQueued" @click="login">
        {{ loginQueued ? "نافذة الدخول مطلوبة" : "انتهت الجلسة · سجّل الدخول" }}
      </button>
      <span v-else-if="jobs.session?.worker_busy" class="pill read"><i class="spinner" aria-hidden="true" />العامل يعمل</span>
      <span v-else class="pill ok" :title="`آخر اتصال بالمنصة: ${fmtWhen(jobs.session?.checked_at)}`"><span class="sess">الجلسة سليمة</span></span>

      <button class="theme-toggle" data-vue type="button" :data-mode="theme" :aria-label="`الثيم: ${THEME_LABEL[theme]}. اضغط للتبديل`"
              @click="next">
        <svg class="i-auto" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="12" cy="12" r="9" /><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" />
        </svg>
        <svg class="i-light" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
             aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
        <svg class="i-dark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"
             aria-hidden="true">
          <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />
        </svg>
        <span>{{ THEME_LABEL[theme] }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.count {
  display: inline-grid; place-items: center; min-inline-size: 20px; block-size: 20px; padding-inline: 6px;
  border-radius: 999px; background: var(--brand); color: var(--on-brand); font-size: var(--fs-xs); margin-inline-start: 4px;
}
.as-btn { border: 0; cursor: pointer; font: inherit; font-family: var(--f-ui); font-size: var(--fs-sm); }
.live-link { display: inline-flex; align-items: center; gap: 6px; }
.live-dot { inline-size: 8px; block-size: 8px; border-radius: 50%; background: var(--ok); }
.live-dot.on { background: var(--brand); box-shadow: 0 0 0 0 var(--brand); animation: live-ping 1.4s infinite; }
.live-dot.off { background: var(--bad); }
@keyframes live-ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--brand) 60%, transparent); }
  100% { box-shadow: 0 0 0 8px transparent; } }
@media (prefers-reduced-motion: reduce) { .live-dot.on { animation: none; } }
.as-btn:disabled { cursor: default; opacity: .8; }
</style>
