<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";

import { neo } from "@/api/neo";
import type { Proposal, ProposalKind } from "@/api/types";
import { useJobsStore } from "@/stores/jobs";
import { fmtDay } from "@/utils/format";

/** الخطوة 4 (التذكير): اقتراح ينتظر قرارك لدرس يبدأ خلال 48 ساعة يظهر أعلى «اليوم» بلون الخطر. */
const KINDS: [ProposalKind, string][] = [["date", "تاريخ"], ["assign", "إسناد"], ["publish", "نشر"], ["content", "محتوى"]];
const jobs = useJobsStore();
const items = ref<{ kind: ProposalKind; label: string; p: Proposal }[]>([]);

function title(p: Proposal): string {
  if ("assessment" in p) return p.assessment.title;
  return `${p.lesson.position}. ${p.lesson.title}`;
}

async function load() {
  try {
    const lists = await Promise.all(KINDS.map(([k]) => neo.proposals(k, { status: "pending,approved" })));
    items.value = lists.flatMap((list, i) => list.filter((p) => p.evidence?.soon)
      .map((p) => ({ kind: KINDS[i][0], label: KINDS[i][1], p })));
  } catch {
    items.value = [];
  }
}
const stop = jobs.onFinished(() => void load());
onMounted(load);
onBeforeUnmount(stop);
</script>

<template>
  <section v-if="items.length" class="card soon" aria-label="اقتراحات لدروس قريبة">
    <header class="head">
      <h2>تنتظر قرارك لدروس تبدأ خلال 48 ساعة ({{ items.length }})</h2>
      <RouterLink to="/review" class="btn sm">راجعها</RouterLink>
    </header>
    <ul>
      <li v-for="i in items.slice(0, 8)" :key="`${i.kind}-${i.p.id}`">
        <span class="pill bad">{{ i.label }}</span>
        {{ title(i.p) }} · {{ fmtDay(i.p.evidence.lesson_date) }}:
        {{ i.p.evidence.before }} ← <b>{{ i.p.evidence.after }}</b>
        <span class="muted">({{ i.p.status_label }})</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.soon { border-color: var(--bad); box-shadow: 0 0 0 2px color-mix(in srgb, var(--bad) 20%, transparent); }
.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
ul { margin: 0; padding-inline-start: 18px; display: grid; gap: 4px; }
</style>
