import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { neo } from "@/api/neo";
import type { Run, Scorecard, WeeklyState } from "@/api/types";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";
import { fmtSlot, fmtStamp, fmtWhen } from "@/utils/format";
import { NODES, type NodeNote } from "@/utils/automation";

/**
 * حالة كل عقدة في رسم الأتمتة من آخر عملياتها، وسطر الدورة الأسبوعية. تُحدَّث كل دقيقة وعند انتهاء أي مهمة.
 * تستعملها صفحة «الأتمتة» وصفحة «مباشر» فيبقى الرسمان متطابقين.
 */
export function useAutomationStatus() {
  const jobs = useJobsStore();
  const classes = useClassesStore();
  const runs = ref<Run[]>([]);
  const weekly = ref<WeeklyState | null>(null);
  const scorecard = ref<Scorecard | null>(null);
  const error = ref("");
  let timer: number | undefined;

  async function load() {
    try {
      const [page, w, s] = await Promise.all([neo.runs({ limit: 200 }), neo.weekly(), neo.scorecard()]);
      runs.value = page.results;
      weekly.value = w;
      scorecard.value = s;
      error.value = "";
    } catch (e) {
      error.value = (e as Error).message;
    }
  }
  onMounted(() => {
    void load();
    void classes.load();
    timer = window.setInterval(load, 60_000);
  });
  onBeforeUnmount(() => window.clearInterval(timer));
  onBeforeUnmount(jobs.onFinished(() => void load()));

  const notes = computed<Record<string, NodeNote>>(() => {
    const out: Record<string, NodeNote> = {};
    for (const s of NODES) {
      const last = runs.value.find((r) => s.kinds.includes(r.kind));
      out[s.key] = last
        ? { ok: last.ok, note: last.class_name, when: fmtStamp(last.finished_at ?? last.started_at) }
        : { ok: null, note: "لم تعمل بعد" };
    }
    const pending = Object.values(classes.openReview).reduce((a, b) => a + b, 0);
    out.approve = { ok: pending ? null : true, note: pending ? `${pending} اقتراحًا بانتظار قرارك` : "لا شيء بانتظارك" };
    const cov = scorecard.value?.current.criteria.find((c) => c.key === "coverage");
    out.scorecard = { ok: cov ? true : null, note: cov?.value != null ? `تغطية الأتمتة ${cov.value}%` : "بلا لقطة بعد" };
    const sess = jobs.session;
    out.platform = { ok: sess ? !sess.expired : null, note: sess ? (sess.expired ? "الجلسة منتهية: neo_login" : "الجلسة سارية") : "…" };
    return out;
  });

  /** عنوان شريط الدورة في الرسم: موعد القادمة بيومه وتاريخه ووقته، لا نصًا ثابتًا */
  const weeklyTitle = computed(() => {
    const w = weekly.value;
    if (!w) return "الدورة الأسبوعية";
    return w.enabled ? `الدورة الأسبوعية — القادمة ${fmtSlot(w.next_at)}` : "الدورة الأسبوعية — معطّلة";
  });

  const weeklyNote = computed(() => {
    const w = weekly.value;
    if (!w) return "";
    return w.last ? `الأخيرة: ${w.last.status_label} ${fmtWhen(w.last.finished_at ?? w.last.created_at)}` : "لم تعمل بعد";
  });

  return { runs, weekly, scorecard, error, notes, weeklyNote, weeklyTitle, load };
}
