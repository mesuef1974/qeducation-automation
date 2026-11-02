<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue";

import { neo } from "@/api/neo";
import type { Job, Run } from "@/api/types";
import { TONE } from "@/domain";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";
import { fmtStamp } from "@/utils/format";

const classes = useClassesStore();
const jobsStore = useJobsStore();
const tab = ref<"jobs" | "runs">("jobs");

// المهام
const jobs = ref<Job[]>([]);
// العمليات
const KINDS: [string, string][] = [
  ["", "كل الأنواع"], ["fetch", "جلب"], ["plan", "اقتراح تواريخ"], ["apply", "تطبيق"],
  ["assign_plan", "اقتراح إسناد"], ["assign_apply", "تطبيق إسناد"], ["publish_plan", "اقتراح نشر"],
  ["publish_apply", "تطبيق نشر"], ["verify", "تحقق"],
];
const kind = ref("");
const lms = ref<number | "">("");
const runs = ref<Run[]>([]);
const total = ref(0);
const open = ref<number | null>(null);
const loading = ref(false);
const error = ref("");
const PAGE = 50;

async function loadJobs() {
  try {
    jobs.value = (await neo.jobs({ limit: 50 })).results;
  } catch (e) {
    error.value = (e as Error).message;
  }
}

async function loadRuns(more = false) {
  loading.value = true;
  try {
    const page = await neo.runs({ kind: kind.value || undefined, class: lms.value || undefined, limit: PAGE,
                                  offset: more ? runs.value.length : 0 });
    runs.value = more ? [...runs.value, ...page.results] : page.results;
    total.value = page.count;
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

watch(tab, (t) => (t === "jobs" ? loadJobs() : loadRuns()), { immediate: true });
watch([kind, lms], () => loadRuns());
const off = jobsStore.onFinished(() => (tab.value === "jobs" ? loadJobs() : loadRuns()));
onUnmounted(off);

function target(j: Job) {
  if (j.params.classes?.length) return j.params.classes.map((c) => classes.name(c)).join("، ");
  if (j.params.run) return `الاقتراح #${j.params.run}${j.params.limit ? ` · أول ${j.params.limit}` : ""}`;
  return "-";
}
</script>

<template>
  <header class="page-head">
    <div>
      <h1>السجل</h1>
      <p>كل مهمة طُلبت من الواجهة، وكل عملية سُجّلت على المنصة (من الواجهة أو الطرفية).</p>
    </div>
    <div class="seg" role="tablist">
      <button role="tab" :aria-selected="tab === 'jobs'" :class="{ on: tab === 'jobs' }" @click="tab = 'jobs'">المهام</button>
      <button role="tab" :aria-selected="tab === 'runs'" :class="{ on: tab === 'runs' }" @click="tab = 'runs'">العمليات</button>
    </div>
  </header>

  <div v-if="error" class="error-box">{{ error }}</div>

  <template v-if="tab === 'jobs'">
    <p v-if="!jobs.length" class="empty">لم تُطلب مهام من الواجهة بعد.</p>
    <div v-else class="table-wrap">
      <table>
        <thead><tr><th class="tight">#</th><th>المهمة</th><th>الهدف</th><th>الطلب</th><th>الحالة</th><th>النتيجة</th></tr></thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td class="tight mono">{{ j.id }}</td>
            <td>{{ j.kind_label }}</td>
            <td>{{ target(j) }}</td>
            <td class="muted">{{ fmtStamp(j.created_at) }}</td>
            <td><span class="pill" :class="TONE[j.status]">{{ j.status_label }}</span></td>
            <td>
              <template v-if="j.status === 'failed'">
                <b class="err">{{ j.error_label }}</b> <small class="muted">{{ j.error }}</small>
              </template>
              <span v-for="r in j.runs" :key="r.id" class="pill" :class="r.ok ? 'prep' : 'bad'">
                {{ r.kind_label }} #{{ r.id }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>

  <template v-else>
    <div class="controls">
      <select v-model="kind" aria-label="النوع">
        <option v-for="[v, label] in KINDS" :key="v" :value="v">{{ label }}</option>
      </select>
      <select v-model="lms" aria-label="الصف">
        <option value="">كل الصفوف</option>
        <option v-for="c in classes.items" :key="c.lms_id" :value="c.lms_id">{{ c.name }}</option>
      </select>
      <span class="muted">{{ total }} عملية</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th class="tight">#</th><th>النوع</th><th>الصف</th><th>الوقت</th><th>النتيجة</th><th class="tight" /></tr></thead>
        <tbody>
          <template v-for="r in runs" :key="r.id">
            <tr>
              <td class="tight mono">{{ r.id }}</td>
              <td>{{ r.kind_label }}</td>
              <td>{{ r.class_name }}</td>
              <td class="muted">{{ fmtStamp(r.started_at) }}</td>
              <td><span class="pill" :class="r.ok ? 'ok' : 'bad'">{{ r.ok ? "سليمة" : "تحتاج مراجعة" }}</span></td>
              <td class="tight">
                <button class="btn ghost sm" :aria-expanded="open === r.id" @click="open = open === r.id ? null : r.id">
                  {{ open === r.id ? "إخفاء" : "الملخص" }}
                </button>
              </td>
            </tr>
            <tr v-if="open === r.id"><td colspan="6"><pre class="json">{{ JSON.stringify(r.summary, null, 2) }}</pre></td></tr>
          </template>
        </tbody>
      </table>
    </div>
    <button v-if="runs.length < total" class="btn" :disabled="loading" @click="loadRuns(true)">
      <i v-if="loading" class="spinner" /> المزيد
    </button>
  </template>
</template>

<style scoped>
.err { color: var(--bad); }
td .pill { margin-inline-end: 4px; }
</style>
