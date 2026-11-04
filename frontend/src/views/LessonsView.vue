<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { neo } from "@/api/neo";
import type { Lesson } from "@/api/types";
import { todayIso } from "@/domain";
import { useConfirm } from "@/composables/useConfirm";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";
import { fmtDay, fmtWhen } from "@/utils/format";

const route = useRoute();
const router = useRouter();
const classes = useClassesStore();
const jobs = useJobsStore();
const confirm = useConfirm();

const lms = computed(() => Number(route.query.class) || classes.items[0]?.lms_id);
const lessons = ref<Lesson[]>([]);
const loading = ref(false);
const error = ref("");
const search = ref("");
type Filter = "all" | "incomplete" | "hidden" | "undated" | "nopoints" | "unmatched" | "unconfirmed";
const filter = ref<Filter>("all");
const FILTERS: [Filter, string, (l: Lesson) => boolean][] = [
  ["all", "الكل", () => true],
  ["incomplete", "ناقصة الجودة", (l) => !!l.audit?.issues.length],
  ["hidden", "مخفية", (l) => l.hidden],
  ["undated", "بلا تاريخ", (l) => !l.date],
  ["nopoints", "بلا نقاط", (l) => !l.awards_points],
  ["unmatched", "بلا مطابقة", (l) => !l.effective_code || l.effective_code === "-"],
  ["unconfirmed", "مطابقة غير مؤكدة", (l) => unconfirmed(l)],
];
/** مطابقة آلية دون 100% لم يؤكدها المعلم: الدرس مستبعد من الاقتراح والكتابة حتى يؤكدها مرة واحدة */
function unconfirmed(l: Lesson) {
  return !!l.match_code && !l.override_code && !l.match_sure;
}

