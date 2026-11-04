<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { neo } from "@/api/neo";
import type { Usage, UsagePeriod } from "@/api/types";
import { fmtShort, fmtStamp, fmtWhen } from "@/utils/format";

/**
 * استهلاك Claude: الجلسة واليوم والأسبوع والشهر، وكل يوم، والنماذج، وأين ذهب الاستهلاك، والجلسات.
 * المصدر قاعدة البيانات بعد استيراد سجلات مجلد Claude تزايديًا (neo/services/usage.py). قراءة فقط.
 */
const data = ref<Usage | null>(null);
const error = ref("");
const loading = ref(false);
const period = ref<UsagePeriod>("session");
const table = ref(false);

const note = ref("");
async function load(session?: string, refresh = false) {
  loading.value = true;
  try {
    data.value = await (refresh ? neo.usageImport(session) : neo.usage(session));
    const im = data.value.imported;
    note.value = im ? `استُوردت ${n(im.new)} خطوة جديدة${im.pending ? "، وبقي ما يستورده العامل في الدقائق القادمة" : ""}.` : "";
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
onMounted(() => load());

const PERIODS: { key: UsagePeriod; label: string }[] = [
  { key: "session", label: "هذه الجلسة" }, { key: "today", label: "اليوم" },
  { key: "week", label: "آخر 7 أيام" }, { key: "month", label: "هذا الشهر" },
];
const NUM = new Intl.NumberFormat("ar-QA-u-nu-latn");
const COMPACT = new Intl.NumberFormat("ar-QA-u-nu-latn", { notation: "compact", maximumFractionDigits: 1 });
const n = (v: number) => NUM.format(v);
const c = (v: number) => COMPACT.format(v);
const pct = (v: number, of: number) => (of ? `${Math.round((v / of) * 1000) / 10}٪` : "-");

const totals = computed(() => data.value?.totals);
const cur = computed(() => totals.value?.[period.value]);
const models = computed(() => data.value?.models[period.value] ?? []);
const groups = computed(() => data.value?.groups[period.value] ?? []);
const maxOf = (rows: { effective: number }[]) => Math.max(1, ...rows.map((r) => r.effective));

// الرسم اليومي: شبكة بثلاثة خطوط عند قيم مستديرة، والأسبوع الأخير مميَّز
const daily = computed(() => data.value?.daily ?? []);
const dailyMax = computed(() => {
  const m = Math.max(1, ...daily.value.map((d) => d.effective));
  const step = 10 ** Math.floor(Math.log10(m));
  return Math.ceil(m / step) * step;
});
const ticks = computed(() => [1, 0.5].map((f) => dailyMax.value * f));
const inWeek = (day: string) => !!data.value && day >= data.value.week_start;
const hover = ref<number | null>(null);
const hovered = computed(() => (hover.value === null ? null : daily.value[hover.value]));

const shortModel = (m: string) => m.replace(/^claude-/, "").replace(/-(\d+)-(\d+)$/, " $1.$2");
const shortSession = (s: string) => s.slice(0, 8);
/** اسم مجلد Claude Code للمشروع (D--shschool-mvp) بصيغة المسار، وجذر المجلد للجلسات المُصدَّرة */
const projectLabel = (p: string) => (p ? p.replace(/^([A-Za-z])--/, "$1:\\").replace(/--claude-worktrees-.*/, " (نسخة تطوير)") : "(الجذر)");
</script>

<template>
  <header class="page-head">
    <div>
      <h1>الاستهلاك</h1>
      <p>استهلاك Claude من سجلات الجلسات في مجلد Claude، محفوظًا في قاعدة البيانات. أرقام فقط، بلا أي نص من المحادثات.</p>
    </div>
    <div class="head-side">
      <small class="muted">آخر استيراد {{ fmtWhen(data?.imported_at) }}</small>
      <button class="btn sm" :disabled="loading" @click="load(data?.session ?? undefined, true)">
        <i v-if="loading" class="spinner" /> حدّث الآن
      </button>
    </div>
  </header>

  <div v-if="note" class="note-box">{{ note }}</div>
  <div v-if="error" class="error-box">{{ error }}</div>
  <p v-else-if="!data" class="empty"><i class="spinner" /> تحميل...</p>
  <p v-else-if="!data.first" class="empty">
    لا سجلات بعد (العامل يستورد كل 10 دقائق، أو اضغط «حدّث الآن»). المجلدات المقروءة:
    <span v-for="s in data.sources" :key="s.path" class="mono"> {{ s.path }} ({{ s.found ? "موجود" : "غير موجود" }})</span>
  </p>

  <template v-else-if="totals && cur">
    <!-- المؤشرات الأربع -->
    <section class="kpis" aria-label="ملخص الاستهلاك">
      <button v-for="p in PERIODS" :key="p.key" class="card kpi" :class="{ on: period === p.key }"
              :aria-pressed="period === p.key" @click="period = p.key">
        <small class="muted">{{ p.label }}</small>
        <b class="big">{{ c(totals[p.key].effective) }}</b>
        <small class="muted">وحدة فعلية · {{ c(totals[p.key].tokens) }} رمز</small>
        <small class="muted">{{ n(totals[p.key].turns) }} خطوة · {{ n(totals[p.key].sessions) }} جلسة</small>
      </button>
    </section>

    <!-- كل يوم -->
    <section class="card">
      <header class="c-head">
        <div>
          <h2>الاستهلاك اليومي · آخر 30 يومًا</h2>
          <small class="muted">بالوحدات الفعلية؛ الأعمدة الداكنة آخر 7 أيام. مرّر على عمود لتفاصيله.</small>
        </div>
        <button class="btn ghost sm" :aria-pressed="table" @click="table = !table">{{ table ? "الرسم" : "جدول" }}</button>
      </header>
      <div v-if="!table" class="daily" role="img" :aria-label="`الاستهلاك اليومي، أعلى يوم ${c(dailyMax)}`">
        <div class="plot">
          <div v-for="t in ticks" :key="t" class="grid" :style="{ insetBlockEnd: `${(t / dailyMax) * 100}%` }">
            <span>{{ c(t) }}</span>
          </div>
          <div class="bars">
            <div v-for="(d, i) in daily" :key="d.day" class="col" @mouseenter="hover = i" @mouseleave="hover = null"
                 @focus="hover = i" @blur="hover = null" tabindex="0" :aria-label="`${fmtShort(d.day)}: ${n(d.effective)}`">
              <i :class="{ week: inWeek(d.day), zero: !d.effective }" :style="{ blockSize: `${(d.effective / dailyMax) * 100}%` }" />
            </div>
          </div>
          <div v-if="hovered" class="tip" role="status">
            <b>{{ fmtShort(hovered.day) }}</b>
            <span>{{ n(hovered.effective) }} وحدة فعلية</span>
            <span class="muted">{{ n(hovered.tokens) }} رمز · {{ n(hovered.turns) }} خطوة</span>
          </div>
        </div>
        <div class="axis">
          <span>{{ fmtShort(daily[0]?.day) }}</span><span>{{ fmtShort(daily[14]?.day) }}</span><span>اليوم</span>
        </div>
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>اليوم</th><th>وحدة فعلية</th><th>رموز</th><th>خطوات</th></tr></thead>
          <tbody>
            <tr v-for="d in [...daily].reverse().filter((x) => x.turns)" :key="d.day">
              <td>{{ fmtShort(d.day) }}</td><td class="num">{{ n(d.effective) }}</td><td class="num">{{ n(d.tokens) }}</td>
              <td class="num">{{ n(d.turns) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="two">
      <!-- النماذج -->
      <section class="card">
        <h2>النماذج · {{ PERIODS.find((p) => p.key === period)?.label }}</h2>
        <ul class="hbars">
          <li v-for="m in models" :key="m.model" :title="`${n(m.effective)} وحدة فعلية`">
            <span class="lbl mono" dir="ltr">{{ shortModel(m.model) }}</span>
            <span class="track"><i :style="{ inlineSize: `${(m.effective / maxOf(models)) * 100}%` }" /></span>
            <span class="val">{{ c(m.effective) }} <small class="muted">{{ pct(m.effective, cur.effective) }}</small></span>
            <small class="sub muted">{{ n(m.turns) }} خطوة · إدخال {{ c(m.input + m.cache_read + m.cache_write) }} · مخرجات {{ c(m.output) }}</small>
          </li>
        </ul>
      </section>

      <!-- أين ذهب -->
      <section class="card">
        <h2>أين ذهب الاستهلاك</h2>
        <ul class="hbars">
          <li v-for="g in groups" :key="g.name" :title="`${n(g.effective)} وحدة فعلية`">
            <span class="lbl">{{ g.name }}</span>
            <span class="track"><i :style="{ inlineSize: `${(g.effective / maxOf(groups)) * 100}%` }" /></span>
            <span class="val">{{ c(g.effective) }} <small class="muted">{{ pct(g.effective, cur.effective) }}</small></span>
          </li>
        </ul>
      </section>
    </div>

    <!-- المشاريع -->
    <section v-if="data.projects.length" class="card">
      <h2>المشاريع · هذا الشهر</h2>
      <ul class="hbars">
        <li v-for="p in data.projects" :key="p.project" :title="`${n(p.effective)} وحدة فعلية`">
          <span class="lbl mono" dir="ltr">{{ projectLabel(p.project) }}</span>
          <span class="track"><i :style="{ inlineSize: `${(p.effective / maxOf(data.projects)) * 100}%` }" /></span>
          <span class="val">{{ c(p.effective) }} <small class="muted">{{ pct(p.effective, totals.month.effective) }}</small></span>
        </li>
      </ul>
    </section>

    <!-- تفكيك الرموز -->
    <section class="card">
      <h2>تفكيك الرموز · {{ PERIODS.find((p) => p.key === period)?.label }}</h2>
      <div class="split" role="img" aria-label="الرموز الخام مقابل وزنها الفعلي">
        <div v-for="part in [
          { k: 'قراءة سياق محفوظ', raw: cur.cache_read, w: data.weights.cache_read },
          { k: 'حفظ سياق جديد', raw: cur.cache_write, w: data.weights.cache_write },
          { k: 'إدخال جديد', raw: cur.input, w: 1 },
          { k: 'مخرجات', raw: cur.output, w: data.weights.output },
        ]" :key="part.k" class="part">
          <small class="muted">{{ part.k }} <span dir="ltr">×{{ part.w }}</span></small>
          <b>{{ c(part.raw) }}</b> <small class="muted">رمز</small>
          <small>= {{ c(part.raw * part.w) }} فعلية ({{ pct(part.raw * part.w, cur.effective) }})</small>
        </div>
      </div>
    </section>

    <!-- الجلسات -->
    <section class="card">
      <h2>الجلسات</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>الجلسة</th><th>المشروع</th><th>من ← إلى</th><th>النماذج</th><th>خطوات</th><th>وحدة فعلية</th></tr></thead>
          <tbody>
            <tr v-for="s in data.sessions" :key="s.session" :class="{ sel: s.session === data.session }"
                class="click" @click="period = 'session'; load(s.session)">
              <td class="mono">{{ shortSession(s.session) }}</td>
              <td class="mono" dir="ltr">{{ projectLabel(s.project) }}</td>
              <td class="muted">{{ fmtStamp(s.first) }} ← {{ fmtStamp(s.last) }}</td>
              <td class="mono" dir="ltr">{{ s.models.map(shortModel).join("، ") }}</td>
              <td class="num">{{ n(s.turns) }}</td>
              <td class="num">{{ n(s.effective) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <small class="muted">
        الوحدة الفعلية بقيمة رمز إدخال عادي: قراءة سياق محفوظ ×{{ data.weights.cache_read }}، وحفظ سياق جديد ×{{ data.weights.cache_write }}،
        والمخرجات ×{{ data.weights.output }}. الجلسة المضغوطة يبدأ سجلها من آخر ضغط.
        المصادر: <span v-for="s in data.sources" :key="s.path" class="mono">{{ s.path }} ({{ s.found ? `${s.files} ملف` : "غير موجود" }}) </span>
      </small>
    </section>
  </template>
</template>

<style scoped>
.head-side { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
h2 { font-size: 17px; margin: 0 0 10px; }
.card { display: grid; gap: 8px; }
.kpis { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 190px), 1fr)); }
.kpi { text-align: start; cursor: pointer; font: inherit; color: inherit; gap: 2px; border: 1px solid var(--line); }
.kpi.on { border-color: var(--slate); box-shadow: 0 0 0 2px color-mix(in srgb, var(--slate) 25%, transparent); }
.kpi .big { font-size: 30px; line-height: 1.2; font-variant-numeric: tabular-nums; }
.c-head { display: flex; justify-content: space-between; align-items: start; gap: 10px; }
.c-head h2 { margin: 0; }

.daily { display: grid; gap: 6px; }
.plot { position: relative; block-size: 220px; margin-inline-end: 44px; }
.grid { position: absolute; inset-inline: 0; border-block-start: 1px dashed var(--line); }
.grid span { position: absolute; inset-inline-end: -44px; transform: translateY(-50%); font-size: 12px; color: var(--muted); }
.bars { position: absolute; inset: 0; display: flex; align-items: flex-end; gap: 2px; border-block-end: 1px solid var(--muted); }
.col { flex: 1; block-size: 100%; display: flex; align-items: flex-end; cursor: default; outline: none; }
.col i { display: block; inline-size: 100%; max-inline-size: 22px; margin-inline: auto; border-radius: 4px 4px 0 0;
         background: color-mix(in srgb, var(--slate) 40%, var(--surface)); min-block-size: 2px; transition: background .15s; }
.col i.week { background: var(--slate); }
.col i.zero { background: var(--line); }
.col:hover i, .col:focus-visible i { background: var(--maroon); }
.tip { position: absolute; inset-block-start: 4px; inset-inline-start: 4px; display: grid; gap: 2px; font-size: 13px;
       background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; pointer-events: none;
       box-shadow: 0 2px 8px rgb(0 0 0 / .08); }
.axis { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-inline-end: 44px; }

.two { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); }
.hbars { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.hbars li { display: grid; grid-template-columns: minmax(90px, 34%) 1fr auto; align-items: center; gap: 4px 10px; font-size: 14px; }
.hbars .track { block-size: 12px; background: var(--code-bg); border-radius: 4px; overflow: hidden; }
.hbars .track i { display: block; block-size: 100%; background: var(--slate); border-radius: 4px; min-inline-size: 2px; }
.hbars .val { font-variant-numeric: tabular-nums; white-space: nowrap; }
.hbars .sub { grid-column: 1 / -1; font-size: 12px; }

.split { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr)); }
.part { display: grid; gap: 2px; padding: 8px 12px; border: 1px solid var(--line); border-radius: 10px; }
.part b { font-size: 20px; font-variant-numeric: tabular-nums; }
.num { font-variant-numeric: tabular-nums; }
tr.click { cursor: pointer; }
tr.sel td { background: var(--slate-soft); }
.mono { font-family: var(--f-mono, ui-monospace, monospace); font-size: 13px; }
</style>
