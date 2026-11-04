<script setup lang="ts">
import { ref } from "vue";

import type { JobKind, PlatformClass } from "@/api/types";
import PrepPackCard from "@/components/PrepPackCard.vue";
import WeeklyCard from "@/components/WeeklyCard.vue";
import { STAGES, todayIso } from "@/domain";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";
import { fmtDay, fmtWhen } from "@/utils/format";

const classes = useClassesStore();
const jobs = useJobsStore();
const actionError = ref("");

async function run(kind: JobKind, k: PlatformClass) {
  try {
    actionError.value = "";
    await jobs.enqueue(kind, { classes: [k.lms_id] });
  } catch (e) {
    actionError.value = (e as Error).message;
  }
}

const seen = (k: PlatformClass) => k.overview.last_verify?.summary.seen_by_student as number | undefined;
const missing = (k: PlatformClass) => (k.overview.last_verify?.summary.missing_past as number[] | undefined) ?? [];
</script>

<template>
  <header class="page-head">
    <div>
      <h1>اليوم</h1>
      <p>{{ fmtDay(todayIso()) }}</p>
    </div>
  </header>

  <div v-if="actionError" class="error-box">{{ actionError }}</div>
  <div v-if="classes.error" class="error-box">تعذّر تحميل الصفوف: {{ classes.error }}</div>
  <p v-else-if="classes.loading && !classes.items.length" class="empty"><i class="spinner" /> تحميل...</p>
  <p v-else-if="!classes.items.length" class="empty">لا توجد صفوف مفعّلة. أضف صفًا من لوحة الإدارة.</p>

  <WeeklyCard />

  <section v-if="classes.items.length" class="card prep-card" aria-label="حزمة التحضير الأسبوعية">
    <header>
      <h2>حزمة التحضير الأسبوعية</h2>
      <small class="muted">
        مجلد للأسبوع على سطح المكتب: التحضير والعرض وورقة العمل وعروض الأقسام لكل درس، والتحضيرات معدّلة
        (العام واسم المعلم واليوم والتاريخ والحصة)، وصف الرسالة الأسبوعية. دروس الأسبوع من الخطة، والقراءة فقط من المنصة.
      </small>
    </header>
    <PrepPackCard v-for="k in classes.items" :key="k.lms_id" :klass="k" />
  </section>

  <section class="cards">
    <article v-for="k in classes.items" :key="k.lms_id" class="card klass">
      <header class="k-head">
        <div>
          <h2>{{ k.name }}</h2>
          <small class="muted">{{ k.plan_title }} · آخر جلب {{ fmtWhen(k.last_fetched_at) }}</small>
        </div>
        <span class="mono muted">#{{ k.lms_id }}</span>
      </header>

      <div class="today">
        <h3>درس اليوم</h3>
        <ul v-if="k.overview.today.length" class="lessons">
          <li v-for="l in k.overview.today" :key="l.id">
            <b>{{ l.position }}. {{ l.title }}</b> <span class="muted">· الحصة {{ l.period ?? "-" }}</span>
          </li>
        </ul>
        <p v-else class="muted">لا درس مؤرخ اليوم.</p>
        <h3>القادم</h3>
        <ul class="lessons">
          <li v-for="l in k.overview.upcoming" :key="l.id">
            <span>{{ l.position }}. {{ l.title }}</span> <span class="muted">· {{ fmtDay(l.date) }}</span>
          </li>
          <li v-if="!k.overview.upcoming.length" class="muted">لا دروس مؤرخة بعد اليوم.</li>
        </ul>
      </div>

      <dl class="stats">
        <div><dt>مؤرخة</dt><dd>{{ k.overview.lessons.dated }} / {{ k.overview.lessons.total }}</dd></div>
        <div><dt>مخفية</dt><dd :class="{ warn: k.overview.lessons.hidden }">{{ k.overview.lessons.hidden }}</dd></div>
        <div><dt>تمنح نقاطًا</dt><dd>{{ k.overview.lessons.points }} / {{ k.overview.lessons.total }}</dd></div>
      </dl>

      <div class="verify">
        <template v-if="k.overview.last_verify">
          <span class="pill" :class="k.overview.last_verify.ok ? 'ok' : 'bad'">
            {{ k.overview.last_verify.ok ? "الطالب يرى ما يجب" : "دروس ماضية لا يراها الطالب" }}
          </span>
          <span class="muted">
            يرى {{ seen(k) ?? "-" }} درسًا · {{ fmtWhen(k.overview.last_verify.at) }}
            <template v-if="missing(k).length"> · مفقود: {{ missing(k).join("، ") }}</template>
          </span>
        </template>
        <span v-else class="muted">لم يُجرَ تحقق بعد.</span>
        <button class="btn sm" :disabled="jobs.busy('verify', k.lms_id)" @click="run('verify', k)">
          <i v-if="jobs.busy('verify', k.lms_id)" class="spinner" /> تحقق الآن
        </button>
      </div>

      <div class="table-wrap">
        <table>
          <thead><tr><th>المرحلة</th><th>للمراجعة</th><th>معتمد</th><th class="tight" /></tr></thead>
          <tbody>
            <tr v-for="s in STAGES" :key="s.kind">
              <td>
                <RouterLink :to="{ name: 'review', params: { kind: s.kind }, query: { class: k.lms_id } }">
                  {{ s.label }}
                </RouterLink>
              </td>
              <td><span v-if="k.overview.review[s.kind].pending" class="pill warn">{{ k.overview.review[s.kind].pending }}</span><span v-else class="muted">0</span></td>
              <td><span v-if="k.overview.review[s.kind].approved" class="pill info">{{ k.overview.review[s.kind].approved }}</span><span v-else class="muted">0</span></td>
              <td class="tight">
                <button class="btn sm" :disabled="jobs.busy(s.plan, k.lms_id)" @click="run(s.plan, k)">
                  <i v-if="jobs.busy(s.plan, k.lms_id)" class="spinner" /> جلب واقتراح
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>
  </section>
</template>

<style scoped>
.prep-card { gap: 18px; }
.prep-card h2 { font-size: 20px; margin: 0; }
.klass { gap: 16px; }
.k-head { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
.k-head h2 { font-size: 22px; }
.today h3 { font-size: 14px; color: var(--muted); margin-block: 6px 2px; }
.lessons { list-style: none; padding: 0; gap: 2px; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 0; }
.stats div { background: var(--bg); border-radius: 10px; padding: 8px 12px; }
.stats dt { font-size: 12.5px; color: var(--muted); }
.stats dd { margin: 0; font: 700 20px var(--f-display); }
.stats dd.warn { color: var(--warn); }
.verify { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; font-size: 14px; }
.verify .btn { margin-inline-start: auto; }
</style>
