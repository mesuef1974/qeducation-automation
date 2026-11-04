<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { neo } from "@/api/neo";
import type { Run, Scorecard, WeeklyState } from "@/api/types";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";
import { ago, fmtStamp } from "@/utils/format";

/**
 * صفحة الأتمتة: رسم لعملية الأتمتة كما تعمل فعلًا، بحالة حيّة لكل مرحلة من آخر عملياتها.
 * القراءة من المنصة (مزامنة وتدقيق) → اقتراح → اعتماد المعلم (البوابة البشرية) → تطبيق → تحقق → بطاقة الأداء،
 * وحزمة التحضير فرع قراءة فقط إلى سطح المكتب، والعامل والدورة الأسبوعية في الأسفل. لا شيء هنا يكتب على المنصة.
 */
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
onMounted(() => { void load(); void classes.load(); timer = window.setInterval(load, 60_000); });
onBeforeUnmount(() => window.clearInterval(timer));
const stop = jobs.onFinished(() => void load());
onBeforeUnmount(stop);

// ------------------------------------------------------------ المراحل وربطها بأنواع العمليات
interface StageSpec { key: string; title: string; sub: string; kinds: string[]; x: number; y: number; human?: boolean }
const W = 1000, H = 600, BW = 168, BH = 92;
const STAGES: StageSpec[] = [
  { key: "platform", title: "منصة قطر للتعليم", sub: "LMS · الصفان 10/3 و12/2", kinds: [], x: 816, y: 60 },
  { key: "fetch", title: "مزامنة", sub: "قراءة الدروس والتقييمات", kinds: ["fetch"], x: 612, y: 60 },
  { key: "audit", title: "تدقيق الجودة", sub: "صورة، وصف، أقسام، تقييم، نتاج", kinds: ["audit"], x: 408, y: 60 },
  { key: "plan", title: "اقتراح", sub: "تواريخ، إسناد، نشر، محتوى", kinds: ["plan", "assign_plan", "publish_plan", "content_plan"], x: 204, y: 60 },
  { key: "approve", title: "اعتماد المعلم", sub: "البوابة البشرية: كل كتابة بقرارك", kinds: [], x: 204, y: 250, human: true },
  { key: "apply", title: "تطبيق", sub: "إضافة فقط · آمن التكرار", kinds: ["apply", "assign_apply", "publish_apply", "content_apply"], x: 408, y: 250 },
  { key: "verify", title: "تحقق", sub: "منظور الطالب وتدقيق بعدي", kinds: ["verify", "audit"], x: 612, y: 250 },
  { key: "scorecard", title: "بطاقة الأداء", sub: "8 معايير · لقطة يومية", kinds: [], x: 816, y: 250 },
  { key: "prep", title: "حزمة التحضير", sub: "سطح المكتب · قراءة فقط", kinds: ["prep"], x: 16, y: 60 },
];
const byKey = (k: string) => STAGES.find((s) => s.key === k)!;

interface Live { last?: Run; count: number; ok: boolean | null; note: string }
const live = computed<Record<string, Live>>(() => {
  const out: Record<string, Live> = {};
  for (const s of STAGES) {
    const mine = runs.value.filter((r) => s.kinds.includes(r.kind));
    const last = mine[0];
    out[s.key] = { last, count: mine.length, ok: last ? last.ok : null, note: last ? `${last.class_name} · ${ago(last.finished_at ?? last.started_at)}` : "لم تعمل بعد" };
  }
  const pending = Object.values(classes.openReview).reduce((a, b) => a + b, 0);
  out.approve = { count: pending, ok: pending ? null : true, note: pending ? `${pending} اقتراحًا بانتظار قرارك` : "لا شيء بانتظارك" };
  const cov = scorecard.value?.current.criteria.find((c) => c.key === "coverage");
  out.scorecard = { count: 0, ok: cov ? true : null, note: cov?.value != null ? `تغطية الأتمتة ${cov.value}%` : "بلا لقطة بعد" };
  const sess = jobs.session;
  out.platform = { count: 0, ok: sess ? !sess.expired : null, note: sess ? (sess.expired ? "الجلسة منتهية: neo_login" : "الجلسة سارية") : "…" };
  return out;
});

