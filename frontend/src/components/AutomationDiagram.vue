<script setup lang="ts">
import { computed, useId } from "vue";

import { NODES, type NodeKey, type NodeNote, type Signal } from "@/utils/automation";

/**
 * رسم عملية الأتمتة كما تعمل فعلًا، مشترك بين «الأتمتة» و«مباشر».
 * القراءة من المنصة (مزامنة وتدقيق) → اقتراح → اعتماد المعلم (البوابة البشرية) → تطبيق → تحقق → بطاقة الأداء،
 * وحزمة التحضير فرع قراءة فقط إلى سطح المكتب، والعامل والدورة الأسبوعية في الأسفل.
 * في «مباشر» يتحرك: العقدة الجارية تنبض ومسارها يسري، وكل صفحة تُقرأ أو تُكتب تعبر الرسم إشارةً،
 * والعقد التي مرت بها المهمة تبقى مضاءة وما سواها يخفت.
 */
const props = withDefaults(defineProps<{
  notes: Record<string, NodeNote>;
  worker: { label: string; tone: string };
  weeklyNote: string;
  /** عنوان شريط الدورة، وفيه موعد القادمة بتاريخه ووقته */
  weeklyTitle?: string;
  /** العقدة التي يجري فيها العمل الآن */
  active?: string;
  /** العقد التي مرت بها المهمة المعروضة؛ null خارج «مباشر» */
  trail?: string[] | null;
  /** العقدة التي توقفت عندها المهمة */
  failed?: string;
  /** تقدّم العقدة الجارية بين 0 و1 */
  progress?: number | null;
  signals?: Signal[];
  /** الدورة تعتمد الروتيني تلقائيًا؛ false = للمراجعة فقط */
  autoApprove?: boolean;
}>(), { weeklyTitle: "الدورة الأسبوعية", active: "", trail: null, failed: "", progress: null, signals: () => [],
        autoApprove: false });

const uid = useId();
const W = 1000, H = 552, BW = 168, BH = 92;
const byKey = (k: NodeKey) => NODES.find((s) => s.key === k)!;

// سهم بين مركزي صندوقين (أفقي أو عمودي)، بالاتجاه من a إلى b
function arrow(a: NodeKey, b: NodeKey): string {
  const A = byKey(a), B = byKey(b);
  if (A.y === B.y) {
    const dir = B.x < A.x ? -1 : 1;
    const x1 = A.x + (dir < 0 ? 0 : BW), x2 = B.x + (dir < 0 ? BW : 0);
    return `M${x1},${A.y + BH / 2} L${x2},${B.y + BH / 2}`;
  }
  const x = A.x + BW / 2;
  return `M${x},${A.y + BH} L${x},${B.y}`;
}
const FLOW: [NodeKey, NodeKey][] = [["platform", "fetch"], ["fetch", "audit"], ["audit", "plan"], ["plan", "approve"],
  ["approve", "apply"], ["apply", "verify"], ["verify", "scorecard"]];

const pf = byKey("platform"), ap = byKey("apply"), pr = byKey("prep"), vf = byKey("verify");
const EDGES: Record<string, string> = {
  ...Object.fromEntries(FLOW.map(([a, b]) => [`${a}>${b}`, arrow(a, b)])),
  // التطبيق يكتب على المنصة: عودة منقّطة (backIn عكسها: قراءة الدرس قبل الإضافة)
  back: `M${ap.x + BW / 2},${ap.y} C ${ap.x + BW / 2},190 ${pf.x + BW / 2},200 ${pf.x + BW / 2},${pf.y + BH}`,
  backIn: `M${pf.x + BW / 2},${pf.y + BH} C ${pf.x + BW / 2},200 ${ap.x + BW / 2},190 ${ap.x + BW / 2},${ap.y}`,
  // حزمة التحضير: فرع قراءة فقط من المنصة إلى سطح المكتب، لا يمر بالاعتماد ولا يكتب على المنصة
  side: `M${pf.x + BW / 2},${pf.y} L${pf.x + BW / 2},8 L${pr.x + BW / 2},8 L${pr.x + BW / 2},${pr.y}`,
};

// طول كل مسار تقريبًا (للخطوط المستقيمة يُحسب، وللمنحنى يُقدَّر) ← مدة عبور الإشارة
function polyLength(d: string): number {
  const pts = [...d.matchAll(/(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g)].map((m) => [Number(m[1]), Number(m[2])]);
  return pts.slice(1).reduce((sum, p, i) => sum + Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]), 0);
}
const SPEED = 520; // بكسل/ث
const dur = (k: string) => Math.round(Math.min(1700, Math.max(280, ((k.startsWith("back") ? 560 : polyLength(EDGES[k])) / SPEED) * 1000)));

