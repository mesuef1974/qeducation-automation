import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { neo } from "@/api/neo";
import type { Job, JobKind, JobParams, SessionState } from "@/api/types";

const ACTIVE = new Set(["queued", "running"]);
const FAST_MS = 2500;   // ما دامت هناك مهمة نشطة
const SLOW_MS = 15000;
const SILENT_MS = 15000; // مهمة منتظرة بلا عامل يعمل طوال هذه المدة → الأرجح أن العامل متوقف

/**
 * المهام وحالة الجلسة. يستطلع الخادم بسرعة أثناء التنفيذ وببطء في غيره،
 * ويُخطر المشتركين حين تنتهي مهمة ليعيدوا تحميل بياناتهم.
 */
export const useJobsStore = defineStore("jobs", () => {
  const jobs = ref<Job[]>([]);
  const session = ref<SessionState | null>(null);
  const error = ref("");
  const finished = ref<Job[]>([]);
  const listeners = new Set<(job: Job) => void>();
  let timer: number | undefined;

  const active = computed(() => jobs.value.filter((j) => ACTIVE.has(j.status)));
  const workerSilent = computed(
    () => !session.value?.worker_busy &&
      active.value.some((j) => j.status === "queued" && Date.now() - Date.parse(j.created_at) > SILENT_MS),
  );

  function schedule() {
    window.clearTimeout(timer);
    timer = window.setTimeout(refresh, active.value.length ? FAST_MS : SLOW_MS);
  }

  async function refresh() {
    try {
      const before = new Map(jobs.value.map((j) => [j.id, j.status]));
      const [page, state] = await Promise.all([neo.jobs({ limit: 20 }), neo.session()]);
      jobs.value = page.results;
      session.value = state;
      error.value = "";
      for (const j of page.results) {
        const was = before.get(j.id);
        if (was && ACTIVE.has(was) && !ACTIVE.has(j.status)) {
          finished.value.unshift(j);
          listeners.forEach((l) => l(j));
        }
      }
    } catch (e) {
      error.value = (e as Error).message;
    }
    schedule();
  }

  async function enqueue(kind: JobKind, params: JobParams = {}) {
    const job = await neo.enqueue(kind, params);
    await refresh();
    return job;
  }

  async function cancel(id: number) {
    await neo.cancel(id);
    await refresh();
  }

  /** هل هناك مهمة نشطة من هذا النوع (ولهذا الصف إن حُدّد)؟ لتعطيل الأزرار المكررة */
  function busy(kind: JobKind, lms?: number, run?: number) {
    return active.value.some((j) => j.kind === kind &&
      (lms === undefined || !j.params.classes || j.params.classes.includes(lms)) &&
      (run === undefined || j.params.run === run));
  }

  function onFinished(cb: (job: Job) => void) {
    listeners.add(cb);
    return () => listeners.delete(cb);
  }

  function dismiss(id: number) {
    finished.value = finished.value.filter((j) => j.id !== id);
  }

  return { jobs, session, error, finished, active, workerSilent, refresh, enqueue, cancel, busy, onFinished, dismiss };
});
