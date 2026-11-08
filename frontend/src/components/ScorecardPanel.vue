<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { neo } from "@/api/neo";
import type { Criterion, Scorecard, ScorecardData } from "@/api/types";
import { fmtDay } from "@/utils/format";

const AREAS: Record<string, string> = { admin: "إداري", content: "محتوى", assess: "تقييم", students: "طلاب" };
const card = ref<Scorecard | null>(null);
const error = ref("");
const saving = ref(false);

async function load() {
  try {
    error.value = "";
    card.value = await neo.scorecard();
  } catch (e) {
    error.value = (e as Error).message;
  }
}

async function save() {
  saving.value = true;
  try {
    await neo.snapshot();
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    saving.value = false;
  }
}

const cur = computed(() => card.value?.current);
const savedToday = computed(() => card.value?.series.some((s) => s.day === cur.value?.day) ?? false);

function tone(c: Criterion): [string, string] {
  if (!c.measured || c.value === null) return ["prep", "غير مقاس"];
  const r = c.value / c.target;
  return r >= 1 ? ["ok", "محقق"] : r >= 0.6 ? ["warn", "قريب"] : ["bad", "فجوة"];
}

/** الفرق عن خط الأساس؛ المعايير كلها «الأعلى أفضل»، فالسالب تراجع */
function delta(c: Criterion): number | null {
  const base = card.value?.baseline?.criteria.find((b) => b.key === c.key)?.value;
  if (base == null || c.value == null || base === c.value) return null;
  return Math.round((c.value - base) * 10) / 10;
}
// علامة LRM أولًا، وإلا ظهرت الإشارة يمين الرقم في السطر العربي («25.3+»)
const signed = (d: number) => `\u200e${d > 0 ? "+" : ""}${d}`;

type Cap = ScorecardData["capabilities"][number];
const capTone = (c: Cap) => (c.automated ? "info" : c.used ? "ok" : c.enabled ? "warn" : "prep");
const capLabel = (c: Cap) => (c.automated ? "مؤتمتة" : c.used ? "مستعملة" : c.enabled ? "مفعّلة بلا استعمال" : "معطّلة");

const fmt = (v: number | null, unit: string) => (v === null ? "—" : unit === "%" ? `${v}%` : `${v} ${unit}`);
const fill = (c: Criterion) => (c.value === null ? 0 : Math.min(100, (100 * c.value) / c.target));

onMounted(load);
</script>