/** المسارات التي تسري ما دامت العقدة تعمل */
const FLOWING: Record<NodeKey, string[]> = {
  platform: [], fetch: ["platform>fetch"], audit: ["platform>fetch", "fetch>audit"], plan: ["audit>plan"],
  approve: ["plan>approve"], apply: ["approve>apply", "back"], verify: ["apply>verify"],
  scorecard: ["verify>scorecard"], prep: ["side"],
};
/** طريق صفحة تُقرأ من المنصة إلى العقدة (مسار الكتابة نفسه يحمل القراءة عائدةً، بلونها) */
const READ: Record<NodeKey, string[]> = {
  platform: [], fetch: ["platform>fetch"], audit: ["platform>fetch", "fetch>audit"],
  plan: ["platform>fetch", "fetch>audit", "audit>plan"], approve: [], apply: ["backIn"], verify: ["backIn", "apply>verify"],
  scorecard: [], prep: ["side"],
};

const live = computed(() => props.trail !== null);
const done = computed(() => (props.progress === null ? null : Math.min(1, Math.max(0, props.progress))));
const runEdges = computed(() => new Set(props.active ? FLOWING[props.active as NodeKey] ?? [] : []));
const trailEdges = computed(() => new Set((props.trail ?? []).flatMap((k) => FLOWING[k as NodeKey] ?? [])));
function edgeState(k: string): string {
  if (runEdges.value.has(k)) return "run";
  if (trailEdges.value.has(k)) return "trail";
  return live.value ? "faded" : "";
}
const marker = (k: string) => `url(#${uid}-${edgeState(k) === "run" || edgeState(k) === "trail" ? "hot" : "arr"})`;

function tone(k: NodeKey): string {
  if (props.active === k) return "run";
  if (props.failed === k) return "bad";
  if (props.trail) return props.trail.includes(k) ? "done" : "dim";
  const l = props.notes[k];
  return l?.ok === false ? "bad" : l?.ok === true ? "ok" : "idle";
}

// الإشارات: كل صفحة مقروءة تعبر مقاطع طريقها واحدًا بعد الآخر، والكتابة تعود من التطبيق إلى المنصة
interface Seg { key: string; d: string; delay: number; dur: number; kind: Signal["kind"] }
const segments = computed<Seg[]>(() => props.signals.flatMap((s) => {
  const keys = s.kind === "write" ? ["back"] : s.kind === "read" ? READ[s.node] ?? [] : [];
  let t = s.delay;
  return keys.map((k, i) => {
    const seg = { key: `${s.id}-${i}`, d: EDGES[k], delay: t, dur: dur(k), kind: s.kind };
    t += seg.dur * 0.9;
    return seg;
  });
}));
const sparks = computed(() => props.signals.filter((s) => s.kind === "file" || (s.kind === "read" && !READ[s.node]?.length)));

// صمّامات الكتابة كما يطبّقها الخادم (safety.py و pipeline._guard_apply)، قائمة HTML تحت الرسم لا تُقص
const SAFEGUARDS = [
  "لا يُكتب شيء قبل اعتمادك، والاعتماد صالح 48 ساعة ويسقط إن تغيّر الدرس بعده",
  "درس مطابقته بالخطة غير مؤكدة لا يُقترح له ولا يُعتمد حتى تؤكده",
  "جلب حديث قبل كل كتابة إن كان آخر جلب أقدم من ساعة",
  "أي نقص في دروس المنصة يوقف المزامنة حتى تؤكد الحذف",
  "التطبيق يتوقف عند أول خطأ غير متوقع، وما بعده يبقى معتمدًا",
  "قراءة بعدية لكل كتابة؛ كتابة خاطئة أو تحققان فاشلان يوقفان الكتابة آليًا",
  "إضافة فقط في المحتوى، ومواعيد التقييم القائمة لا تُمس",
  "حد التغييرات في الدورة = حصص الصف في نافذتها",
];
const weeklySub = computed(() => (props.autoApprove
  ? "كل اثنين 7:00: تعتمد الروتيني الآمن تلقائيًا (تواريخ، إسناد، نشر) وتطبّقه بالصمّامات، ثم التحقق وحزمتا التحضير."
  : "كل اثنين 7:00، للمراجعة فقط: تجلب وتقترح وتتحقق وتبني حزمتي التحضير، ولا يُطبَّق إلا ما اعتمدته."));
</script>