const activeKey = computed(() => {
  const j = jobs.active.find((x) => x.status === "running");
  if (!j) return "";
  if (j.kind === "audit") return "audit";
  if (j.kind === "verify") return "verify";
  if (j.kind === "weekly") return "apply";
  if (j.kind === "prep_pack") return "prep";
  return j.kind.endsWith("_plan") ? "plan" : j.kind.endsWith("_apply") ? "apply" : "fetch";
});

// سهم بين مركزي صندوقين (أفقي أو عمودي)، بالاتجاه من a إلى b
function arrow(a: string, b: string): string {
  const A = byKey(a), B = byKey(b);
  if (A.y === B.y) {
    const dir = B.x < A.x ? -1 : 1;
    const x1 = A.x + (dir < 0 ? 0 : BW), x2 = B.x + (dir < 0 ? BW : 0);
    return `M${x1},${A.y + BH / 2} L${x2},${B.y + BH / 2}`;
  }
  const x = A.x + BW / 2;
  return `M${x},${A.y + BH} L${x},${B.y}`;
}
const FLOW: [string, string][] = [["platform", "fetch"], ["fetch", "audit"], ["audit", "plan"], ["plan", "approve"],
  ["approve", "apply"], ["apply", "verify"], ["verify", "scorecard"]];

const tone = (k: string) => {
  if (activeKey.value === k) return "run";
  const l = live.value[k];
  return l?.ok === false ? "bad" : l?.ok === true ? "ok" : "idle";
};
const worker = computed(() => {
  const s = jobs.session;
  if (!s) return { label: "…", tone: "idle" };
  if (!s.worker_alive) return { label: "العامل متوقف", tone: "bad" };
  return s.worker_busy ? { label: "العامل ينفّذ مهمة", tone: "run" } : { label: `العامل جاهز · ${s.queued} في الطابور`, tone: "ok" };
});
const SAFEGUARDS = [
  "إضافة فقط: لا يُعدَّل موجود ولا يُحذف",
  "يُقرأ الدرس قبل كل إضافة؛ الموجود يُتخطّى",
  "حد 20 تغييرًا للمرحلة في الدورة الأسبوعية",
  "فحص شكل المنصة قبل الكتابة (انكماش > 20% يوقف)",
  "تحقق بعدي من منظور الطالب",
  "بيانات الطلاب محلية فقط",
];
</script>

