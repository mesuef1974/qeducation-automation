<script setup lang="ts">
import { computed, reactive, ref } from "vue";

import type { PlatformClass, PrepLesson, PrepRun } from "@/api/types";
import { useJobsStore } from "@/stores/jobs";
import { fmtShort, fmtStamp } from "@/utils/format";

/**
 * حزمة التحضير الأسبوعية لصف: مجلد الأسبوع على سطح المكتب (التحضير والعرض وورقة العمل وعروض الأقسام لكل درس،
 * والتحضيرات معدّلة) وصف الرسالة الأسبوعية جاهزًا للنسخ. قراءة فقط من المنصة.
 */
const props = defineProps<{ klass: PlatformClass }>();
const jobs = useJobsStore();
const error = ref("");
const copied = ref(false);
const pick = reactive<{ week: number | null }>({ week: null });

const prep = computed(() => props.klass.overview.prep);
const last = computed<PrepRun | null>(() => prep.value?.last ?? null);
const week = computed(() => pick.week ?? prep.value?.next_week ?? null);
const busy = computed(() => jobs.busy("prep_pack", props.klass.lms_id));

async function build() {
  if (week.value === null) return;
  try {
    error.value = "";
    await jobs.enqueue("prep_pack", { class: props.klass.lms_id, week: week.value });
  } catch (e) {
    error.value = (e as Error).message;
  }
}

const roleLabel: Record<string, string> = { prep: "تحضير", worksheet: "ورقة عمل", presentation: "عرض", section: "عرض قسم" };
const filesLine = (l: PrepLesson) => {
  const n: Record<string, number> = {};
  for (const f of l.files) n[f.role] = (n[f.role] ?? 0) + 1;
  return Object.entries(n).map(([r, c]) => (c > 1 ? `${roleLabel[r]} ×${c}` : roleLabel[r])).join("، ");
};
const notes = (l: PrepLesson) => l.files.filter((f) => f.note).map((f) => f.note as string);
const staleCount = computed(() => Object.keys(last.value?.stale_years ?? {}).length);

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
async function copyRow() {
  const m = last.value?.message;
  if (!m) return;
  const tsv = `${m.header.join("\t")}\n${m.row.join("\t")}`;
  const html = `<table dir="rtl" border="1"><tr>${m.header.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>` +
    `<tr>${m.row.map((c) => `<td>${esc(c)}</td>`).join("")}</tr></table>`;
  try {
    if ("ClipboardItem" in window) {
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }), "text/plain": new Blob([tsv], { type: "text/plain" }),
      })]);
    } else {
      await navigator.clipboard.writeText(tsv);
    }
    copied.value = true;
    window.setTimeout(() => (copied.value = false), 2000);
  } catch (e) {
    error.value = `تعذّر النسخ: ${(e as Error).message}`;
  }
}
</script>

