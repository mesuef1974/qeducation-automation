<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { neo } from "@/api/neo";
import type { WeeklyReport, WeeklyStage, WeeklyState } from "@/api/types";
import { useJobsStore } from "@/stores/jobs";
import { fmtSlot, fmtStamp } from "@/utils/format";

/** الدورة الأسبوعية: موعدها، وتقرير آخر دورة (ما طُبّق تلقائيًا وما بقي لمراجعتك ولماذا). */
const STAGE_LABEL: Record<string, string> = { dates: "التواريخ", assign: "الإسناد", publish: "النشر" };

const jobs = useJobsStore();
const state = ref<WeeklyState | null>(null);
const error = ref("");

async function load() {
  try {
    state.value = await neo.weekly();
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  }
}

async function runNow() {
  if (!state.value) return;
  try {
    await jobs.enqueue("weekly", { cycle: state.value.cycle });
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  }
}

const last = computed(() => state.value?.last ?? null);
const report = computed<WeeklyReport>(() => last.value?.report ?? {});
const running = computed(() => jobs.busy("weekly"));
const stages = (c: Record<string, WeeklyStage>) => Object.entries(c).filter(([k]) => k in STAGE_LABEL);

function line(s: WeeklyStage): string {
  if (s.anomaly) return s.anomaly;
  if (s.review_only) return s.held ? `للمراجعة فقط · ${s.held} بانتظار اعتمادك` : "للمراجعة فقط · لا جديد";
  const parts = [`طُبّق ${s.applied ?? s.approved ?? 0}`];
  if (s.held) parts.push(`${s.held} للمراجعة`);
  if (s.failed) parts.push(`${s.failed} فشل`);
  return parts.join(" · ");
}
const tone = (s: WeeklyStage) => (s.anomaly || s.failed || s.ok === false ? "bad" : s.held ? "warn" : "ok");

const stop = jobs.onFinished((j) => { if (j.kind === "weekly") void load(); });
onMounted(load);
onBeforeUnmount(stop);
</script>

<template>
  <section class="card weekly" aria-label="الدورة الأسبوعية">
    <header class="head">
      <div>
        <h2>الدورة الأسبوعية</h2>
        <small class="muted">
          <template v-if="state && !state.auto_approve">للمراجعة فقط: تجلب وتقترح وتتحقق، ولا يُعتمد شيء إلا بموافقتك.</template>
          <template v-else>التواريخ ثم الإسناد ثم النشر ثم التحقق، تلقائيًا مع تقرير.</template>
          <template v-if="state?.enabled">القادمة {{ fmtSlot(state.next_at) }}.</template>
          <template v-else-if="state">معطّلة من الإعدادات.</template>
        </small>
      </div>
      <button class="btn sm" :disabled="!state || running" @click="runNow">
        <i v-if="running" class="spinner" /> شغّل الآن
      </button>
    </header>

    <div v-if="error" class="error-box">{{ error }}</div>
    <p v-else-if="!last" class="muted">لم تُجرَ دورة بعد.</p>
    <template v-else>
      <p class="status">
        <span class="pill" :class="last.status === 'done' ? (report.attention ? 'warn' : 'ok') : last.status === 'failed' ? 'bad' : 'info'">
          {{ last.status === "done" && report.attention ? `تمت · ${report.attention} تحتاج نظرك` : last.status_label }}
        </span>
        <span class="muted">{{ fmtStamp(last.finished_at ?? last.created_at) }}</span>
        <span v-if="last.error" class="err">{{ last.error }}</span>
      </p>
      <div v-if="report.classes" class="grid">
        <div v-for="(c, name) in report.classes" :key="name" class="klass">
          <b>{{ name }}</b>
          <ul>
            <li v-for="[key, s] in stages(c)" :key="key">
              <span class="pill" :class="tone(s)">{{ STAGE_LABEL[key] }}</span> {{ line(s) }}
            </li>
            <li v-if="c.verify">
              <span class="pill" :class="c.verify.ok ? 'ok' : 'bad'">التحقق</span>
              {{ c.verify.ok ? "الطالب يرى ما يجب" : `مفقود: ${(c.verify.missing_past ?? []).join("، ")}` }}
            </li>
          </ul>
        </div>
      </div>
      <RouterLink v-if="report.attention" to="/review" class="btn ghost sm">راجع ما بقي</RouterLink>
    </template>
  </section>
</template>

<style scoped>
.weekly { gap: 12px; }
.head { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
.head h2 { font-size: 20px; margin: 0; }
.status { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0; font-size: 14px; }
.err { color: var(--bad); }
.grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); }
.klass ul { list-style: none; padding: 0; margin: 6px 0 0; display: grid; gap: 4px; font-size: 14px; }
</style>
