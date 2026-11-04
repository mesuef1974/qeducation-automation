<script setup lang="ts">
import { computed, watch } from "vue";

import type { Job } from "@/api/types";
import { firstLine, jobTarget } from "@/domain";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";

const jobs = useJobsStore();
const classes = useClassesStore();
const AUTO_HIDE_MS = 8000;
const SHOWN = 2; // المهام النشطة الظاهرة؛ الباقي سطر واحد

// الجارية أولًا ثم الأقدم انتظارًا (ترتيب التنفيذ)
const queue = computed(() => [...jobs.active].sort((a, b) =>
  Number(b.status === "running") - Number(a.status === "running") || a.id - b.id));

const target = (j: Job) => jobTarget(j.kind, j.params, classes.name);

function outcome(j: Job): string {
  if (j.status === "failed") return firstLine(j.error) || j.error_label;
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
    <div v-if="queue.length && jobs.workerDown" class="toast down">
      <span class="pill warn">العامل متوقف</span>
      <div class="txt">
        <b>{{ queue.length }} مهمة لن تُنفَّذ حتى يعمل العامل</b>
        <small>شغّله في طرفية: <code>cd backend &amp;&amp; python manage.py neo_worker</code></small>
      </div>
    </div>

    <div v-for="j in queue.slice(0, SHOWN)" :key="j.id" class="toast">
      <i v-if="j.status === 'running' && !jobs.workerDown" class="spinner" aria-hidden="true" />
      <span v-else class="pill warn">في الانتظار</span>
      <div class="txt">
        <b>{{ j.kind_label }}</b>
        <small>{{ target(j) }}</small>
      </div>
      <button v-if="j.status === 'queued'" class="btn ghost sm" @click="jobs.cancel(j.id)">إلغاء</button>
    </div>
    <RouterLink v-if="queue.length > SHOWN" class="toast more" to="/log">
      و{{ queue.length - SHOWN }} مهام أخرى في الانتظار · السجل
    </RouterLink>

    <div v-for="j in jobs.finished.slice(0, 2)" :key="`f${j.id}`" class="toast" :class="j.status">
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
  display: grid; gap: 6px; inline-size: min(360px, calc(100vw - 32px));
}
.toast {
  display: flex; align-items: center; gap: 10px; padding: 8px 12px;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  box-shadow: 0 6px 24px rgba(0, 0, 0, .12);
}
.toast.failed { border-inline-start: 4px solid var(--bad); }
.toast.done { border-inline-start: 4px solid var(--ok); }
.toast.down { border-inline-start: 4px solid var(--warn); }
.toast.more { justify-content: center; font-size: 13px; color: var(--muted); text-decoration: none; }
.toast.more:hover { color: var(--maroon); }
.txt { display: grid; flex: 1; min-inline-size: 0; line-height: 1.5; }
.txt small { color: var(--muted); overflow-wrap: anywhere; }
.close { border: 0; background: none; color: var(--muted); font-size: 20px; cursor: pointer; line-height: 1; }
</style>
