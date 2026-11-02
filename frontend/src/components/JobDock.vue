<script setup lang="ts">
import { watch } from "vue";

import type { Job } from "@/api/types";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";

const jobs = useJobsStore();
const classes = useClassesStore();
const AUTO_HIDE_MS = 8000;

function target(j: Job): string {
  if (j.params.classes?.length) return j.params.classes.map((c) => classes.name(c)).join("، ");
  if (j.params.run) return `الاقتراح #${j.params.run}${j.params.limit ? ` · أول ${j.params.limit}` : ""}`;
  return "";
}

function outcome(j: Job): string {
  if (j.status === "failed") return j.error || j.error_label;
  const bad = j.runs.filter((r) => !r.ok);
  return bad.length ? `انتهت مع ${bad.length} عملية تحتاج مراجعة` : `${j.runs.length} عملية سليمة`;
}

// إشعار النجاح يختفي وحده؛ الإخفاق يبقى حتى يُغلق
watch(() => jobs.finished.length, () => {
  const j = jobs.finished[0];
  if (j?.status === "done") window.setTimeout(() => jobs.dismiss(j.id), AUTO_HIDE_MS);
});
</script>

<template>
  <aside class="dock" aria-live="polite" aria-label="المهام">
    <div v-for="j in jobs.active" :key="j.id" class="toast">
      <i v-if="j.status === 'running'" class="spinner" aria-hidden="true" />
      <span v-else class="pill warn">في الانتظار</span>
      <div class="txt">
        <b>{{ j.kind_label }}</b>
        <small>{{ target(j) }}</small>
        <small v-if="j.status === 'queued' && jobs.workerSilent" class="warn-txt">
          لا عامل يعمل؟ شغّل: <code>python manage.py neo_worker</code>
        </small>
      </div>
      <button v-if="j.status === 'queued'" class="btn ghost sm" @click="jobs.cancel(j.id)">إلغاء</button>
    </div>

    <div v-for="j in jobs.finished.slice(0, 3)" :key="`f${j.id}`" class="toast" :class="j.status">
      <span class="pill" :class="j.status === 'done' ? 'ok' : 'bad'">{{ j.status_label }}</span>
      <div class="txt">
        <b>{{ j.kind_label }}</b>
        <small>{{ target(j) }}</small>
        <small>{{ outcome(j) }}</small>
      </div>
      <RouterLink class="btn ghost sm" to="/log" @click="jobs.dismiss(j.id)">التفاصيل</RouterLink>
      <button class="close" aria-label="إغلاق" @click="jobs.dismiss(j.id)">×</button>
    </div>
  </aside>
</template>

<style scoped>
.dock {
  position: fixed; inset-block-end: 16px; inset-inline-end: 16px; z-index: 20;
  display: grid; gap: 8px; inline-size: min(380px, calc(100vw - 32px));
}
.toast {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  box-shadow: 0 6px 24px rgba(0, 0, 0, .12);
}
.toast.failed { border-inline-start: 4px solid var(--bad); }
.toast.done { border-inline-start: 4px solid var(--ok); }
.txt { display: grid; flex: 1; min-inline-size: 0; line-height: 1.5; }
.txt small { color: var(--muted); overflow-wrap: anywhere; }
.warn-txt { color: var(--warn) !important; }
.close { border: 0; background: none; color: var(--muted); font-size: 20px; cursor: pointer; line-height: 1; }
</style>
