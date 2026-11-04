<script setup lang="ts">
import { computed } from "vue";

import AutomationDiagram from "@/components/AutomationDiagram.vue";
import { useAutomationStatus } from "@/composables/useAutomationStatus";
import { useJobsStore } from "@/stores/jobs";
import { KIND_NODE } from "@/utils/automation";
import { fmtWhen } from "@/utils/format";

/**
 * صفحة الأتمتة: رسم لعملية الأتمتة كما تعمل فعلًا، بحالة حيّة لكل مرحلة من آخر عملياتها (AutomationDiagram)،
 * وآخر العمليات ونضج المراحل. الحركة لحظة بلحظة في «مباشر». لا شيء هنا يكتب على المنصة.
 */
const jobs = useJobsStore();
const { runs, scorecard, error, notes, weeklyNote, weeklyTitle } = useAutomationStatus();

const activeKey = computed(() => {
  const j = jobs.active.find((x) => x.status === "running");
  return j ? KIND_NODE[j.kind] : "";
});
const worker = computed(() => {
  const s = jobs.session;
  if (!s) return { label: "…", tone: "idle" };
  if (!s.worker_alive) return { label: "العامل متوقف", tone: "bad" };
  return s.worker_busy ? { label: "العامل ينفّذ مهمة", tone: "run" } : { label: `العامل جاهز · ${s.queued} في الطابور`, tone: "ok" };
});
</script>

<template>
  <header class="page-head">
    <div>
      <h1>الأتمتة</h1>
      <p>كيف تعمل: قراءة من المنصة، ثم اقتراح، ثم اعتمادك، ثم تطبيق وتحقق. كل صندوق يعرض آخر عملية له.</p>
    </div>
    <div class="head-side">
      <RouterLink to="/live" class="btn sm"><i class="live-dot" aria-hidden="true" /> الحركة لحظة بلحظة في «مباشر»</RouterLink>
      <span class="pill" :class="worker.tone">{{ worker.label }}</span>
    </div>
  </header>
  <div v-if="error" class="error-box">{{ error }}</div>

  <section class="card diagram">
    <AutomationDiagram :notes="notes" :worker="worker" :weekly-note="weeklyNote" :weekly-title="weeklyTitle" :active="activeKey" />
  </section>

  <section class="grid">
    <article class="card">
      <h2>آخر العمليات</h2>
      <table class="tbl">
        <thead><tr><th>العملية</th><th>الصف</th><th>النتيجة</th><th>متى</th></tr></thead>
        <tbody>
          <tr v-for="r in runs.slice(0, 12)" :key="r.id">
            <td>{{ r.kind_label }}</td><td>{{ r.class_name }}</td>
            <td><span class="pill" :class="r.ok ? 'ok' : 'bad'">{{ r.ok ? "سليمة" : "فيها خلل" }}</span></td>
            <td class="muted">{{ fmtWhen(r.finished_at ?? r.started_at) }}</td>
          </tr>
        </tbody>
      </table>
    </article>
    <article class="card">
      <h2>المراحل ونضجها</h2>
      <ul class="levels">
        <li v-for="t in scorecard?.current.tasks ?? []" :key="t.key">
          <span>{{ t.title }}</span>
          <span class="bar"><i :style="{ inlineSize: `${(t.level / 4) * 100}%` }" /></span>
          <small class="muted">{{ scorecard?.current.levels[String(t.level)] }}</small>
        </li>
      </ul>
    </article>
  </section>
</template>

<style scoped>
.diagram { padding: 8px; overflow: hidden; }
.head-side { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.live-dot { inline-size: 8px; block-size: 8px; border-radius: 50%; background: var(--brand); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-block-start: 16px; }
.card h2 { font-size: 17px; margin: 0 0 10px; }
.tbl { inline-size: 100%; border-collapse: collapse; font-size: 14px; }
.tbl th, .tbl td { text-align: start; padding: 6px 8px; border-block-end: 1px solid var(--line); }
.levels { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.levels li { display: grid; grid-template-columns: 1fr 120px auto; gap: 10px; align-items: center; font-size: 14px; }
.bar { block-size: 8px; background: var(--code-bg); border-radius: 99px; overflow: hidden; }
.bar i { display: block; block-size: 100%; background: var(--brand); }
.pill.run { background: var(--warn-soft); }
</style>
