<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { neo } from "@/api/neo";
import type { LiveEvent, LiveFeed, LiveKind } from "@/api/types";
import AutomationDiagram from "@/components/AutomationDiagram.vue";
import ErrorText from "@/components/ErrorText.vue";
import { useAutomationStatus } from "@/composables/useAutomationStatus";
import { useJobsStore } from "@/stores/jobs";
import { isNode, KIND_NODE, NODES, type NodeKey, type NodeNote, type Signal } from "@/utils/automation";
import { fmtClock, fmtShort, fmtSlot, fmtStamp, fmtStampSec, fmtWhen } from "@/utils/format";

/**
 * «مباشر»: ما يفعله العامل الآن على المنصة لحظة بلحظة، من بثّه الحي (media/live/job_<id>.jsonl).
 * المهمة الجارية بمراحلها وتقدّمها وزمنها، ورسم الأتمتة يتحرك معها (العقدة الجارية، ومسارها، وكل صفحة تعبره)،
 * وسجل البث، والطابور، وآخر المهام (تُعاد مشاهدتها بالنقر). الصفحة تقرأ فقط؛ لا شيء هنا يكتب على المنصة.
 */
const jobs = useJobsStore();
const feed = ref<LiveFeed | null>(null);
const events = ref<LiveEvent[]>([]);
const error = ref("");
const pinned = ref<number | null>(null); // مهمة سابقة تُعاد مشاهدتها؛ null = المباشر
const follow = ref(true);
const filter = ref<"all" | "steps" | "net" | "file" | "alerts">("all");
const skew = ref(0); // ساعة الخادم − ساعة المتصفح
const tick = ref(Date.now());
const list = ref<HTMLOListElement | null>(null);

const MAX_EVENTS = 2000;
const FAST_MS = 1200;
const SLOW_MS = 4000;
let jobId: number | null = null;
let lastSeq = 0;
let timer: number | undefined;
let ticker: number | undefined;
let alive = true;
let quiet = true; // أول تحميل أو إعادة مشاهدة: ما سبق من أحداث لا يتحرك في الرسم

async function poll(): Promise<void> {
  window.clearTimeout(timer);
  try {
    const data = await neo.live({ since: lastSeq, job: pinned.value ?? undefined });
    skew.value = Date.parse(data.now) - Date.now();
    const id = data.job?.id ?? null;
    if (id !== jobId) { // مهمة جديدة بدأت (أو اختيرت): البث من أوله
      jobId = id;
      lastSeq = 0;
      events.value = [];
      if (id !== null && data.events[0]?.seq !== 1) return poll();
    }
    feed.value = data;
    if (data.events.length) {
      if (!quiet && !pinned.value) spawn(data.events);
      events.value = [...events.value, ...data.events].slice(-MAX_EVENTS);
      lastSeq = data.events[data.events.length - 1].seq;
    }
    quiet = false;
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  }
  if (alive) timer = window.setTimeout(poll, running.value ? FAST_MS : SLOW_MS);
}

function watchJob(id: number | null) {
  pinned.value = id;
  jobId = null;
  quiet = true;
  signals.value = [];
  void poll();
}

onMounted(() => {
  void poll();
  ticker = window.setInterval(() => (tick.value = Date.now()), 1000);
});
onBeforeUnmount(() => {
  alive = false;
  window.clearTimeout(timer);
  window.clearInterval(ticker);
});

// ------------------------------------------------------------ الحالة
const job = computed(() => feed.value?.job ?? null);
const summary = computed(() => job.value?.live ?? null);
const running = computed(() => job.value?.status === "running");
const serverNow = computed(() => tick.value + skew.value);