async function load(id = lms.value) {
  if (!id) return;
  loading.value = true;
  try {
    lessons.value = await neo.lessons(id);
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
watch(lms, (id) => load(id), { immediate: true });
// انتهاء التدقيق يحدّث الجدول
jobs.onFinished((j) => { if (j.kind === "audit") void load(); });

async function audit() {
  try {
    await jobs.enqueue("audit", { classes: [lms.value] });
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const audited = computed(() => lessons.value.filter((l) => l.audit).length);
const lastAudit = computed(() => lessons.value.map((l) => l.audit?.audited_at ?? "").sort().at(-1) || null);

const count = (f: Filter) => lessons.value.filter(FILTERS.find(([k]) => k === f)![2]).length;
const shown = computed(() => {
  const test = FILTERS.find(([k]) => k === filter.value)![2];
  const q = search.value.trim();
  return lessons.value.filter((l) => test(l) && (!q || l.title.includes(q) || String(l.position) === q));
});
const today = todayIso();

const pendingConfirm = computed(() => shown.value.filter(unconfirmed));
async function confirmMatch(list: Lesson[]) {
  if (!list.length) return;
  const ok = await confirm({
    title: list.length === 1 ? `تأكيد مطابقة الدرس ${list[0].position}` : `تأكيد مطابقة ${list.length} درسًا`,
    body: list.length === 1
      ? `«${list[0].title}» ← درس الخطة ${list[0].match_code} (${Math.round((list[0].match_score ?? 0) * 100)}%). `
        + "بعد التأكيد يدخل الاقتراح والكتابة ما بقيت مطابقته الآلية نفسها."
      : "كل درس معروض بمطابقته الآلية الحالية. بعد التأكيد تدخل الاقتراح والكتابة ما بقيت مطابقتها نفسها.",
    confirm: "أكّد المطابقة",
  });
  if (!ok) return;
  try {
    await neo.confirmLessons(list.map((l) => l.lms_lesson_id));
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  }
}

const shrink = computed(() => classes.byId.get(lms.value ?? 0)?.shrink_pending ?? {});
async function acceptShrink() {
  const s = shrink.value;
  const ok = await confirm({
    title: "تأكيد حذف دروس من المنصة",
    body: `المحفوظ ${s.saved} درسًا وعلى المنصة ${s.platform}. الغائبة: ${(s.missing ?? []).join("، ")}. `
      + "إن كان الحذف مقصودًا فأكّده؛ يُقبل النقص في الجلب القادم مرة واحدة، وتُحذف الدروس الغائبة واقتراحاتها محليًا.",
    confirm: "الحذف مقصود",
    danger: true,
  });
  if (!ok || !lms.value) return;
  try {
    await neo.acceptShrink(lms.value);
    await classes.load();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
</script>

<template>
  <header class="page-head">
    <div>
      <h1>الدروس</h1>
      <p>
        كما على المنصة بعد آخر جلب، مع مطابقتها بالخطة الفصلية.
        <template v-if="audited">الجودة مدقَّقة في {{ audited }} درسًا · {{ fmtWhen(lastAudit) }}.</template>
        <template v-else-if="lessons.length">لم تُدقَّق جودة الدروس بعد.</template>
      </p>
    </div>
    <button class="btn sm" :disabled="!lms || jobs.busy('audit', lms)" @click="audit">
      <i v-if="jobs.busy('audit', lms)" class="spinner" /> تدقيق الجودة
    </button>
  </header>

  <div class="controls">
    <nav class="seg" aria-label="الصف">
      <button v-for="c in classes.items" :key="c.lms_id" :class="{ on: c.lms_id === lms }"
              @click="router.replace({ query: { class: c.lms_id } })">{{ c.name }}</button>
    </nav>
    <div class="seg" role="group" aria-label="تصفية">
      <button v-for="[k, label] in FILTERS" :key="k" :class="{ on: filter === k }" @click="filter = k">
        {{ label }} <span class="muted">{{ count(k) }}</span>
      </button>
    </div>
    <input v-model="search" type="search" placeholder="بحث بالعنوان أو الرقم" aria-label="بحث">
  </div>

  <div v-if="shrink.saved" class="error-box shrink">
    <span>
      أوقفت المزامنة: نقص عدد الدروس على المنصة (المحفوظ {{ shrink.saved }}، المنصة {{ shrink.platform }}) ولم يُحفظ شيء.
      <template v-if="shrink.missing?.length">الغائبة: {{ shrink.missing.join("، ") }}.</template>
    </span>
    <button v-if="!classes.byId.get(lms ?? 0)?.allow_shrink" class="btn sm" @click="acceptShrink">الحذف مقصود</button>
    <span v-else class="pill info">أُكّد؛ يُقبل في الجلب القادم</span>
  </div>
  <div v-if="filter === 'unconfirmed' && pendingConfirm.length" class="confirm-bar">
    <span class="muted">هذه الدروس مستبعدة من الاقتراح والكتابة حتى تؤكد مطابقتها مرة واحدة.</span>
    <button class="btn sm" @click="confirmMatch(pendingConfirm)">أكّد مطابقة المعروض ({{ pendingConfirm.length }})</button>
  </div>
  <div v-if="error" class="error-box">{{ error }}</div>
  <p v-else-if="loading && !lessons.length" class="empty"><i class="spinner" /> تحميل...</p>

  <div v-else class="table-wrap">
    <table>
      <thead>
        <tr><th class="tight">#</th><th>العنوان</th><th>التاريخ</th><th class="tight">الحصة</th><th>درس الخطة</th><th>للطالب</th><th>نقاط</th><th>الجودة</th></tr>
      </thead>
      <tbody>
        <tr v-for="l in shown" :key="l.lms_lesson_id" :class="{ today: l.date === today }">
          <td class="tight mono">{{ l.position }}</td>
          <td>{{ l.title }}</td>
          <td :class="{ muted: !l.date }">{{ fmtDay(l.date) }}</td>
          <td class="tight">{{ l.period ?? "-" }}</td>
          <td>
            <span v-if="l.override_code" class="pill info" title="مطابقة يدوية">{{ l.override_code }}</span>
            <template v-else-if="unconfirmed(l)">
              <span class="mono">{{ l.match_code }}</span>
              <span class="pill warn" title="مطابقة آلية غير مؤكدة: الدرس مستبعد من الاقتراح والكتابة">
                {{ Math.round((l.match_score ?? 0) * 100) }}%
              </span>
              <button class="btn sm" @click="confirmMatch([l])">أكّد</button>
            </template>
            <span v-else-if="l.match_code" class="mono">{{ l.match_code }}</span>
            <span v-else class="pill warn">لا مطابقة</span>
          </td>
          <td><span class="pill" :class="l.hidden ? 'bad' : 'ok'">{{ l.hidden ? "مخفي" : "ظاهر" }}</span></td>
          <td><span v-if="l.awards_points" class="pill ok">نعم</span><span v-else class="pill warn">لا</span></td>
          <td>
            <!-- flex على عنصر داخل الخلية لا على الخلية نفسها، وإلا انكسرت حدود الصف -->
            <div class="quality">
              <template v-if="l.audit">
                <span v-if="!l.audit.issues.length" class="pill ok" :title="l.audit.sections.join('، ')">مستوفٍ</span>
                <span v-for="x in l.audit.issue_labels" v-else :key="x" class="pill warn"
                      :title="l.audit.sections.length ? `الأقسام: ${l.audit.sections.join('، ')}` : 'بلا أقسام'">{{ x }}</span>
              </template>
              <span v-else class="muted">-</span>
            </div>
          </td>
        </tr>
        <tr v-if="!shown.length"><td colspan="8" class="muted">لا دروس تطابق التصفية.</td></tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.quality { display: flex; flex-wrap: wrap; gap: 4px; }
.shrink, .confirm-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; }
.confirm-bar { margin-block: 8px; }
</style>