<template>
  <div class="diagram-wrap">
  <div class="scroll">
  <svg :viewBox="`0 0 ${W} ${H}`" role="img" aria-label="رسم عملية الأتمتة" :class="{ live }">
    <defs>
      <marker :id="`${uid}-arr`" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" class="arrow-head" />
      </marker>
      <marker :id="`${uid}-hot`" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" class="arrow-head hot" />
      </marker>
    </defs>

    <!-- مساران: قراءة (أعلى) وكتابة (أسفل) -->
    <text x="984" y="30" class="lane">① القراءة من المنصة والاقتراح</text>
    <text x="984" y="222" class="lane">② الاعتماد ثم الكتابة والتحقق</text>

    <path v-for="[a, b] in FLOW" :key="a + b" :d="EDGES[`${a}>${b}`]" :class="['flow', edgeState(`${a}>${b}`)]"
          :marker-end="marker(`${a}>${b}`)" />
    <path :d="EDGES.back" :class="['flow', 'back', edgeState('back')]" :marker-end="marker('back')" />
    <text :x="vf.x + 40" y="200" class="hint">كتابة على المنصة بعد اعتمادك</text>
    <path :d="EDGES.side" :class="['flow', 'side', edgeState('side')]" :marker-end="marker('side')" />
    <text :x="pr.x + 6" :y="pr.y + BH + 18" class="hint">التحضير والعروض وورقة العمل</text>
    <text :x="pr.x + 6" :y="pr.y + BH + 34" class="hint">معدّلة + صف الرسالة الأسبوعية</text>

    <!-- الإشارات المتحركة: تحت الصناديق، فتبدو داخلة فيها خارجة منها -->
    <g class="signals" aria-hidden="true">
      <path v-for="s in segments" :key="s.key" :d="s.d" pathLength="100" :class="['packet', s.kind]"
            :style="{ animationDuration: `${s.dur}ms`, animationDelay: `${s.delay}ms` }" />
    </g>

    <g v-for="s in NODES" :key="s.key" :class="['node', tone(s.key), { human: s.human }]" :transform="`translate(${s.x},${s.y})`">
      <rect v-if="active === s.key" class="halo" x="-7" y="-7" :width="BW + 14" :height="BH + 14" rx="20" />
      <rect :width="BW" :height="BH" rx="14" />
      <circle v-if="active === s.key" cx="16" cy="16" r="5" class="dot" />
      <g v-else-if="tone(s.key) === 'done'" class="tick" role="img" aria-label="مرّت بها المهمة">
        <circle cx="17" cy="17" r="8" />
        <path d="M13,17 l3,3 l5,-6" />
      </g>
      <text :x="BW - 14" y="27" class="title">{{ s.title }}</text>
      <text :x="BW - 14" y="44" class="sub">{{ s.sub }}</text>
      <text :x="BW - 14" y="62" class="note">{{ notes[s.key]?.note }}</text>
      <text v-if="notes[s.key]?.when" :x="BW - 14" y="77" class="when">{{ notes[s.key]?.when }}</text>
      <template v-if="active === s.key && done !== null">
        <rect x="12" :y="BH - 9" :width="BW - 24" height="4" rx="2" class="track" />
        <rect :x="12 + (BW - 24) * (1 - done)" :y="BH - 9" :width="(BW - 24) * done" height="4" rx="2" class="fill" />
      </template>
    </g>
    <g aria-hidden="true">
      <rect v-for="s in sparks" :key="`spark-${s.id}`" :x="byKey(s.node).x" :y="byKey(s.node).y" :width="BW" :height="BH"
            rx="14" class="spark" :style="{ animationDelay: `${s.delay}ms` }" />
    </g>

    <!-- شريط الدورة الأسبوعية والعامل -->
    <g transform="translate(16,392)">
      <rect :width="968" height="72" rx="14" class="band" />
      <text x="954" y="28" class="title">{{ weeklyTitle }}</text>
      <text x="14" y="28" class="hint">{{ weeklyNote }}</text>
      <text x="954" y="52" class="sub">{{ weeklySub }}</text>
    </g>
    <g transform="translate(16,484)">
      <rect :width="968" height="56" rx="14" :class="['band', worker.tone]" />
      <text x="954" y="24" class="title">العامل (neo_worker)</text>
      <text x="954" y="44" class="sub">مهمة واحدة في كل مرة · نبض كل 5 ثوانٍ · يعيد تشغيل نفسه عند تغيّر الكود وهو خامل · {{ worker.label }}</text>
    </g>
  </svg>
  </div>
  <section class="valves" aria-label="الصمّامات">
    <h3>الصمّامات قبل أي كتابة على المنصة</h3>
    <ul><li v-for="g in SAFEGUARDS" :key="g">{{ g }}</li></ul>
  </section>
  </div>
</template>

<style scoped>
/* الرسم لا يصغر عن 880px فيبقى نصه مقروءًا (لا 6.7px)، ويُمرَّر أفقيًا في الشاشات الضيقة.
   direction: rtl يبقي «%» والأرقام في مكانها من النص العربي؛ ولذلك المرساة معكوسة: start = يمين x، end = يساره. */
