<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import { neo } from "@/api/neo";
import type { Job, Usage, UsageFilter, UsageVerify } from "@/api/types";
import { useJobsStore } from "@/stores/jobs";
import { ago, fmtShort, fmtWhen } from "@/utils/format";

/**
 * استهلاك Claude: لوحة الحدود (الأسبوعي لكل النماذج ولـ Fable، والشهري)، ثم مرشّحات النطاق والنماذج يتبعها
 * الرسم اليومي والنماذج وأين ذهب وتفكيك الرموز، وتوكنز كل شهر، والتحقق المستقل.
 * المصدر قاعدة البيانات بعد استيراد سجلات مجلد Claude تزايديًا (neo/services/usage.py). قراءة فقط.
 */
const data = ref<Usage | null>(null);
const error = ref("");
const loading = ref(false);
const note = ref("");
const table = ref(false);
const monthTable = ref(false);

// المرشّحات
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

async function load(refresh = false) {
  loading.value = true;
  try {
    data.value = await neo.usage(filter.value, refresh);
    const im = data.value.imported;
    note.value = im ? `استُوردت ${n(im.new)} خطوة جديدة${im.pending ? "، وبقي ما يستورده العامل في الدقائق القادمة" : ""}.` : "";
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
watch(filter, () => load(), { deep: true });

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

/** claude-haiku-4-5-20251001 ← haiku 4.5، claude-sonnet-5 ← sonnet 5 */
function shortModel(m: string): string {
  const [name, ...ver] = m.replace(/^claude-/, "").replace(/-\d{8}$/, "").split("-");
  return ver.length ? `${name} ${ver.join(".")}` : name;
}
const maxOf = (rows: { effective: number }[]) => Math.max(1, ...rows.map((r) => r.effective));

// لوحة الحدود
const panel = computed(() => data.value?.panel);

// الرسم اليومي لنطاق المرشّح
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

// توكنز كل شهر
const months = computed(() => data.value?.monthly ?? []);
const monthMax = computed(() => Math.max(1, ...months.value.map((m) => m.tokens)));

const cur = computed(() => data.value?.totals);

// التحقق المستقل: العامل يعدّ ملفات السجل الأصلية بكود منفصل ويقارنها بقاعدة البيانات (مهمة usage_verify)
const jobs = useJobsStore();
const check = ref<Job | null>(null);
const report = computed(() => (check.value?.status === "done" ? (check.value.report as unknown as UsageVerify) : null));
async function loadCheck() {
  try {
    check.value = (await neo.jobs({ kind: "usage_verify", limit: 1 })).results[0] ?? null;
  } catch { /* يبقى القسم بلا تقرير */ }
}
async function runCheck() {
  try {
    await jobs.enqueue("usage_verify");
    await loadCheck();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const off = jobs.onFinished((j) => { if (j.kind === "usage_verify") { void loadCheck(); void load(); } });
onUnmounted(off);
const FIELD_LABEL: [keyof UsageVerify["windows"]["week"]["diff"], string][] = [
  ["turns", "الرسائل"], ["input", "إدخال جديد"], ["cache_read", "قراءة سياق"], ["cache_write", "حفظ سياق"], ["output", "مخرجات"],
];

onMounted(() => { void load(); void loadCheck(); });
</script>

<template>
  <header class="page-head">
    <div>
      <h1>الاستهلاك</h1>
      <p>توكنز Claude من سجلات الجلسات في مجلد Claude، محفوظة في قاعدة البيانات. أرقام فقط، بلا أي نص من المحادثات.</p>
    </div>
    <div class="head-side">
      <small class="muted">عمر البيانات: {{ data?.imported_at ? ago(data.imported_at) : "لم تُستورد بعد" }}</small>
      <button class="btn primary sm" :disabled="loading" @click="load(true)">
        <i v-if="loading" class="spinner" /> تحديث فوري
      </button>
    </div>
  </header>

  <div v-if="note" class="note-box">{{ note }}</div>
  <div v-if="error" class="error-box">{{ error }}</div>
  <p v-else-if="!data" class="empty"><i class="spinner" /> تحميل...</p>
  <p v-else-if="!data.first" class="empty">
    لا سجلات بعد (العامل يستورد كل 10 دقائق، أو اضغط «تحديث فوري»). المجلدات المقروءة:
    <span v-for="s in data.sources" :key="s.path" class="mono"> {{ s.path }} ({{ s.found ? "موجود" : "غير موجود" }})</span>
  </p>

  <template v-else-if="panel && cur">
    <!-- لوحة الحدود: الأسبوعي (كل النماذج وFable) والشهري -->
    <section class="card limits" aria-label="حدود الاستهلاك">
      <h2>حدود الاستهلاك</h2>
      <div class="lim">
        <div class="lim-head">
          <b>الأسبوعي · كل النماذج</b>
          <span class="muted">{{ fmtShort(panel.week.since) }} ← اليوم</span>
          <b class="lim-val">{{ c(panel.week.all.tokens) }} <small class="muted">توكن</small></b>
        </div>
        <span class="track"><i :style="{ inlineSize: pct(panel.week.all.tokens, panel.month.all.tokens).replace('٪', '%') }" /></span>
        <small class="muted">
          {{ n(panel.week.all.turns) }} رسالة · {{ n(panel.week.all.sessions) }} جلسة · المعدل {{ c(panel.week.all.tokens / 7) }}/يوم ·
          {{ pct(panel.week.all.tokens, panel.month.all.tokens) }} من آخر 30 يومًا
        </small>
      </div>
      <div class="lim">
        <div class="lim-head">
          <b>الأسبوعي · Fable</b>
          <span class="muted">{{ fmtShort(panel.week.since) }} ← اليوم</span>
          <b class="lim-val">{{ c(panel.week.fable.tokens) }} <small class="muted">توكن</small></b>
        </div>
        <span class="track"><i class="fable" :style="{ inlineSize: pct(panel.week.fable.tokens, panel.week.all.tokens).replace('٪', '%') }" /></span>
        <small class="muted">
          {{ n(panel.week.fable.turns) }} رسالة · المعدل {{ c(panel.week.fable.tokens / 7) }}/يوم ·
          {{ pct(panel.week.fable.tokens, panel.week.all.tokens) }} من توكنز الأسبوع
        </small>
      </div>
      <div class="lim">
        <div class="lim-head">
          <b>الشهري · آخر 30 يومًا</b>
          <span class="muted">{{ fmtShort(panel.month.since) }} ← اليوم</span>
          <b class="lim-val">{{ c(panel.month.all.tokens) }} <small class="muted">توكن</small></b>
        </div>
        <ul class="fams">
          <li v-for="f in panel.month.families" :key="f.family">
            <span class="lbl">{{ f.family }}</span>
            <span class="track"><i :class="{ fable: f.family === 'Fable' }" :style="{ inlineSize: pct(f.tokens, panel.month.all.tokens).replace('٪', '%') }" /></span>
            <span class="val">{{ c(f.tokens) }} <small class="muted">{{ pct(f.tokens, panel.month.all.tokens) }}</small></span>
          </li>
        </ul>
        <small class="muted">{{ n(panel.month.all.turns) }} رسالة · {{ n(panel.month.all.sessions) }} جلسة · المعدل {{ c(panel.month.all.tokens / 30) }}/يوم</small>
      </div>
      <small class="muted">
        النسبة المئوية من حدّ خطتك وموعد التصفير لا تحفظها سجلات Claude؛ تظهر هنا حين يُربط مصدر لقطات /usage (cli_usage).
        هذه الجلسة: {{ c(data.session_total.tokens) }} توكن.
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
                :aria-pressed="picked.includes(m.model)" dir="ltr" @click="toggle(m.model)">
          {{ shortModel(m.model) }}
        </button>
        <button class="btn ghost sm" @click="reset">إعادة الضبط</button>
      </div>
      <small class="muted">
        {{ fmtShort(data.filter.since) }} ← {{ fmtShort(data.filter.until) }} ({{ n(data.filter.days) }} يومًا) ·
        {{ data.filter.models.length ? data.filter.models.map(shortModel).join("، ") : "كل النماذج" }} ·
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
            <span class="muted">{{ n(hovered.turns) }} رسالة · {{ n(hovered.effective) }} وحدة فعلية</span>
          </div>
        </div>
        <div class="axis">
          <span>{{ fmtShort(daily[0]?.day) }}</span><span>{{ fmtShort(mid) }}</span><span>{{ fmtShort(daily[daily.length - 1]?.day) }}</span>
        </div>
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>اليوم</th><th>توكنز</th><th>رسائل</th><th>وحدة فعلية</th></tr></thead>
          <tbody>
            <tr v-for="d in [...daily].reverse().filter((x) => x.turns)" :key="d.day">
              <td>{{ fmtShort(d.day) }}</td><td class="num">{{ n(d.tokens) }}</td><td class="num">{{ n(d.turns) }}</td>
              <td class="num">{{ n(d.effective) }}</td>
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
          <span class="track"><i :style="{ inlineSize: `${(m.tokens / monthMax) * 100}%` }" /></span>
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
            <span class="lbl mono" dir="ltr">{{ shortModel(m.model) }}</span>
            <span class="track"><i :class="{ fable: /fable/.test(m.model) }" :style="{ inlineSize: `${(m.tokens / Math.max(1, ...data.models.map((x) => x.tokens))) * 100}%` }" /></span>
            <span class="val">{{ c(m.tokens) }} <small class="muted">{{ pct(m.tokens, cur.tokens) }}</small></span>
            <small class="sub muted">{{ n(m.turns) }} رسالة · مخرجات {{ c(m.output) }} · {{ c(m.effective) }} وحدة فعلية</small>
          </li>
        </ul>
      </section>
      <section class="card">
        <h2>أين ذهب الاستهلاك</h2>
        <small class="muted">بالوحدات الفعلية: قراءة سياق ×{{ data.weights.cache_read }}، وحفظ سياق ×{{ data.weights.cache_write }}، ومخرجات ×{{ data.weights.output }}.</small>
        <ul class="hbars">
          <li v-for="g in data.groups" :key="g.name" :title="`${n(g.effective)} وحدة فعلية`">
            <span class="lbl">{{ g.name }}</span>
            <span class="track"><i :style="{ inlineSize: `${(g.effective / maxOf(data.groups)) * 100}%` }" /></span>
            <span class="val">{{ c(g.effective) }} <small class="muted">{{ pct(g.effective, cur.effective) }}</small></span>
          </li>
        </ul>
      </section>
    </div>

    <section class="card">
      <h2>تفكيك التوكنز</h2>
      <div class="split" role="img" aria-label="التوكنز الخام مقابل وزنها الفعلي">
        <div v-for="part in [
          { k: 'قراءة ذاكرة (سياق محفوظ)', raw: cur.cache_read, w: data.weights.cache_read },
          { k: 'كتابة ذاكرة (سياق جديد)', raw: cur.cache_write, w: data.weights.cache_write },
          { k: 'إدخال', raw: cur.input, w: 1 },
          { k: 'مخرجات', raw: cur.output, w: data.weights.output },
        ]" :key="part.k" class="part">
          <small class="muted">{{ part.k }}</small>
          <b>{{ c(part.raw) }}</b>
          <small>{{ pct(part.raw, cur.tokens) }} من التوكنز · {{ pct(part.raw * part.w, cur.effective) }} من الوحدات الفعلية</small>
        </div>
      </div>
    </section>

    <!-- التحقق ومصدر الأرقام -->
    <section class="card verify" :class="report ? (report.ok ? 'good' : 'bad') : ''" aria-label="التحقق من الأرقام">
      <header class="c-head">
        <div>
          <h2>التحقق ومصدر الأرقام</h2>
          <small class="muted">
            المصدر: ملفات سجل الجلسات التي يكتبها Claude على هذا الجهاز (*.jsonl)، ومنها حقل usage لكل رد من النموذج.
            التحقق يعدّها من جديد بكود مستقل عن الاستيراد ويقارنها بقاعدة البيانات.
          </small>
        </div>
        <button class="btn sm" :disabled="jobs.busy('usage_verify')" @click="runCheck">
          <i v-if="jobs.busy('usage_verify')" class="spinner" /> تحقق من الأرقام الآن
        </button>
      </header>
      <p v-if="!check" class="muted">لم يُجرَ تحقق بعد.</p>
      <p v-else-if="check.status !== 'done'" class="muted">
        <template v-if="check.status === 'failed'">تعذّر التحقق: {{ check.error }}</template>
        <template v-else><i class="spinner" /> العامل يعدّ الملفات الآن (دقيقة أو اثنتان)...</template>
      </p>
      <template v-else-if="report">
        <p class="verdict">
          <span class="pill" :class="report.ok ? 'ok' : 'bad'">{{ report.ok ? "مطابقة تامة" : "يوجد فرق" }}</span>
          {{ fmtWhen(report.checked_at) }} ·
          {{ n(report.files) }} ملف · {{ n(report.lines) }} سطر استهلاك · {{ n(report.messages) }} رسالة فريدة ·
          {{ n(report.dup_lines) }} سطر مكرر لرسالة سبق عدّها
          <template v-if="report.dup_differ">
            · {{ n(report.dup_differ) }} رسالة تكررت بأرقام مختلفة (أولها مؤقت أثناء كتابة الرد)، فيُؤخذ أكبرها:
            أخذ أولها كان سيُنقص مخرجات 30 يومًا {{ n(report.windows.month.output_first_line_loss) }} رمز
          </template>
          <template v-else> · المكرر بالأرقام نفسها دائمًا</template>
        </p>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>الحقل</th>
                <template v-for="w in (['week', 'month'] as const)" :key="w">
                  <th>{{ w === "week" ? "7 أيام" : "30 يومًا" }}: الملفات</th><th>قاعدة البيانات</th><th>الفرق</th>
                </template>
              </tr>
            </thead>
            <tbody>
              <tr v-for="[k, label] in FIELD_LABEL" :key="k">
                <td>{{ label }}</td>
                <template v-for="w in (['week', 'month'] as const)" :key="w">
                  <td class="num">{{ n(report.windows[w].files[k]) }}</td>
                  <td class="num">{{ n(report.windows[w].db[k]) }}</td>
                  <td class="num" :class="{ err: report.windows[w].diff[k] }">{{ n(report.windows[w].diff[k]) }}</td>
                </template>
              </tr>
            </tbody>
          </table>
        </div>
        <small class="muted">
          لا يُعدّ: ردود «synthetic» ليست من نموذج ({{ n(report.synthetic) }})، وأسطر تالفة ({{ n(report.bad_json) }}).
          لا تشمل الملفات: جلسات Claude في المتصفح أو التطبيق أو السحابة ما لم تُصدَّر إلى backend/usage، ولا حدود اشتراكك
          (مصدرها صفحة الاستخدام في إعدادات claude.ai).
        </small>
      </template>
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
.chip { font: 13px/1.2 var(--f-mono, ui-monospace, monospace); padding: 5px 10px; border-radius: 99px; border: 1px solid var(--line);
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
.mono { font-family: var(--f-mono, ui-monospace, monospace); font-size: 13px; }
.verify.good { border-color: var(--ok); }
.verify.bad { border-color: var(--bad); }
.verdict { margin: 0; font-size: 14px; }
.err { color: var(--bad); }
@media (max-width: 640px) { .months li { grid-template-columns: 1fr auto; } .months .track { grid-column: 1 / -1; grid-row: 2; } }
</style>