const worker = computed(() => {
  const w = feed.value?.worker;
  if (!w) return { tone: "idle", label: "…" };
  if (!w.alive) return { tone: "bad", label: "العامل متوقف" };
  return feed.value?.session.worker_busy ? { tone: "run", label: "يعمل الآن" } : { tone: "ok", label: "جاهز" };
});
const beatAge = computed(() => {
  const at = feed.value?.worker.seen_at;
  return at ? Math.max(0, Math.round((serverNow.value - Date.parse(at)) / 1000)) : null;
});
/** آخر نبض: بالثواني ما دام حديثًا، وبتاريخه ووقته إن تأخر فلا تكفي الثواني */
const beatText = computed(() => {
  const age = beatAge.value, at = feed.value?.worker.seen_at;
  if (age === null || !at) return "";
  return age < 60 ? `آخر نبض قبل ${age} ث` : `آخر نبض ${fmtWhen(at)}`;
});
const beatTitle = computed(() => {
  const at = feed.value?.worker.seen_at;
  return at ? fmtStampSec(at) : "";
});

const elapsed = computed(() => {
  const j = job.value;
  if (!j?.started_at) return 0;
  return running.value ? Math.max(0, (serverNow.value - Date.parse(j.started_at)) / 1000) : (j.seconds ?? 0);
});
/** تحت الساعة: متى بدأت المهمة، أو كيف انتهت ومتى */
const heroWhen = computed(() => {
  const j = job.value;
  if (!j) return "";
  if (running.value) return j.started_at ? `منذ ${fmtStamp(j.started_at)}` : "منذ البدء";
  return `${j.status_label} · ${fmtStamp(j.finished_at ?? j.started_at)}`;
});
const progress = computed(() => summary.value?.progress ?? null);
const pct = computed(() => {
  if (summary.value?.end?.status === "done") return 100;
  const p = progress.value;
  return p && p.total ? Math.min(100, Math.round((p.current / p.total) * 100)) : 0;
});
const lastStep = computed(() => [...events.value].reverse().find((e) => e.kind === "step" || e.kind === "file")?.text ?? "");
const stages = computed(() => {
  const all = summary.value?.stages ?? [];
  const ended = !!summary.value?.end;
  return all.map((s, i) => ({ ...s, state: i < all.length - 1 || ended ? "done" : running.value ? "now" : "done" }));
});
const counts = computed(() => summary.value?.counts ?? {});
const ops = computed(() => summary.value?.ops ?? {});
const fileTotal = computed(() => (ops.value.download ?? 0) + (ops.value.cache ?? 0) || (counts.value.file ?? 0));
const ended = computed(() => summary.value?.end ?? null);
const tone = computed(() => (running.value ? "run" : ended.value?.status === "failed" || job.value?.status === "failed" ? "bad"
  : job.value ? "ok" : "idle"));

// ------------------------------------------------------------ الرسم الحي
const { notes: baseNotes, weeklyNote } = useAutomationStatus();
const signals = ref<Signal[]>([]);
const BURST = 6; // أقصى إشارات من دفعة واحدة، والباقي يظهر في السجل
const GAP_MS = 420;
let signalId = 0;

/** كل صفحة تُقرأ أو تُكتب، وكل ملف، يعبر الرسم إشارةً من حيث جاء إلى حيث ذهب */
function spawn(batch: LiveEvent[]) {
  const fallback: NodeKey = job.value ? KIND_NODE[job.value.kind] : "fetch";
  let n = 0;
  for (const e of batch) {
    if (n >= BURST) break;
    const node = isNode(e.node) ? e.node : fallback;
    const kind = e.kind === "net" ? (node === "apply" && e.method && e.method !== "GET" ? "write" : "read")
      : e.kind === "file" ? "file" : null;
    if (!kind) continue;
    const s: Signal = { id: ++signalId, node, kind, delay: n++ * GAP_MS };
    signals.value = [...signals.value, s];
    window.setTimeout(() => (signals.value = signals.value.filter((x) => x.id !== s.id)), s.delay + 4500);
  }
}

