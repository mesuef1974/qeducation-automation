<script setup lang="ts">
import { nextTick, ref, watch } from "vue";

import { confirmState, settleConfirm } from "@/composables/useConfirm";

const dialog = ref<HTMLDialogElement | null>(null);

watch(() => confirmState.ask, async (ask) => {
  await nextTick();
  if (ask && !dialog.value?.open) dialog.value?.showModal();
  if (!ask && dialog.value?.open) dialog.value.close();
});
</script>

<template>
  <dialog ref="dialog" class="confirm" @cancel.prevent="settleConfirm(false)">
    <template v-if="confirmState.ask">
      <h3>{{ confirmState.ask.title }}</h3>
      <p>{{ confirmState.ask.body }}</p>
      <div class="actions">
        <button class="btn" :class="confirmState.ask.danger ? 'danger' : 'primary'" autofocus
                @click="settleConfirm(true)">
          {{ confirmState.ask.confirm }}
        </button>
        <button class="btn" @click="settleConfirm(false)">رجوع</button>
      </div>
    </template>
  </dialog>
</template>

<style scoped>
.confirm {
  inline-size: min(460px, calc(100vw - 32px)); border: 1px solid var(--line); border-radius: 14px;
  background: var(--surface); color: var(--fg); padding: 22px; display: grid; gap: 12px;
}
.confirm:not([open]) { display: none; }
.confirm::backdrop { background: rgba(0, 0, 0, .45); }
.confirm p { color: var(--muted); }
.actions { display: flex; gap: 8px; margin-block-start: 6px; }
</style>
