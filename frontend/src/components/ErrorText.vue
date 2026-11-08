<script setup lang="ts">
import { computed } from "vue";

import { explainError } from "@/utils/errors";

/** نص خطأ: جملة عربية مع الحل إن عُرف النوع، والنص التقني الأصلي في تفاصيل بـ dir=ltr؛ وغير المعروف يُعزل بـ bdi. */
const props = defineProps<{ text: string | null | undefined }>();
const info = computed(() => explainError(props.text));
</script>

<template>
  <span v-if="info.summary" class="err-text">
    <b>{{ info.summary }}.</b> <span>{{ info.hint }}</span>
    <details class="tech">
      <summary class="muted">التفاصيل التقنية</summary>
      <code class="raw" dir="ltr">{{ text }}</code>
    </details>
  </span>
  <bdi v-else dir="auto" class="err-text">{{ text }}</bdi>
</template>

<style scoped>
.err-text { overflow-wrap: anywhere; min-inline-size: 0; }
.tech { max-inline-size: 100%; }
.tech summary { cursor: pointer; font-size: var(--fs-sm); }
.raw { display: block; margin-block-start: var(--sp-1); white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
