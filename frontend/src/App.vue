<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";

import AppTopbar from "@/components/AppTopbar.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import JobDock from "@/components/JobDock.vue";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";

const jobs = useJobsStore();
const classes = useClassesStore();
let off: (() => void) | undefined;

onMounted(() => {
  jobs.refresh();
  classes.load();
  // كل مهمة تنتهي قد تغيّر الملخصات (اقتراح جديد، تطبيق، تحقق)
  off = jobs.onFinished(() => classes.load());
});
onUnmounted(() => off?.());
</script>

<template>
  <AppTopbar />
  <main class="page">
    <RouterView />
  </main>
  <JobDock />
  <ConfirmDialog />
</template>
