<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { neo } from "@/api/neo";
import type { Usage, UsageFilter, UsageQuota } from "@/api/types";
import { ago, fmtShort, fmtStamp } from "@/utils/format";

/**
 * استهلاك Claude من «ميزان» (قراءة فقط): حدود الخطة (الأسبوعية وFable والخمس ساعات) والشهري، ثم مرشّحات النطاق
 * والنماذج يتبعها الرسم اليومي والنماذج وأصل الطلب وتفكيك التوكنز، وتوكنز كل شهر.
 */
const data = ref<Usage | null>(null);
const error = ref("");
const loading = ref(false);
const table = ref(false);
const monthTable = ref(false);

const RANGES = [{ key: "7", label: "7 أيام" }, { key: "30", label: "30 يومًا" }, { key: "90", label: "90 يومًا" },
                { key: "all", label: "الكل" }] as const;
const range = ref<NonNullable<UsageFilter["days"]>>("30");
const from = ref("");
const to = ref("");
const picked = ref<string[]>([]);
const filter = computed<UsageFilter>(() => ({ days: range.value, from: from.value || undefined, to: to.value || undefined,
                                              models: picked.value.length ? picked.value : undefined }));

const NUM = new Intl.NumberFormat("ar-QA-u-nu-latn");
const COMPACT = new Intl.NumberFormat("ar-QA-u-nu-latn", { notation: "compact", maximumFractionDigits: 1 });
const n = (v: number) => NUM.format(v);
const c = (v: number) => COMPACT.format(v);
const pct = (v: number, of: number) => (of ? `${Math.round((v / of) * 1000) / 10}٪` : "-");
const width = (v: number, of: number) => `${of ? Math.min(100, (v / of) * 100) : 0}%`;

