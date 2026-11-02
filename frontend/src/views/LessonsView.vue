<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { neo } from "@/api/neo";
import type { Lesson } from "@/api/types";
import { todayIso } from "@/domain";
import { useClassesStore } from "@/stores/classes";
import { fmtDay } from "@/utils/format";

const route = useRoute();
const router = useRouter();
const classes = useClassesStore();

const lms = computed(() => Number(route.query.class) || classes.items[0]?.lms_id);
const lessons = ref<Lesson[]>([]);
const loading = ref(false);
const error = ref("");
const search = ref("");
type Filter = "all" | "hidden" | "undated" | "nopoints" | "unmatched";
const filter = ref<Filter>("all");
const FILTERS: [Filter, string, (l: Lesson) => boolean][] = [
  ["all", "الكل", () => true],
  ["hidden", "مخفية", (l) => l.hidden],
  ["undated", "بلا تاريخ", (l) => !l.date],
  ["nopoints", "بلا نقاط", (l) => !l.awards_points],
  ["unmatched", "بلا مطابقة", (l) => !l.effective_code || l.effective_code === "-"],
];

watch(lms, async (id) => {
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
}, { immediate: true });

const count = (f: Filter) => lessons.value.filter(FILTERS.find(([k]) => k === f)![2]).length;
const shown = computed(() => {
  const test = FILTERS.find(([k]) => k === filter.value)![2];
  const q = search.value.trim();
  return lessons.value.filter((l) => test(l) && (!q || l.title.includes(q) || String(l.position) === q));
});
const today = todayIso();
</script>

<template>
  <header class="page-head">
    <div>
      <h1>الدروس</h1>
      <p>كما على المنصة بعد آخر جلب، مع مطابقتها بالخطة الفصلية.</p>
    </div>
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

  <div v-if="error" class="error-box">{{ error }}</div>
  <p v-else-if="loading && !lessons.length" class="empty"><i class="spinner" /> تحميل...</p>

  <div v-else class="table-wrap">
    <table>
      <thead>
        <tr><th class="tight">#</th><th>العنوان</th><th>التاريخ</th><th class="tight">الحصة</th><th>درس الخطة</th><th>للطالب</th><th>نقاط</th></tr>
      </thead>
      <tbody>
        <tr v-for="l in shown" :key="l.lms_lesson_id" :class="{ today: l.date === today }">
          <td class="tight mono">{{ l.position }}</td>
          <td>{{ l.title }}</td>
          <td :class="{ muted: !l.date }">{{ fmtDay(l.date) }}</td>
          <td class="tight">{{ l.period ?? "-" }}</td>
          <td>
            <span v-if="l.override_code" class="pill info" title="مطابقة يدوية">{{ l.override_code }}</span>
            <span v-else-if="l.match_code" class="mono">{{ l.match_code }}</span>
            <span v-else class="pill warn">لا مطابقة</span>
          </td>
          <td><span class="pill" :class="l.hidden ? 'bad' : 'ok'">{{ l.hidden ? "مخفي" : "ظاهر" }}</span></td>
          <td><span v-if="l.awards_points" class="pill ok">نعم</span><span v-else class="pill warn">لا</span></td>
        </tr>
        <tr v-if="!shown.length"><td colspan="7" class="muted">لا دروس تطابق التصفية.</td></tr>
      </tbody>
    </table>
  </div>
</template>