.diagram-wrap { display: grid; gap: 10px; }
.scroll { overflow-x: auto; }
svg { inline-size: 100%; min-inline-size: 880px; block-size: auto; display: block; font-family: inherit; direction: rtl; unicode-bidi: isolate; }
.lane { font-size: 15px; font-weight: 700; fill: var(--muted); text-anchor: start; }
.hint { font-size: 12px; fill: var(--muted); text-anchor: end; }
.flow { fill: none; stroke: var(--line); stroke-width: 2.5; transition: stroke .4s, opacity .4s; }
.flow.back { stroke-dasharray: 6 6; stroke: var(--maroon); opacity: .7; }
.flow.side { stroke-dasharray: 3 5; stroke: var(--muted); }
.flow.trail { stroke: var(--maroon); opacity: .6; }
.flow.faded { opacity: .35; }
.flow.run { stroke: var(--maroon); stroke-width: 3.5; opacity: 1; stroke-dasharray: 8 7; animation: march .7s linear infinite; }
.arrow-head { fill: var(--line); }
.arrow-head.hot { fill: var(--maroon); }

.node { transition: opacity .4s; }
.node rect { fill: var(--surface); stroke: var(--line); stroke-width: 1.5; transition: stroke .3s, fill .3s, stroke-width .3s; }
.node.ok rect { stroke: var(--maroon); }
.node.bad rect { stroke: var(--bad); fill: var(--bad-soft); }
.node.run rect { stroke: var(--maroon); stroke-width: 3; }
.node.done rect { stroke: var(--maroon); stroke-width: 2; }
.node.dim { opacity: .5; }
.node.human rect { fill: var(--maroon-soft); stroke: var(--maroon); stroke-dasharray: 5 4; }
.node.human.run rect { stroke-dasharray: none; }
.node .halo { fill: none; stroke: var(--maroon); stroke-width: 6; opacity: .25; animation: halo 1.6s ease-in-out infinite; }
.node text { text-anchor: start; fill: var(--fg); }
.node .title, g .title { font-size: 16px; font-weight: 700; fill: var(--fg); text-anchor: start; }
.node .sub, g .sub { font-size: 12px; fill: var(--muted); text-anchor: start; }
.node .note { font-size: 12px; font-weight: 600; fill: var(--maroon); }
.node .when { font-size: 11px; fill: var(--muted); }
.node.bad .note { fill: var(--bad); }
.node .track { fill: var(--code-bg); stroke: none; }
.node .fill { fill: var(--maroon); stroke: none; transition: width .6s ease, x .6s ease; }
.tick circle { fill: var(--maroon); }
.tick path { fill: none; stroke: var(--on-brand); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.dot { fill: var(--maroon); animation: pulse 1.2s infinite; }

.packet {
  fill: none; stroke-width: 8; stroke-linecap: round; stroke-dasharray: .5 400;
  animation-name: travel; animation-timing-function: cubic-bezier(.45, .05, .55, .95); animation-fill-mode: both;
}
.packet.read { stroke: var(--slate); color: var(--slate); filter: drop-shadow(0 0 3px currentColor); }
.packet.write { stroke: var(--maroon); color: var(--maroon); filter: drop-shadow(0 0 4px currentColor); }
.spark { fill: none; stroke: var(--ok); stroke-width: 2; opacity: 0; animation: spark 1.1s ease-out both; }

.band { fill: var(--surface); stroke: var(--line); stroke-width: 1.5; }
.band.soft { fill: var(--code-bg); }
.band.bad { stroke: var(--bad); fill: var(--bad-soft); }
.band.run { stroke: var(--maroon); stroke-width: 3; }
.valves { border: 1px solid var(--line); border-radius: 12px; background: var(--code-bg); padding: 10px 14px; }
.valves h3 { margin: 0 0 6px; font-size: var(--fs-md); }
.valves ul { margin: 0; padding-inline-start: 18px; display: grid; gap: 4px 24px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); font-size: var(--fs-base); }

@keyframes pulse { 50% { opacity: .2; } }
@keyframes march { from { stroke-dashoffset: 15; } to { stroke-dashoffset: 0; } }
@keyframes halo { 0%, 100% { opacity: .12; } 50% { opacity: .45; } }
@keyframes travel {
  0% { stroke-dashoffset: 0; opacity: 0; }
  10%, 90% { opacity: 1; }
  100% { stroke-dashoffset: -100; opacity: 0; }
}
@keyframes spark {
  0% { opacity: .9; stroke-width: 2; }
  100% { opacity: 0; stroke-width: 18; }
}
@media (prefers-reduced-motion: reduce) {
  .packet, .spark { display: none; }
  .flow.run, .node .halo, .dot { animation: none; }
}
</style>