async function load(refresh = false) {
  loading.value = true;
  try {
    data.value = await neo.usage(filter.value, refresh);
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
watch(filter, () => load(), { deep: true });
onMounted(() => load());

function setRange(k: NonNullable<UsageFilter["days"]>) {
  range.value = k;
  from.value = "";
  to.value = "";
}
function toggle(m: string) {
  picked.value = picked.value.includes(m) ? picked.value.filter((x) => x !== m) : [...picked.value, m];
}
function reset() {
  setRange("30");
  picked.value = [];
}

// حدود الخطة
const quotas = computed(() => {
  const q = data.value?.quota;
  if (!q) return [];
  return [
    { key: "week", title: "الأسبوعي · كل النماذج", q: q.week },
    { key: "fable", title: "الأسبوعي · Fable", q: q.fable },
    { key: "five_hour", title: "الخمس ساعات", q: q.five_hour && !q.five_hour.stale ? q.five_hour : null },
  ].filter((x): x is { key: string; title: string; q: UsageQuota } => !!x.q);
});
const UTC = new Intl.DateTimeFormat("ar-QA-u-nu-latn", { hour: "2-digit", minute: "2-digit", timeZone: "UTC", hour12: false });
const resetLabel = (q: UsageQuota) => (q.reset ? `تتصفّر ${fmtStamp(q.reset)} (UTC ${UTC.format(new Date(q.reset))})` : "");

// كل يوم
const daily = computed(() => data.value?.daily ?? []);
const dailyMax = computed(() => {
  const m = Math.max(1, ...daily.value.map((d) => d.tokens));
  const step = 10 ** Math.floor(Math.log10(m));
  return Math.ceil(m / step) * step;
});
const ticks = computed(() => [1, 0.5].map((f) => dailyMax.value * f));
const hover = ref<number | null>(null);
const hovered = computed(() => (hover.value === null ? null : daily.value[hover.value]));
const mid = computed(() => daily.value[Math.floor(daily.value.length / 2)]?.day);

// كل شهر
const months = computed(() => data.value?.monthly ?? []);
const monthMax = computed(() => Math.max(1, ...months.value.map((m) => m.tokens)));

const cur = computed(() => data.value?.totals);
const maxTok = (rows: { tokens: number }[]) => Math.max(1, ...rows.map((r) => r.tokens));
</script>

<template>
  <header class="page-head">
    <div>
      <h1>الاستهلاك</h1>
      <p>توكنز Claude وحصة الخطة من «ميزان» على هذا الجهاز. قراءة فقط، أرقام بلا أي نص من المحادثات.</p>
    </div>
    <div class="head-side">
      <small class="muted">عمر البيانات: {{ data ? ago(data.source.fetched_at) : "-" }}</small>
      <button class="btn primary sm" :disabled="loading" @click="load(true)">
        <i v-if="loading" class="spinner" /> تحديث فوري
      </button>
    </div>
  </header>

  <div v-if="error" class="error-box">{{ error }}</div>
  <p v-else-if="!data" class="empty"><i class="spinner" /> تحميل...</p>

  <template v-else-if="cur">
    <!-- حدود الخطة والشهري -->
    <section class="card limits" aria-label="حدود استهلاك الخطة">
      <h2>حدود استهلاك الخطة{{ data.source.plan ? ` · ${data.source.plan}` : "" }}</h2>
      <div v-for="x in quotas" :key="x.key" class="lim">
        <div class="lim-head">
          <b>{{ x.title }}</b>
          <span class="muted">{{ resetLabel(x.q) }}</span>
          <b class="lim-val">{{ n(x.q.pct) }}%</b>
        </div>
        <span class="track"><i :class="{ fable: x.key === 'fable' }" :style="{ inlineSize: `${Math.min(100, x.q.pct)}%` }" /></span>
        <small class="muted">
          آخر لقطة {{ ago(x.q.at) }} من {{ x.q.source }}
        </small>
      </div>
      <p v-if="!quotas.length" class="muted">لا لقطات حصة في «ميزان» بعد.</p>

      <div class="lim">
        <div class="lim-head">
          <b>الشهري · آخر 30 يومًا</b>
          <span class="muted">{{ fmtShort(data.panel.month.since) }} ← اليوم · لا حدّ شهريًا للخطة</span>
          <b class="lim-val">{{ c(data.panel.month.all.tokens) }} <small class="muted">توكن</small></b>
        </div>
        <ul class="fams">
          <li v-for="f in data.panel.month.families" :key="f.family">
            <span class="lbl">{{ f.family }}</span>
            <span class="track"><i :class="{ fable: f.family === 'Fable' }" :style="{ inlineSize: width(f.tokens, data.panel.month.all.tokens) }" /></span>
            <span class="val">{{ c(f.tokens) }} <small class="muted">{{ pct(f.tokens, data.panel.month.all.tokens) }}</small></span>
          </li>
        </ul>
        <small class="muted">
          {{ n(data.panel.month.all.turns) }} رسالة · المعدل {{ c(data.panel.month.all.tokens / 30) }}/يوم ·
          هذا الأسبوع ({{ fmtShort(data.panel.week.since) }} ←): {{ c(data.panel.week.all.tokens) }} توكن، منها Fable {{ c(data.panel.week.fable.tokens) }}
        </small>
      </div>
      <small class="muted">
        المصدر: «ميزان» ({{ data.source.url }}) · {{ n(data.source.snapshots) }} لقطة حصة · التوكنز من {{ data.source.first_day }} إلى {{ data.source.last_day }}.
        النسب كما في آخر لقطة؛ معدل الحرق والمتوقَّع عند التصفير في «ميزان» نفسه.
      </small>
    </section>

    <!-- المرشّحات -->
    <section class="filters" aria-label="المرشّحات">
      <div class="row">
        <div class="seg" role="group" aria-label="النطاق">
          <button v-for="r in RANGES" :key="r.key" :class="{ on: !from && range === r.key }" @click="setRange(r.key)">{{ r.label }}</button>
        </div>
        <label class="date">من <input v-model="from" type="date" :max="data.today"></label>
        <label class="date">إلى <input v-model="to" type="date" :max="data.today"></label>
      </div>
      <div class="row chips" role="group" aria-label="النماذج">
        <button v-for="m in data.all_models" :key="m.model" class="chip" :class="{ on: picked.includes(m.model), fable: m.family === 'Fable' }"
                :aria-pressed="picked.includes(m.model)" @click="toggle(m.model)">
          {{ m.model }}
        </button>
        <button class="btn ghost sm" @click="reset">إعادة الضبط</button>
      </div>
      <small class="muted">
        {{ fmtShort(data.filter.since) }} ← {{ fmtShort(data.filter.until) }} ({{ n(data.filter.days) }} يومًا) ·
        {{ data.filter.models.length ? data.filter.models.join("، ") : "كل النماذج" }} ·
        {{ c(cur.tokens) }} توكن · {{ n(cur.turns) }} رسالة
      </small>
    </section>

    <!-- كل يوم -->
    <section class="card">
      <header class="c-head">
        <div>
          <h2>التوكنز كل يوم</h2>
          <small class="muted">إدخال وكتابة ذاكرة وقراءة ذاكرة ومخرجات، لنطاق المرشّحات. مرّر على عمود لتفاصيله.</small>
        </div>
        <button class="btn ghost sm" :aria-pressed="table" @click="table = !table">{{ table ? "الرسم" : "عرض الجدول" }}</button>
      </header>
      <div v-if="!table" class="daily" role="img" :aria-label="`التوكنز كل يوم، أعلى يوم ${c(dailyMax)}`">
        <div class="plot">
          <div v-for="t in ticks" :key="t" class="grid" :style="{ insetBlockEnd: `${(t / dailyMax) * 100}%` }">
            <span>{{ c(t) }}</span>
          </div>
          <div class="bars">
            <div v-for="(d, i) in daily" :key="d.day" class="col" tabindex="0" :aria-label="`${fmtShort(d.day)}: ${n(d.tokens)}`"
                 @mouseenter="hover = i" @mouseleave="hover = null" @focus="hover = i" @blur="hover = null">
              <i :class="{ zero: !d.tokens }" :style="{ blockSize: `${(d.tokens / dailyMax) * 100}%` }" />
            </div>
          </div>
          <div v-if="hovered" class="tip" role="status">
            <b>{{ fmtShort(hovered.day) }}</b>
            <span>{{ n(hovered.tokens) }} توكن</span>
            <span class="muted">{{ n(hovered.turns) }} رسالة</span>
          </div>
        </div>
        <div class="axis">
          <span>{{ fmtShort(daily[0]?.day) }}</span><span>{{ fmtShort(mid) }}</span><span>{{ fmtShort(daily[daily.length - 1]?.day) }}</span>
        </div>
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>اليوم</th><th>توكنز</th><th>رسائل</th></tr></thead>
          <tbody>
            <tr v-for="d in [...daily].reverse().filter((x) => x.turns)" :key="d.day">
              <td>{{ fmtShort(d.day) }}</td><td class="num">{{ n(d.tokens) }}</td><td class="num">{{ n(d.turns) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- توكنز كل شهر -->
    <section class="card">
      <header class="c-head">
        <div>
          <h2>توكنز كل شهر</h2>
          <small class="muted">
            مجموع التوكنز لكل شهر ميلادي بمرشّح النماذج. المعدل «/يوم» يقسم على أيام الشهر داخل مدى البيانات: الشهر الأول
            يبدأ من أول يوم فيها والجاري ينتهي اليوم (جزئي). لا حدّ شهريًا للخطة؛ الأشرطة تقارن الأشهر ببعضها.
          </small>
        </div>
        <button class="btn ghost sm" :aria-pressed="monthTable" @click="monthTable = !monthTable">{{ monthTable ? "الرسم" : "عرض الجدول" }}</button>
      </header>
      <ul v-if="!monthTable" class="months">
        <li v-for="m in months" :key="m.month" :title="`${n(m.tokens)} توكن · ${n(m.turns)} رسالة`">
          <span class="lbl" dir="ltr">{{ m.month }} <small v-if="m.partial" class="muted">(جزئي)</small></span>
          <span class="track"><i :style="{ inlineSize: width(m.tokens, monthMax) }" /></span>
          <span class="val">{{ c(m.tokens) }} · {{ c(m.per_day) }}/يوم</span>
        </li>
      </ul>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>الشهر</th><th>الأيام</th><th>توكنز</th><th>/يوم</th><th>رسائل</th></tr></thead>
          <tbody>
            <tr v-for="m in [...months].reverse()" :key="m.month">
              <td dir="ltr">{{ m.month }}</td><td class="num">{{ m.days }}{{ m.partial ? " (جزئي)" : "" }}</td>
              <td class="num">{{ n(m.tokens) }}</td><td class="num">{{ n(m.per_day) }}</td><td class="num">{{ n(m.turns) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="two">
      <section class="card">
        <h2>النماذج</h2>
        <ul class="hbars">
          <li v-for="m in data.models" :key="m.model" :title="`${n(m.tokens)} توكن`">
            <span class="lbl">{{ m.model }}</span>
            <span class="track"><i :class="{ fable: m.family === 'Fable' }" :style="{ inlineSize: width(m.tokens, maxTok(data.models)) }" /></span>
            <span class="val">{{ c(m.tokens) }} <small class="muted">{{ pct(m.tokens, cur.tokens) }}</small></span>
            <small class="sub muted">{{ n(m.turns) }} رسالة · مخرجات {{ c(m.output) }}</small>
          </li>
        </ul>
      </section>
      <section class="card">
        <h2>أصل الطلب</h2>
        <small class="muted">من أرسل الطلب إلى النموذج: أنت، أو وكيل فرعي، أو مهمة مجدولة، أو جلسة أخرى...</small>
        <ul class="hbars">
          <li v-for="o in data.origins" :key="o.origin" :title="`${n(o.tokens)} توكن`">
            <span class="lbl">{{ o.label }}</span>
            <span class="track"><i :style="{ inlineSize: width(o.tokens, maxTok(data.origins)) }" /></span>
            <span class="val">{{ c(o.tokens) }} <small class="muted">{{ pct(o.tokens, cur.tokens) }}</small></span>
          </li>
        </ul>
      </section>
    </div>

    <section class="card">
      <h2>تفكيك التوكنز</h2>
      <div class="split" role="img" aria-label="أنواع التوكنز">
        <div v-for="part in [
          { k: 'قراءة ذاكرة (سياق محفوظ)', raw: cur.cache_read },
          { k: 'كتابة ذاكرة (سياق جديد)', raw: cur.cache_write },
          { k: 'إدخال', raw: cur.input },
          { k: 'مخرجات', raw: cur.output },
        ]" :key="part.k" class="part">
          <small class="muted">{{ part.k }}</small>
          <b>{{ c(part.raw) }}</b>
          <small>{{ pct(part.raw, cur.tokens) }} من التوكنز</small>
        </div>
      </div>
    </section>
  </template>
</template>

<style scoped>
.head-side { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
h2 { font-size: 17px; margin: 0 0 10px; }
.card { display: grid; gap: 8px; }
.c-head { display: flex; justify-content: space-between; align-items: start; gap: 10px; }
.c-head h2 { margin: 0; }
.track { block-size: 10px; background: var(--code-bg); border-radius: 4px; overflow: hidden; display: block; }
.track i { display: block; block-size: 100%; background: var(--slate); border-radius: 4px; min-inline-size: 2px; }
.track i.fable { background: var(--maroon); }

.limits { gap: 14px; }
.limits h2 { margin: 0; }
.lim { display: grid; gap: 6px; }
.lim-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; }
.lim-val { margin-inline-start: auto; font-size: 22px; font-variant-numeric: tabular-nums; }
.fams { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.fams li { display: grid; grid-template-columns: 64px 1fr auto; align-items: center; gap: 10px; font-size: 14px; }

.filters { display: grid; gap: 8px; border-block: 1px solid var(--line); padding-block: 12px; }
.filters .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.date { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; }
.date input { font: inherit; padding: 4px 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--fg); }
.chip { font: 13px/1.2 inherit; padding: 5px 10px; border-radius: 99px; border: 1px solid var(--line);
        background: var(--surface); color: var(--fg); cursor: pointer; }
.chip.on { background: var(--slate); border-color: var(--slate); color: var(--on-brand, #fff); }
.chip.fable.on { background: var(--maroon); border-color: var(--maroon); }

.daily { display: grid; gap: 6px; }
.plot { position: relative; block-size: 220px; margin-inline-end: 52px; }
.grid { position: absolute; inset-inline: 0; border-block-start: 1px dashed var(--line); }
.grid span { position: absolute; inset-inline-end: -52px; transform: translateY(-50%); font-size: 12px; color: var(--muted); }
.bars { position: absolute; inset: 0; display: flex; align-items: flex-end; gap: 2px; border-block-end: 1px solid var(--muted); }
.col { flex: 1; block-size: 100%; display: flex; align-items: flex-end; outline: none; }
.col i { display: block; inline-size: 100%; max-inline-size: 22px; margin-inline: auto; border-radius: 4px 4px 0 0;
         background: var(--slate); min-block-size: 2px; transition: background .15s; }
.col i.zero { background: var(--line); }
.col:hover i, .col:focus-visible i { background: var(--maroon); }
.tip { position: absolute; inset-block-start: 4px; inset-inline-start: 4px; display: grid; gap: 2px; font-size: 13px;
       background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; pointer-events: none;
       box-shadow: 0 2px 8px rgb(0 0 0 / .08); }
.axis { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-inline-end: 52px; }

.months { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.months li { display: grid; grid-template-columns: 140px 1fr minmax(150px, auto); align-items: center; gap: 12px; font-size: 14px; }
.months .track { block-size: 14px; }
.months .val, .hbars .val { font-variant-numeric: tabular-nums; white-space: nowrap; }

.two { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); }
.hbars { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.hbars li { display: grid; grid-template-columns: minmax(90px, 34%) 1fr auto; align-items: center; gap: 4px 10px; font-size: 14px; }
.hbars .track { block-size: 12px; }
.hbars .sub { grid-column: 1 / -1; font-size: 12px; }

.split { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 190px), 1fr)); }
.part { display: grid; gap: 2px; padding: 8px 12px; border: 1px solid var(--line); border-radius: 10px; }
.part b { font-size: 20px; font-variant-numeric: tabular-nums; }
.num { font-variant-numeric: tabular-nums; }
@media (max-width: 640px) { .months li { grid-template-columns: 1fr auto; } .months .track { grid-column: 1 / -1; grid-row: 2; } }
</style>
