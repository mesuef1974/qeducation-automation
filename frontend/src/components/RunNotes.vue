<script setup lang="ts">
import { computed } from "vue";

import type { RunNotes } from "@/api/types";
import ErrorText from "@/components/ErrorText.vue";

/** ملاحظات ملخص العملية التي تحتاج نظر المعلم، بلغة مقروءة بدل JSON. */
const props = defineProps<{ notes: RunNotes; compact?: boolean }>();

const lines = computed(() => {
  const n = props.notes, out: { tone: "bad" | "warn"; title: string; items?: string[]; err?: boolean }[] = [];
  if (n.error) out.push({ tone: "bad", title: n.error, err: true });
  if (n.stopped)
    out.push({ tone: "bad", title: `توقف التطبيق عند أول خطأ غير متوقع: ${n.stopped}`
      + (n.not_attempted ? ` · لم يُجرَّب ${n.not_attempted} وبقي معتمدًا` : ""), err: true });
  if (n.unconfirmed_match?.length)
    out.push({ tone: "warn", title: `استُبعد ${n.unconfirmed_match.length} درسًا لأن مطابقته بالخطة غير مؤكدة (أكّدها من «الدروس»)`,
               items: n.unconfirmed_match });
  if (n.kept_on_platform?.length)
    out.push({ tone: "warn", title: `مواعيد قائمة على المنصة تخالف المعتمد ولم تُمس (${n.kept_on_platform.length})`,
               items: n.kept_on_platform });
  return out;
});
</script>

<template>
  <ul v-if="lines.length" class="run-notes" :class="{ compact }">
    <li v-for="(l, i) in lines" :key="i" :class="l.tone">
      <ErrorText v-if="l.err" :text="l.title" />
      <b v-else>{{ l.title }}</b>
      <details v-if="l.items?.length">
        <summary class="muted">التفاصيل</summary>
        <ul><li v-for="it in l.items" :key="it">{{ it }}</li></ul>
      </details>
    </li>
  </ul>
</template>

<style scoped>
.run-notes { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; font-size: var(--fs-base); }
.run-notes > li { border-inline-start: 4px solid var(--warn); background: var(--warn-soft); border-radius: 8px; padding: 6px 10px; }
.run-notes > li.bad { border-color: var(--bad); background: var(--bad-soft); }
.run-notes details ul { margin: 4px 0 0; padding-inline-start: 18px; }
.run-notes summary { cursor: pointer; font-size: var(--fs-sm); }
.compact > li { padding: 4px 8px; }
</style>