<template>
  <div class="prep">
    <div class="controls">
      <b>{{ klass.name }}</b>
      <select v-model.number="pick.week" :aria-label="`أسبوع الحزمة لـ ${klass.name}`">
        <option :value="null">الأسبوع القادم ({{ prep?.next_week ?? "-" }})</option>
        <option v-for="w in prep?.weeks ?? []" :key="w.week_no" :value="w.week_no">
          الأسبوع {{ w.week_no }} · {{ fmtShort(w.start_date) }} – {{ fmtShort(w.end_date) }}
        </option>
      </select>
      <button class="btn sm primary" :disabled="busy || week === null" @click="build">
        <i v-if="busy" class="spinner" /> ابنِ حزمة الأسبوع {{ week ?? "" }}
      </button>
    </div>
    <div v-if="error" class="error-box">{{ error }}</div>

    <p v-if="!last" class="muted">لم تُبنَ حزمة لهذا الصف بعد.</p>
    <template v-else>
      <p class="status">
        <span class="pill" :class="last.ok ? 'ok' : last.error ? 'bad' : 'warn'">
          الأسبوع {{ last.week }} · {{ last.ok ? "سليمة" : last.error ? "توقفت" : "تحتاج نظرك" }}
        </span>
        <span class="muted">{{ fmtStamp(last.at) }}</span>
        <span v-if="last.same_as_previous === true" class="pill info">مطابقة للتشغيل السابق</span>
        <span v-else-if="last.same_as_previous === false" class="pill warn">تختلف عن التشغيل السابق</span>
      </p>
      <div v-if="last.error" class="error-box">{{ last.error }}</div>
      <template v-else>
        <p v-if="last.folder" class="folder"><span class="muted">المجلد:</span> <code>{{ last.folder }}</code>
          <span class="muted">· {{ last.files }} ملفًا، نُزّل منها {{ last.downloads }}</span></p>

        <div class="table-wrap">
          <table>
            <thead><tr><th>#</th><th>الدرس</th><th>اليوم والحصة</th><th>الملفات</th><th>ملاحظات</th></tr></thead>
            <tbody>
              <tr v-for="l in last.lessons ?? []" :key="l.position">
                <td class="tight mono">{{ l.position }}</td>
                <td>{{ l.part }}</td>
                <td class="tight">{{ l.day }} {{ fmtShort(l.date) }} · ح{{ l.period }}</td>
                <td>{{ filesLine(l) }}</td>
                <td class="notes">
                  <span v-for="m in l.missing" :key="m" class="pill warn">بلا {{ m }}</span>
                  <span v-if="l.platform_differs" class="muted">
                    على المنصة: {{ l.platform_date ? fmtShort(l.platform_date) : "بلا تاريخ" }}{{ l.platform_period ? ` ح${l.platform_period}` : "" }}
                  </span>
                  <span v-for="n in notes(l)" :key="n" class="muted">{{ n }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="last.message" class="message">
          <div class="msg-head">
            <b>صف الرسالة الأسبوعية</b>
            <button class="btn sm" @click="copyRow">{{ copied ? "نُسخ" : "نسخ الصف" }}</button>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th v-for="h in last.message.header" :key="h">{{ h }}</th></tr></thead>
              <tbody><tr><td v-for="(c, i) in last.message.row" :key="i">{{ c }}</td></tr></tbody>
            </table>
          </div>
          <small v-if="last.pages_unknown?.length" class="muted">
            لا صفحات مسجلة في جدول الكتاب للدروس: {{ last.pages_unknown.join("، ") }}.
          </small>
        </div>

        <ul class="checks">
          <li><span class="pill" :class="staleCount ? 'bad' : 'ok'">الأعوام</span>
            {{ staleCount ? `بقي 2024 أو 2025 في ${staleCount} ملف` : "لا يبقى 2024 ولا 2025 في أي ملف" }}</li>
          <li v-for="c in last.word_check ?? []" :key="c.file">
            <span class="pill" :class="c.ok === null ? 'info' : c.ok ? 'ok' : 'bad'">Word · {{ c.template }}</span>
            <template v-if="c.ok === null">{{ c.note }}</template>
            <template v-else-if="c.ok">
              فتحه Word: العام {{ c.years_seen?.length ? `${c.years_seen.join("، ")}–${Number(c.years_seen[0]) + 1}` : "" }} في الرأس والتذييل،
              والمعلم والتاريخ والمتابعة سليمة، وصُدّر PDF
            </template>
            <template v-else>{{ c.problems?.join("، ") }}</template>
          </li>
          <li v-if="last.teacher_missing"><span class="pill warn">اسم المعلم</span> غير مضبوط في الإعدادات (config/local.json).</li>
          <li v-for="e in last.errors ?? []" :key="e"><span class="pill bad">خطأ</span> {{ e }}</li>
        </ul>
      </template>
    </template>
  </div>
</template>

<style scoped>
.prep { display: grid; gap: 10px; }
.status { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0; font-size: 14px; }
.folder { margin: 0; font-size: 13.5px; overflow-wrap: anywhere; }
.folder code { direction: ltr; unicode-bidi: plaintext; }
.notes { display: flex; flex-wrap: wrap; gap: 4px 8px; font-size: 13px; }
.message { display: grid; gap: 6px; }
.msg-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.checks { list-style: none; padding: 0; margin: 0; display: grid; gap: 4px; font-size: 14px; }
</style>
