<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import ScorecardPanel from "@/components/ScorecardPanel.vue";
import { useTheme } from "@/composables/useTheme";

/**
 * تبويب واحد: بطاقة الأداء (الأرقام الحيّة) أعلاه، ثم تقرير SWOT الذي تُوسم بنوده بالمعايير نفسها.
 * تقرير SWOT كما هو في docs/report (المصدر الوحيد)، داخل إطار من الأصل نفسه.
 * الإطار بطول محتواه فيتمرر مع الصفحة، ويتبع ثيم الواجهة، وتُكبَّر لقطاته في الصفحة الأم.
 */
const SRC = "/docs/report/platform_report.html";
const SECTIONS: [string, string][] = [
  ["scorecard", "بطاقة الأداء"], ["summary", "الملخص"], ["swot", "المصفوفة"], ["tows", "الاستراتيجيات"], ["evidence", "الأدلة"],
  ["student", "الطالب"], ["cards", "البطاقات"], ["automation", "الأتمتة"], ["roadmap", "الخطة"],
];
// داخل الواجهة: شريطها العلوي يكفي، والروابط تُفتح خارج الإطار
const EMBED_CSS = ".topbar{display:none!important} .wrap{padding-block:0 24px}";

const { theme } = useTheme();
const frame = ref<HTMLIFrameElement | null>(null);
const height = ref(1400);
const state = ref<"loading" | "ready" | "failed">("loading");
const zoom = ref<{ src: string; alt: string } | null>(null);
let observer: ResizeObserver | undefined;

const doc = () => frame.value?.contentDocument ?? null;

function onLoad() {
  const d = doc();
  if (!d?.getElementById("swot")) {
    state.value = "failed";
    return;
  }
  const style = d.createElement("style");
  style.textContent = EMBED_CSS;
  d.head.append(style);
  const base = d.createElement("base");
  base.target = "_blank";
  d.head.prepend(base);
  d.documentElement.setAttribute("data-theme", theme.value);

  d.addEventListener("click", (e) => {
    const img = (e.target as Element | null)?.closest?.(".ev img") as HTMLImageElement | null;
    if (!img) return;
    e.preventDefault();
    e.stopPropagation(); // قبل مستمع التقرير نفسه، الذي يكبّر داخل الإطار الطويل
    zoom.value = { src: img.src, alt: img.alt };
  }, true);

  // الطول يتغير باكتمال اللقطات وبعرض النافذة؛ ResizeObserver لا يكفي وحده (يتأخر في الألسنة المخفية)
  const View = d.defaultView as (Window & typeof globalThis) | null;
  observer = View ? new View.ResizeObserver(fit) : undefined;
  observer?.observe(d.body);
  d.addEventListener("load", fit, true); // اكتمال كل صورة
  state.value = "ready";
  fit();
}

function fit() {
  const d = doc();
  if (d?.body) height.value = Math.ceil(d.body.getBoundingClientRect().height) + 8;
}

watch(theme, (t) => doc()?.documentElement.setAttribute("data-theme", t));

function go(id: string) {
  if (id === "scorecard") {
    document.getElementById("scorecard")?.scrollIntoView({ behavior: "smooth" });
    return;
  }
  const target = doc()?.getElementById(id);
  if (!target || !frame.value) return;
  // فوق القسم: الشريط العلوي وشريط الأقسام، وكلاهما لاصق ويطول حين يلتف في الشاشة الضيقة
  const stuck = (document.querySelector(".topbar")?.getBoundingClientRect().height ?? 50)
    + (document.querySelector(".sections")?.getBoundingClientRect().height ?? 46) + 16;
  const top = frame.value.getBoundingClientRect().top + target.getBoundingClientRect().top + window.scrollY - stuck;
  window.scrollTo({ top, behavior: "smooth" });
}

const closeZoom = (e: KeyboardEvent) => { if (e.key === "Escape") zoom.value = null; };
onMounted(() => {
  window.addEventListener("keydown", closeZoom);
  window.addEventListener("resize", fit);
});
onBeforeUnmount(() => {
  observer?.disconnect();
  window.removeEventListener("keydown", closeZoom);
  window.removeEventListener("resize", fit);
});
</script>

<template>
  <header class="page-head">
    <div>
      <h1>SWOT والأداء</h1>
      <p>المعايير الثمانية بأرقامها الحيّة، ثم القوة والضعف والفرص والتهديدات موسومة بمعاييرها، والاستراتيجيات وخطة العمل.</p>
    </div>
    <div class="actions">
      <a class="btn sm" :href="SRC" target="_blank" rel="noopener">فتح التقرير مستقلًا</a>
      <a class="btn sm" :href="`${SRC}?share`" target="_blank" rel="noopener">نسخة المشاركة</a>
    </div>
  </header>

  <nav class="seg sections" aria-label="أقسام التبويب">
    <button v-for="[id, label] in SECTIONS" :key="id" :disabled="id !== 'scorecard' && state !== 'ready'" @click="go(id)">
      {{ label }}
    </button>
  </nav>

  <ScorecardPanel />

  <h2 class="report-title">تقرير SWOT</h2>

  <p v-if="state === 'loading'" class="empty"><i class="spinner" /> تحميل التقرير...</p>
  <div v-if="state === 'failed'" class="error-box">
    تعذّر تحميل التقرير من <code>{{ SRC }}</code>. تأكد أن الخادم يعمل وأن الملف موجود في docs/report.
  </div>

  <iframe ref="frame" :src="SRC" title="تحليل SWOT لمنصة قطر للتعليم" class="report" :class="{ hidden: state !== 'ready' }"
          :style="{ blockSize: `${height}px` }" @load="onLoad" />

  <div v-if="zoom" class="zoom" role="dialog" aria-label="عرض اللقطة" @click="zoom = null">
    <img :src="zoom.src" :alt="zoom.alt">
  </div>
</template>

<style scoped>
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.report-title { margin-block-end: -12px; }
.sections { position: sticky; inset-block-start: calc(var(--topbar-h, 50px) + 8px); z-index: 4; box-shadow: 0 2px 10px rgba(0, 0, 0, .06); }
.sections button:disabled { opacity: .5; cursor: default; }
.report { inline-size: 100%; border: 0; display: block; background: transparent; }
.report.hidden { position: absolute; visibility: hidden; block-size: 0 !important; }
.zoom {
  position: fixed; inset: 0; z-index: 40; background: rgba(0, 0, 0, .86); display: grid; place-items: center;
  padding: 16px; cursor: zoom-out;
}
.zoom img { max-inline-size: 100%; max-block-size: 100%; border-radius: 8px; }
</style>