<template>
  <header class="page-head">
    <div>
      <h1>الأتمتة</h1>
      <p>كيف تعمل: قراءة من المنصة، ثم اقتراح، ثم اعتمادك، ثم تطبيق وتحقق. كل صندوق يعرض آخر عملية له.</p>
    </div>
    <span class="pill" :class="worker.tone">{{ worker.label }}</span>
  </header>
  <div v-if="error" class="error-box">{{ error }}</div>

  <section class="card diagram">
    <svg :viewBox="`0 0 ${W} ${H}`" role="img" aria-label="رسم عملية الأتمتة">
      <defs>
        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" class="arrow-head" />
        </marker>
      </defs>

      <!-- مساران: قراءة (أعلى) وكتابة (أسفل) -->
      <text x="984" y="30" class="lane">① القراءة من المنصة والاقتراح</text>
      <text x="984" y="222" class="lane">② الاعتماد ثم الكتابة والتحقق</text>

      <path v-for="[a, b] in FLOW" :key="a + b" :d="arrow(a, b)" class="flow" marker-end="url(#arr)" />
      <!-- التطبيق يكتب على المنصة: عودة منقّطة -->
      <path :d="`M${byKey('apply').x + BW / 2},${byKey('apply').y} C ${byKey('apply').x + BW / 2},190 ${byKey('platform').x + BW / 2},200 ${byKey('platform').x + BW / 2},${byKey('platform').y + BH}`"
            class="flow back" marker-end="url(#arr)" />
      <text :x="byKey('verify').x + 40" y="200" class="hint">كتابة على المنصة بعد اعتمادك</text>
      <!-- حزمة التحضير: فرع قراءة فقط من المنصة إلى سطح المكتب، لا يمر بالاعتماد ولا يكتب على المنصة -->
      <path :d="`M${byKey('platform').x + BW / 2},${byKey('platform').y} L${byKey('platform').x + BW / 2},8 L${byKey('prep').x + BW / 2},8 L${byKey('prep').x + BW / 2},${byKey('prep').y}`"
            class="flow side" marker-end="url(#arr)" />
      <text :x="byKey('prep').x + 6" :y="byKey('prep').y + BH + 18" class="hint">التحضير والعروض وورقة العمل</text>
      <text :x="byKey('prep').x + 6" :y="byKey('prep').y + BH + 34" class="hint">معدّلة + صف الرسالة الأسبوعية</text>

      <g v-for="s in STAGES" :key="s.key" :class="['node', tone(s.key), { human: s.human }]" :transform="`translate(${s.x},${s.y})`">
        <rect :width="BW" :height="BH" rx="14" />
        <circle v-if="activeKey === s.key" cx="16" cy="16" r="5" class="dot" />
        <text :x="BW - 14" y="30" class="title">{{ s.title }}</text>
        <text :x="BW - 14" y="50" class="sub">{{ s.sub }}</text>
        <text :x="BW - 14" y="76" class="note">{{ live[s.key]?.note }}</text>
      </g>

      <!-- شريط الدورة الأسبوعية والعامل -->
      <g transform="translate(204,392)">
        <rect :width="780" height="72" rx="14" class="band" />
        <text x="766" y="28" class="title">الدورة الأسبوعية — الخميس 14:00</text>
        <text x="766" y="52" class="sub">
          تنفّذ ①②③ للروتيني تلقائيًا (تواريخ، إسناد، نشر، نقاط) بصمّامات، ثم لقطة بطاقة الأداء.
          {{ weekly?.enabled ? `القادمة: ${fmtStamp(weekly.next_at)}` : "معطّلة" }}
          <tspan v-if="weekly?.last"> · الأخيرة: {{ weekly.last.status_label }} {{ ago(weekly.last.finished_at) }}</tspan>
        </text>
      </g>
      <g transform="translate(204,484)">
        <rect :width="780" height="56" rx="14" :class="['band', worker.tone]" />
        <text x="766" y="24" class="title">العامل (neo_worker)</text>
        <text x="766" y="44" class="sub">مهمة واحدة في كل مرة · نبض كل 5 ثوانٍ · يعيد تشغيل نفسه عند تغيّر الكود وهو خامل · {{ worker.label }}</text>
      </g>
      <g transform="translate(16,392)">
        <rect width="172" height="148" rx="14" class="band soft" />
        <text x="158" y="24" class="title">الصمّامات</text>
        <text v-for="(g, i) in SAFEGUARDS" :key="g" x="158" :y="44 + i * 17" class="tiny">• {{ g }}</text>
      </g>
    </svg>
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
            <td class="muted">{{ ago(r.finished_at ?? r.started_at) }}</td>
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
svg { inline-size: 100%; block-size: auto; display: block; font-family: inherit; direction: ltr; }
.lane { font-size: 15px; font-weight: 700; fill: var(--muted); text-anchor: end; }
.hint { font-size: 12px; fill: var(--muted); text-anchor: start; }
.flow { fill: none; stroke: var(--line); stroke-width: 2.5; }
.flow.back { stroke-dasharray: 6 6; stroke: var(--brand); opacity: .7; }
.flow.side { stroke-dasharray: 3 5; stroke: var(--muted); }
.arrow-head { fill: var(--line); }
.node rect { fill: var(--surface); stroke: var(--line); stroke-width: 1.5; }
.node.ok rect { stroke: var(--brand); }
.node.bad rect { stroke: var(--bad); fill: var(--bad-soft); }
.node.run rect { stroke: var(--brand); stroke-width: 3; }
.node.human rect { fill: var(--maroon-soft); stroke: var(--maroon); stroke-dasharray: 5 4; }
.node text { text-anchor: end; fill: var(--fg); }
.node .title, .band + .title, g .title { font-size: 16px; font-weight: 700; fill: var(--fg); text-anchor: end; }
.node .sub, g .sub { font-size: 11.5px; fill: var(--muted); text-anchor: end; }
.node .note { font-size: 12px; font-weight: 600; fill: var(--brand-deep); }
.node.bad .note { fill: var(--bad); }
.dot { fill: var(--brand); animation: pulse 1.2s infinite; }
@keyframes pulse { 50% { opacity: .2; } }
.band { fill: var(--surface); stroke: var(--line); stroke-width: 1.5; }
.band.soft { fill: var(--code-bg); }
.band.bad { stroke: var(--bad); fill: var(--bad-soft); }
.band.run { stroke: var(--brand); stroke-width: 3; }
.tiny { font-size: 11px; fill: var(--fg); text-anchor: end; }
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
