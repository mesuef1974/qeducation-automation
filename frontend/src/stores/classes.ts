import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { neo } from "@/api/neo";
import type { PlatformClass, ProposalKind } from "@/api/types";

export const useClassesStore = defineStore("classes", () => {
  const items = ref<PlatformClass[]>([]);
  const loading = ref(false);
  const error = ref("");

  const byId = computed(() => new Map(items.value.map((c) => [c.lms_id, c])));
  const name = (lms?: number) => (lms ? byId.value.get(lms)?.name ?? `صف ${lms}` : "");

  /** المعلّق + المعتمد لكل نوع، لكل الصفوف */
  const openReview = computed(() => {
    const totals: Record<ProposalKind, number> = { date: 0, assign: 0, publish: 0 };
    for (const c of items.value)
      for (const k of Object.keys(totals) as ProposalKind[])
        totals[k] += c.overview.review[k].pending + c.overview.review[k].approved;
    return totals;
  });

  async function load() {
    loading.value = true;
    try {
      items.value = await neo.classes();
      error.value = "";
    } catch (e) {
      error.value = (e as Error).message;
    } finally {
      loading.value = false;
    }
  }

  return { items, loading, error, byId, name, openReview, load };
});