const nodeNow = computed<NodeKey | "">(() => {
  if (!running.value || !job.value) return "";
  for (let i = events.value.length - 1; i >= 0; i--) {
    const n = events.value[i].node;
    if (isNode(n)) return n;
  }
  return KIND_NODE[job.value.kind];
});
const nodeTitle = computed(() => NODES.find((n) => n.key === nodeNow.value)?.title ?? "");
/** العقد التي مرت بها المهمة المعروضة؛ المنصة منها إن قُرئ منها شيء */
const trail = computed<string[] | null>(() => {
  const j = job.value;
  if (!j) return null;
  const seen = (summary.value?.nodes ?? []).filter(isNode);
  const list: string[] = seen.length ? seen : [KIND_NODE[j.kind]];
  return [...new Set([...((counts.value.net ?? 0) > 0 ? ["platform"] : []), ...list])];
});
const failedNode = computed(() => {
  const j = job.value;
  if (!j || running.value || !(ended.value?.status === "failed" || j.status === "failed")) return "";
  const t = trail.value ?? [];
  return t[t.length - 1] ?? "";
});
const nodeProgress = computed(() => {
  const p = progress.value;
  const current = stages.value[stages.value.length - 1]?.text;
  return running.value && p && p.total && p.stage === current ? p.current / p.total : null;
});
const clip = (t: string, n = 27) => (t.length > n ? `${t.slice(0, n - 1)}…` : t);
const lastOf = (kinds: LiveKind[]) => [...events.value].reverse().find((e) => kinds.includes(e.kind));
const notes = computed<Record<string, NodeNote>>(() => {
  const out = { ...baseNotes.value };
  if (!running.value) return out;
  const net = lastOf(["net"]);
  if (net) out.platform = { ok: true, note: clip(`${counts.value.net ?? 0} طلبًا · ${net.text}`) };
  const k = nodeNow.value;
  if (k) {
    const p = progress.value;
    const e = lastOf(["step", "file", "net", "stage"]);
    const text = nodeProgress.value !== null && p ? `${p.current}/${p.total} · ${p.text}`
      : e?.kind === "net" ? `${e.method && e.method !== "GET" ? "يكتب" : "يقرأ"}: ${e.text}` : e?.text ?? "";
    out[k] = { ok: null, note: clip(text) };
  }
  return out;
});

let folded = false;
try {
  folded = localStorage.getItem("live.diagram") === "folded";
} catch {
  /* بلا تخزين يبقى الرسم ظاهرًا */
}
const showDiagram = ref(!folded);
function toggleDiagram() {
  showDiagram.value = !showDiagram.value;
  try {
    localStorage.setItem("live.diagram", showDiagram.value ? "open" : "folded");
  } catch {
    /* تفضيل للجلسة فقط */
  }
}

// ------------------------------------------------------------ سجل البث
const TAG: Record<LiveKind, string> = {
  start: "بدء", stage: "مرحلة", step: "خطوة", net: "المنصة", file: "ملف", warn: "تنبيه", error: "خطأ", end: "نهاية",
};
const FILTERS: { key: typeof filter.value; label: string; kinds: LiveKind[] | null }[] = [
  { key: "all", label: "الكل", kinds: null },
  { key: "steps", label: "المراحل والخطوات", kinds: ["start", "stage", "step", "end"] },
  { key: "net", label: "طلبات المنصة", kinds: ["net"] },
  { key: "file", label: "الملفات", kinds: ["file"] },
  { key: "alerts", label: "التنبيهات", kinds: ["warn", "error"] },
];
const shown = computed(() => {
  const kinds = FILTERS.find((f) => f.key === filter.value)?.kinds;
  return kinds ? events.value.filter((e) => kinds.includes(e.kind)) : events.value;
});

function meta(e: LiveEvent): string {
  if (e.kind === "net") return [e.status, e.ms !== undefined ? `${e.ms} م.ث` : ""].filter(Boolean).join(" · ");
  if (e.kind === "file") return e.cached ? "من الذاكرة المؤقتة" : e.size ? `${Math.max(1, Math.round(e.size / 1024))} ك.ب` : "";
  if (e.kind === "step" && e.total) return `${e.current} / ${e.total}`;
  if (e.kind === "warn" && e.retry) return `انتظار ${e.retry} ث`;
  return "";
}