<template>
  <header id="scorecard" class="page-head">
    <div>
      <h2>بطاقة الأداء</h2>
      <p>
        المعايير الثمانية بقيمها الحالية ومستهدفاتها.
        <template v-if="card?.baseline">خط الأساس: {{ fmtDay(card.baseline.day) }}.</template>
        <template v-else>لم يُحفظ خط أساس بعد.</template>
      </p>
    </div>
    <button class="btn sm" :disabled="saving || !cur" @click="save">
      {{ savedToday ? "تحديث لقطة اليوم" : card?.baseline ? "حفظ لقطة اليوم" : "حفظ خط الأساس" }}
    </button>
  </header>

  <div v-if="error" class="error-box">تعذّر تحميل بطاقة الأداء: {{ error }}</div>
  <p v-else-if="!cur" class="empty"><i class="spinner" /> تحميل...</p>

  <template v-if="cur">
    <section class="grid">
      <article v-for="c in cur.criteria" :key="c.key" class="card crit">
        <div class="row">
          <h3>{{ c.title }}</h3>
          <span class="pill" :class="tone(c)[0]">{{ tone(c)[1] }}</span>
        </div>
        <div class="row nums">
          <b>{{ fmt(c.value, c.unit) }}</b>
          <small>المستهدف {{ fmt(c.target, c.unit) }}</small>
        </div>
        <div class="bar" role="meter" :aria-valuenow="c.value ?? 0" :aria-valuemax="c.target" :aria-label="c.title">
          <i :style="{ inlineSize: `${fill(c)}%` }" :class="tone(c)[0]" />
        </div>
        <small v-if="c.level !== null" class="muted">
          النضج {{ c.level }} من 4 · المستهدف {{ c.target_level }}
        </small>
        <p class="detail">{{ c.detail }}</p>
        <small v-if="delta(c) !== null" class="delta" :class="{ down: delta(c)! < 0 }">
          {{ signed(delta(c)!) }} عن خط الأساس
        </small>
        <p v-if="c.next" class="next">الخطوة التالية: {{ c.next }}</p>
      </article>
    </section>

    <section class="card">
      <h2>المهام المتكررة ونضج أتمتتها</h2>
      <p class="muted">
        المستويات: <span v-for="(name, n) in cur.levels" :key="n" class="lvl">{{ n }} {{ name }}</span>
      </p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>المهمة</th><th>المجال</th><th>النضج الآن ← المستهدف</th><th>دقائق/أسبوع يدويًا</th></tr></thead>
          <tbody>
            <tr v-for="t in cur.tasks" :key="t.key">
              <td>{{ t.title }}</td>
              <td>{{ AREAS[t.area] }}</td>
              <td>
                <span class="steps" role="img" :aria-label="`${t.level} من 4، والمستهدف ${t.target}`">
                  <i v-for="n in 4" :key="n" :class="{ on: n <= t.level, goal: n > t.level && n <= t.target }" />
                </span>
                {{ t.level }} ← {{ t.target }}
              </td>
              <td>{{ t.minutes }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <small class="muted">الدقائق تقدير أولي؛ قِس وقتك الفعلي أسبوعًا لتصحيحها.</small>
    </section>

    <section class="cards">
      <article class="card">
        <h2>قدرات المنصة</h2>
        <p class="muted">التبويبات كما في إعدادات الصف، ثم القدرات داخلها. الاستعمال بإفادتك.</p>
        <ul class="chips">
          <li v-for="c in cur.capabilities" :key="c.title" class="pill" :class="capTone(c)">
            {{ capLabel(c) }} · {{ c.title }}
          </li>
        </ul>
      </article>
      <article class="card">
        <h2>شروط الامتثال</h2>
        <ul class="gates">
          <li v-for="g in cur.compliance" :key="g.title">
            <span class="pill" :class="g.ok ? 'ok' : 'bad'">{{ g.ok ? "محقق" : "غير محقق" }}</span> {{ g.title }}
          </li>
        </ul>
      </article>
    </section>
  </template>
</template>

<style scoped>
.grid { display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr)); }
.crit h3 { margin: 0; font-size: var(--fs-body); }
.row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.nums b { font-size: var(--fs-3xl); }
.nums small, .detail, .muted { color: var(--muted); }
.detail { margin: 0; font-size: var(--fs-sm); }
.next { margin: 0; font-size: var(--fs-sm); color: var(--maroon); }
.delta { color: var(--ok); }
.delta.down { color: var(--bad); }
.bar { block-size: 8px; border-radius: 999px; background: var(--code-bg); overflow: hidden; }
.bar i { display: block; block-size: 100%; border-radius: inherit; background: var(--muted); }
.bar i.ok { background: var(--ok); }
.bar i.warn { background: var(--warn); }
.bar i.bad { background: var(--bad); }
.lvl { display: inline-block; margin-inline-end: 12px; white-space: nowrap; } /* inline-block: يسمح بالالتفاف بين العناصر المتلاصقة */
.steps { display: inline-flex; gap: 3px; vertical-align: middle; margin-inline-end: 6px; }
.steps i { inline-size: 14px; block-size: 8px; border-radius: 2px; background: var(--code-bg); }
.steps i.on { background: var(--maroon); }
.steps i.goal { background: var(--maroon-soft); outline: 1px dashed var(--maroon); }
.chips, .gates { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.gates { display: grid; gap: 8px; }
</style>
