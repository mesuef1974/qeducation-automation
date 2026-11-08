<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";

import AppTopbar from "@/components/AppTopbar.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import JobDock from "@/components/JobDock.vue";
import { useScrollRegions } from "@/composables/useScrollRegions";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";

useScrollRegions();
const jobs = useJobsStore();
const classes = useClassesStore();
let off: (() => void) | undefined;
let bar: ResizeObserver | undefined;

onMounted(() => {
  jobs.refresh();
  classes.load();
  // كل مهمة تنتهي قد تغيّر الملخصات (اقتراح جديد، تطبيق، تحقق)
  off = jobs.onFinished(() => classes.load());
  // ارتفاع الشريط العلوي الفعلي (يلتف على سطرين أو ثلاثة في الشاشة الضيقة) للأشرطة اللاصقة تحته (app.css)
  const top = document.querySelector<HTMLElement>(".topbar");
  if (top) {
    const set = () => document.documentElement.style.setProperty("--topbar-h", `${top.offsetHeight}px`);
    set(); // فورًا، فالمراقب لا يُبلغ في لسان مخفي حتى يُعرض
    if ("ResizeObserver" in window) {
      bar = new ResizeObserver(set);
      bar.observe(top);
    }
  }
});
/** رابط التخطي: ينقل التركيز إلى المحتوى دون تغيير مسار Vue Router */
function skipToMain() {
  document.getElementById("main")?.focus();
}
onUnmounted(() => {
  off?.();
  bar?.disconnect();
});
</script>

<template>
  <a class="skip" href="#main" @click.prevent="skipToMain">تخطَّ إلى المحتوى</a>
  <AppTopbar />
  <main id="main" class="page" tabindex="-1">
    <RouterView />
  </main>
  <JobDock />
  <ConfirmDialog />
</template>