/** لحظة بدء المرحلة بتاريخها ووقتها، من حدثها في البث */
function stageStamp(s: { text: string; t: number }): string {
  const e = events.value.find((x) => x.kind === "stage" && x.text === s.text && Math.abs(x.t - s.t) < 0.5);
  return e ? fmtStampSec(e.at) : "";
}

function fmtDur(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(r).padStart(2, "0")}`;
}

function onScroll() {
  const el = list.value;
  if (el) follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
}
watch(() => shown.value.length, async () => {
  if (!follow.value) return;
  await nextTick();
  if (list.value) list.value.scrollTop = list.value.scrollHeight;
});
function jumpToEnd() {
  follow.value = true;
  if (list.value) list.value.scrollTop = list.value.scrollHeight;
}

async function cancel(id: number) {
  try {
    await jobs.cancel(id);
    void poll();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const statusTone = (s: string) => (s === "done" ? "ok" : s === "failed" ? "bad" : s === "running" ? "info" : "warn");
</script>

<template>
  <header class="page-head live-head">
    <div>
      <h1>مباشر</h1>
      <p>ما يفعله العامل الآن على المنصة، لحظة بلحظة. هذه الصفحة تقرأ فقط.</p>
    </div>
    <div class="beacon" :class="worker.tone" role="status" aria-live="polite">
      <i class="dot" aria-hidden="true" />
      <div>
        <b>{{ worker.label }}</b>
        <small v-if="beatAge !== null" :title="beatTitle">{{ beatText }}<template v-if="feed?.worker.pid"> · PID {{ feed.worker.pid }}</template></small>
        <small v-else>لا نبض مسجّل</small>
      </div>
    </div>
  </header>

  <div v-if="error" class="error-box">تعذّر الاتصال بالخادم: {{ error }}</div>
  <div v-else-if="feed && !feed.worker.alive" class="error-box">
    العامل متوقف، فلن تُنفَّذ المهام. شغّله بـ <code>start.ps1</code> أو <code>open-edge.bat</code> في مجلد المشروع.
  </div>

  <section class="layout">
    <div class="main">
      <article class="card hero" :class="tone" aria-label="المهمة">
        <template v-if="job">
          <div class="hero-top">
            <div class="title">
              <span class="eyebrow">
                <i v-if="running" class="pulse" aria-hidden="true" />
                {{ pinned ? "إعادة مشاهدة" : running ? "تعمل الآن" : "آخر مهمة" }} · #{{ job.id }}
              </span>
              <h2>{{ job.kind_label }}</h2>
              <p v-if="job.target" class="muted">{{ job.target }}</p>
            </div>
            <div class="timer">
              <span class="clock mono">{{ fmtDur(elapsed) }}</span>
              <small>{{ heroWhen }}</small>
            </div>
          </div>

          <p v-if="!events.length && !running" class="muted note">لا بث مسجّل لهذه المهمة؛ البث يبدأ مع المهام الجديدة.</p>
          <div class="now">
            <span class="stage-now">{{ progress?.stage || stages[stages.length - 1]?.text || "بدء المهمة" }}</span>
            <span class="step-now">{{ progress?.text ?? lastStep }}</span>
          </div>
          <div class="bar" :class="{ indeterminate: running && !progress }" role="progressbar" :aria-valuenow="pct"
               aria-valuemin="0" aria-valuemax="100">
            <i :style="{ inlineSize: `${pct}%` }" />
          </div>
          <div class="bar-meta">
            <span>{{ progress ? `${progress.current} من ${progress.total}` : running ? "جارٍ…" : "" }}</span>
            <span class="mono">{{ pct }}%</span>
          </div>

          <ol v-if="stages.length" class="stages" aria-label="المراحل">
            <li v-for="(s, i) in stages" :key="i" :class="s.state" :title="stageStamp(s)">
              <span class="n">{{ s.state === "done" ? "✓" : i + 1 }}</span>
              <span class="st">{{ s.text }}</span>
              <small class="mono">+{{ fmtDur(s.t) }}</small>
            </li>
          </ol>

          <dl class="kpis">
            <div><dt>طلبات المنصة</dt><dd class="mono">{{ counts.net ?? 0 }}</dd></div>
            <div>
              <dt>ملفات</dt><dd class="mono">{{ fileTotal }}</dd>
              <small v-if="ops.download || ops.cache || ops.edit" class="sub">
                نُزّل {{ ops.download ?? 0 }} · مخزّن {{ ops.cache ?? 0 }} · عُدّل {{ ops.edit ?? 0 }}
              </small>
            </div>
            <div :class="{ warn: counts.warn }"><dt>تنبيهات</dt><dd class="mono">{{ counts.warn ?? 0 }}</dd></div>
            <div :class="{ bad: counts.error }"><dt>أخطاء</dt><dd class="mono">{{ counts.error ?? 0 }}</dd></div>
          </dl>

          <div v-if="ended" class="result" :class="ended.status === 'done' ? 'ok' : 'bad'">
            <b>{{ ended.status === "done" ? "انتهت" : "توقفت" }}</b> {{ ended.text }}
          </div>
          <div v-else-if="!running && job.status === 'failed'" class="result bad">
            <b>توقفت</b> {{ job.error_label }}: <ErrorText :text="job.error" />
          </div>
          <button v-if="pinned" class="btn sm" @click="watchJob(null)">العودة إلى المباشر</button>
        </template>
        <p v-else class="muted">لم تُنفَّذ مهمة بعد. اطلب واحدة من «اليوم» وستظهر هنا لحظة بدئها.</p>
      </article>

      <article class="card flow-card" aria-label="الرسم الحي">
        <header class="flow-head">
          <h2>
            الرسم الحي
            <small v-if="nodeNow" class="where"><i class="pulse" aria-hidden="true" /> الآن في «{{ nodeTitle }}»</small>
            <small v-else-if="job" class="muted">مسار آخر مهمة</small>
          </h2>
          <div class="legend" aria-label="مفتاح الرسم">
            <span><i class="sw read" aria-hidden="true" /> قراءة من المنصة</span>
            <span><i class="sw write" aria-hidden="true" /> كتابة على المنصة</span>
            <span><i class="sw file" aria-hidden="true" /> ملف</span>
            <button class="btn ghost sm" :aria-expanded="showDiagram" @click="toggleDiagram">{{ showDiagram ? "طيّ" : "إظهار" }}</button>
          </div>
        </header>
        <AutomationDiagram v-if="showDiagram" :notes="notes" :worker="worker" :weekly-note="weeklyNote" :active="nodeNow"
                           :trail="trail" :failed="failedNode" :progress="nodeProgress" :signals="signals"
                           :auto-approve="!!feed?.weekly.auto_approve" />
      </article>

      <article class="card feed" aria-label="سجل البث">
        <header class="feed-head">
          <h2>سجل البث <small class="muted">{{ events.length }} حدثًا</small></h2>
          <div class="seg" role="tablist">
            <button v-for="f in FILTERS" :key="f.key" :class="{ on: filter === f.key }" role="tab"
                    :aria-selected="filter === f.key" @click="filter = f.key">{{ f.label }}</button>
          </div>
        </header>
        <ol ref="list" class="log" @scroll="onScroll">
          <li v-for="e in shown" :key="e.seq" :class="['ev', e.kind]">
            <time :title="fmtStampSec(e.at)">
              <span class="clk mono">{{ fmtClock(e.at) }}</span>
              <small>{{ fmtShort(e.at) }} · <bdi dir="ltr" class="mono">+{{ fmtDur(e.t) }}</bdi></small>
            </time>
            <span class="tag">{{ TAG[e.kind] }}</span>
            <span class="txt">{{ e.text }}</span>
            <span class="meta">{{ meta(e) }}</span>
          </li>
          <li v-if="!shown.length" class="ev empty">لا أحداث بعد.</li>
        </ol>
        <button v-if="!follow" class="btn sm jump" @click="jumpToEnd">↓ إلى أحدث حدث</button>
      </article>
    </div>

    <aside class="side">
      <article class="card">
        <h2>الطابور <small class="muted">{{ feed?.queue.length ?? 0 }}</small></h2>
        <ul class="jobs">
          <li v-for="q in feed?.queue ?? []" :key="q.id">
            <div><b>{{ q.kind_label }}</b><small>{{ q.target }}</small></div>
            <button class="btn ghost sm" @click="cancel(q.id)">إلغاء</button>
          </li>
          <li v-if="!feed?.queue.length" class="muted">لا شيء بالانتظار.</li>
        </ul>
      </article>

      <article class="card">
        <h2>آخر المهام</h2>
        <ul class="jobs">
          <li v-for="r in feed?.recent ?? []" :key="r.id" :class="{ sel: job?.id === r.id }">
            <button class="row" @click="watchJob(r.id)" :aria-label="`إعادة مشاهدة ${r.kind_label}`">
              <span class="pill" :class="statusTone(r.status)">{{ r.status_label }}</span>
              <span class="what"><b>{{ r.kind_label }}</b><small>{{ r.target }}</small></span>
              <span class="when"><span class="mono">{{ r.seconds !== null ? fmtDur(r.seconds) : "-" }}</span>
                <small :title="fmtWhen(r.finished_at ?? r.started_at)">{{ fmtStamp(r.finished_at ?? r.started_at ?? r.created_at) }}</small></span>
            </button>
          </li>
        </ul>
      </article>

      <article class="card">
        <h2>العامل والجدولة</h2>
        <dl class="kv">
          <dt>الجلسة</dt>
          <dd><span class="pill" :class="feed?.session.expired ? 'bad' : 'ok'">{{ feed?.session.expired ? "منتهية" : "سارية" }}</span></dd>
          <dt>آخر اتصال</dt><dd>{{ fmtWhen(feed?.session.checked_at) }}</dd>
          <dt>الدورة الأسبوعية</dt>
          <dd>{{ feed?.weekly.enabled ? `القادمة ${fmtSlot(feed.weekly.next_at)}${feed.weekly.auto_approve ? "" : " · للمراجعة فقط"}` : "معطّلة" }}</dd>
          <dt>الكتابة على المنصة</dt>
          <dd>
            <span class="pill" :class="feed?.session.halted ? 'bad' : 'ok'">{{ feed?.session.halted ? "موقوفة آليًا" : "مسموحة بعد اعتمادك" }}</span>
            <small v-if="feed?.session.halted" class="muted"> {{ feed.session.halt_reason }}</small>
          </dd>
          <dt>التمهّل</dt><dd>&lrm;3–6&lrm; ث بين طلبات الحزمة، وإعادة بعد &lrm;429&lrm;</dd>
        </dl>
        <RouterLink to="/swot" class="btn ghost sm">نضج المراحل في «SWOT والأداء»</RouterLink>
      </article>
    </aside>
  </section>
</template>

<style scoped>
.live-head { align-items: center; }
.beacon {
  display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-radius: 999px;
  background: var(--surface); border: 1px solid var(--line);
}
.beacon div { display: grid; line-height: 1.3; }
.beacon small { color: var(--muted); font-size: var(--fs-xs); }
.beacon .dot { inline-size: 12px; block-size: 12px; border-radius: 50%; background: var(--muted); flex: none; }
.beacon.ok .dot { background: var(--ok); }
.beacon.bad { border-color: var(--bad); }
.beacon.bad .dot { background: var(--bad); }
.beacon.run { border-color: var(--brand); }
.beacon.run .dot { background: var(--brand); animation: ping 1.4s infinite; }

.layout { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr) minmax(260px, 340px); align-items: start; }
@media (max-width: 980px) { .layout { grid-template-columns: 1fr; } }
.main, .side { display: grid; gap: 16px; min-inline-size: 0; }
.card h2 { font-size: var(--fs-lg); margin: 0; display: flex; align-items: baseline; gap: 8px; }

/* المهمة */
.hero { gap: 14px; border-inline-start: 5px solid var(--line); }
.hero.run { border-inline-start-color: var(--brand); }
.hero.ok { border-inline-start-color: var(--ok); }
.hero.bad { border-inline-start-color: var(--bad); }
.hero-top { display: flex; justify-content: space-between; align-items: start; gap: 16px; flex-wrap: wrap; }
.title h2 { font: 700 clamp(20px, 3vw, 26px) var(--f-display); margin: 2px 0; }
.title p { margin: 0; }
.eyebrow { display: inline-flex; align-items: center; gap: 8px; font-size: var(--fs-sm); color: var(--muted); }
.pulse { inline-size: 8px; block-size: 8px; border-radius: 50%; background: var(--brand); animation: ping 1.4s infinite; }
.timer { display: grid; justify-items: end; }
.clock { font-size: clamp(28px, 5vw, 40px); font-weight: 600; line-height: 1; letter-spacing: .5px; direction: ltr; }
.timer small { color: var(--muted); font-size: var(--fs-xs); }
.now { display: grid; gap: 2px; }
.stage-now { font-weight: 700; font-size: var(--fs-body); }
.step-now { color: var(--muted); font-size: var(--fs-base); overflow-wrap: anywhere; min-block-size: 1.4em; }
.bar { block-size: 10px; border-radius: 999px; background: var(--code-bg); overflow: hidden; position: relative; }
.bar i { display: block; block-size: 100%; background: var(--brand); border-radius: inherit; transition: inline-size .6s ease; }
.hero.ok .bar i { background: var(--ok); }
.hero.bad .bar i { background: var(--bad); }
.bar.indeterminate i { inline-size: 35% !important; position: absolute; inset-inline-start: -35%; animation: slide 1.4s ease-in-out infinite; }
.bar-meta { display: flex; justify-content: space-between; font-size: var(--fs-sm); color: var(--muted); margin-block-start: -6px; }
.stages { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 8px; }
.stages li {
  display: inline-flex; align-items: center; gap: 8px; padding: 5px 12px 5px 8px; border-radius: 999px;
  background: var(--code-bg); font-size: var(--fs-sm); max-inline-size: 100%;
}
.stages .n {
  display: inline-grid; place-items: center; inline-size: 20px; block-size: 20px; border-radius: 50%; font-size: var(--fs-xs);
  background: var(--surface); border: 1px solid var(--line); flex: none;
}
.stages .st { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stages small { color: var(--muted); }
.stages .done .n { background: var(--ok); border-color: var(--ok); color: var(--surface); }
.stages .now { background: var(--maroon-soft); color: var(--maroon); font-weight: 600; }
.stages .now .n { background: var(--brand); border-color: var(--brand); color: var(--on-brand); animation: ping 1.4s infinite; }
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 0; }
@media (max-width: 560px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.kpis div { background: var(--bg); border-radius: 10px; padding: 8px 12px; }
.kpis dt { font-size: var(--fs-xs); color: var(--muted); }
.kpis dd { margin: 0; font-size: var(--fs-2xl); font-weight: 600; }
.kpis .sub { display: block; color: var(--muted); font-size: var(--fs-xs); }
.kpis .warn dd { color: var(--warn); }
.kpis .bad dd { color: var(--bad); }
.result { border-radius: 10px; padding: 10px 14px; font-size: var(--fs-base); }
.result.ok { background: var(--ok-soft); }
.result.bad { background: var(--bad-soft); }

/* الرسم الحي */
.flow-card { gap: 6px; }
.flow-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; }
.flow-head .where { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-sm); font-weight: 600; color: var(--maroon); }
.legend { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; font-size: var(--fs-xs); color: var(--muted); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { inline-size: 10px; block-size: 10px; border-radius: 50%; }
.sw.read { background: var(--slate); box-shadow: 0 0 6px var(--slate); }
.sw.write { background: var(--brand); box-shadow: 0 0 6px var(--brand); }
.sw.file { border: 2px solid var(--ok); }

/* سجل البث */
.feed { position: relative; }
.feed-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; }
.log {
  list-style: none; margin: 0; padding: 6px 0; block-size: min(56vh, 520px); overflow-y: auto;
  background: var(--bg); border: 1px solid var(--line); border-radius: 10px; font-size: var(--fs-sm);
}
.ev { display: grid; grid-template-columns: 96px 74px minmax(0, 1fr) auto; gap: 10px; align-items: baseline; padding: 4px 12px; }
.ev:hover { background: var(--surface); }
.ev time { display: grid; color: var(--muted); font-size: var(--fs-xs); line-height: 1.3; }
.ev time small { font-size: var(--fs-xs); opacity: .85; }
.ev .tag { font-size: var(--fs-xs); padding: 0 8px; border-radius: 999px; text-align: center; background: var(--code-bg); color: var(--muted); }
.ev .txt { overflow-wrap: anywhere; }
.ev .meta { color: var(--muted); font-size: var(--fs-xs); white-space: nowrap; font-variant-numeric: tabular-nums; }
.ev.stage { background: var(--maroon-soft); margin-block: 4px; }
.ev.stage .tag { background: var(--brand); color: var(--on-brand); }
.ev.stage .txt { font-weight: 700; color: var(--maroon); }
.ev.step .tag { background: var(--slate-soft); color: var(--slate); }
.ev.net { color: var(--muted); }
.ev.file .tag { background: var(--ok-soft); color: var(--ok); }
.ev.warn .tag { background: var(--warn-soft); color: var(--warn); }
.ev.error { background: var(--bad-soft); }
.ev.error .tag { background: var(--bad); color: var(--surface); }
.ev.start .tag, .ev.end .tag { background: var(--fg); color: var(--surface); }
.ev.end .txt { font-weight: 700; }
.ev.empty { display: block; color: var(--muted); text-align: center; padding: 24px; }
.jump { position: absolute; inset-block-end: 28px; inset-inline-start: 50%; transform: translateX(-50%); box-shadow: 0 4px 16px rgba(0, 0, 0, .15); }
@media (max-width: 560px) { .ev { grid-template-columns: 92px minmax(0, 1fr); } .ev .tag, .ev .meta { display: none; } }

/* الجانب */
.jobs { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; font-size: var(--fs-base); }
.jobs > li { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.jobs > li div { display: grid; min-inline-size: 0; }
.jobs small { color: var(--muted); font-size: var(--fs-xs); overflow-wrap: anywhere; }
.jobs .row {
  inline-size: 100%; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px; align-items: center;
  padding: 6px 8px; border: 1px solid transparent; border-radius: 10px; background: none; font: inherit; color: inherit;
  text-align: start; cursor: pointer;
}
.jobs .row:hover, .jobs .sel .row { border-color: var(--line); background: var(--bg); }
.jobs .what { display: grid; min-inline-size: 0; }
.jobs .when { display: grid; justify-items: end; font-size: var(--fs-sm); }

@keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--brand) 55%, transparent); } 100% { box-shadow: 0 0 0 9px transparent; } }
@keyframes slide { from { inset-inline-start: -35%; } to { inset-inline-start: 100%; } }
@media (prefers-reduced-motion: reduce) {
  .beacon.run .dot, .pulse, .stages .now .n { animation: none; }
  .bar.indeterminate i { animation-duration: 4s; }
}
</style>
