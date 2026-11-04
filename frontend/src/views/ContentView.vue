<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";

import { neo } from "@/api/neo";
import type { ContentProposal } from "@/api/types";
import { useConfirm } from "@/composables/useConfirm";
import { TONE } from "@/domain";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";

/**
 * محرك المحتوى: اقتراحات الإضافة لكل درس ناقص (وصف، وصورة بطاقة، وقسم تهيئة، وتقييم ذاتي التصحيح).
 * تعدّل النص ثم تعتمد، ويُطبَّق على درس واحد في كل مرة؛ لا يُمس الموجود.
 */
const route = useRoute();
const router = useRouter();
const classes = useClassesStore();
const jobs = useJobsStore();
const confirm = useConfirm();

const lms = computed(() => Number(route.query.class) || classes.items[0]?.lms_id);
const items = ref<ContentProposal[]>([]);
const error = ref("");
const loading = ref(false);
const drafts = ref<Record<number, string>>({}); // تعديلات لم تُحفظ بعد، بمعرّف الاقتراح
const open = ref<number | null>(null);

async function load() {
  if (!lms.value) return;
  loading.value = true;
  try {
    items.value = await neo.proposals<ContentProposal>("content", { class: lms.value });
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}
watch(lms, load, { immediate: true });
const stop = jobs.onFinished((j) => { if (j.kind.startsWith("content_")) void load(); });
onBeforeUnmount(stop);

// تعديل لم يُحفظ لا يضيع بمغادرة الصفحة أو إغلاقها دون تنبيه
onBeforeRouteLeave(() => !unsaved.value || confirm({
  title: "تعديل لم يُحفظ",
  body: "عدّلتَ نص اقتراح ولم تحفظه ولم تعتمده. إن غادرت الصفحة ضاع التعديل.",
  confirm: "غادر دون حفظ",
}));
const warnUnload = (e: BeforeUnloadEvent) => {
  if (unsaved.value) e.preventDefault();
};
onMounted(() => window.addEventListener("beforeunload", warnUnload));
onBeforeUnmount(() => window.removeEventListener("beforeunload", warnUnload));

interface Group { lesson: ContentProposal["lesson"]; run: number; props: ContentProposal[] }
const groups = computed<Group[]>(() => {
  const by = new Map<number, Group>();
  for (const p of items.value) {
    const g = by.get(p.lesson.id) ?? { lesson: p.lesson, run: p.run, props: [] };
    g.props.push(p);
    by.set(p.lesson.id, g);
  }
  return [...by.values()].sort((a, b) => a.lesson.position - b.lesson.position);
});
const latestRun = computed(() => Math.max(0, ...items.value.map((p) => p.run)));
const allPending = computed(() => items.value.filter((p) => p.status === "pending" && p.run === latestRun.value));
const allApproved = computed(() => items.value.filter((p) => p.status === "approved" && p.run === latestRun.value));
const pending = (g: Group) => g.props.filter((p) => p.status === "pending");
const approved = (g: Group) => g.props.filter((p) => p.status === "approved");
const field = (p: ContentProposal) => (p.kind === "description" || p.kind === "assessment" || p.kind === "outcomes" ? "text" : p.kind === "section" ? "html" : "");
/** النص المعروض: تعديلك غير المحفوظ ما دام الاقتراح قيد المراجعة، وإلا ما حُفظ فعلًا على الخادم */
const text = (p: ContentProposal) =>
  (p.status === "pending" ? drafts.value[p.id] : undefined) ?? String(p.payload[field(p)] ?? "");
const unsaved = computed(() => Object.keys(drafts.value).length > 0);

async function plan() {
  try {
    await jobs.enqueue("content_plan", { classes: [lms.value] });
  } catch (e) {
    error.value = (e as Error).message;
  }
}

/** يحفظ تعديل الاقتراح إن وُجد؛ false إن رفضه الخادم (صيغة التقييم مثلًا)، فيبقى التعديل في صندوقه */
async function save(p: ContentProposal): Promise<boolean> {
  const f = field(p);
  if (!f || drafts.value[p.id] === undefined) return true;
  try {
    const updated = await neo.editContent(p.id, { [f]: drafts.value[p.id] });
    Object.assign(p, updated);
    delete drafts.value[p.id];
    return true;
  } catch (e) {
    error.value = `لم يُحفظ تعديل «${p.kind_label}»: ${(e as Error).message}`;
    return false;
  }
}

async function decide(ids: number[], decision: "approve" | "reject" | "reset") {
  if (!ids.length) return;
  try {
    error.value = "";
    if (decision === "approve") {
      // تعديل لم يُحفظ يُحفظ قبل الاعتماد، وإلا اعتُمد النص الأصلي وبقي الصندوق يعرض تعديلك
      for (const p of items.value.filter((x) => ids.includes(x.id) && drafts.value[x.id] !== undefined)) {
        if (!(await save(p))) return;
      }
    }
    await neo.decide("content", ids, decision);
    ids.forEach((id) => delete drafts.value[id]);
    await load();
  } catch (e) {
    error.value = (e as Error).message;
  }
}

async function apply(g: Group) {
  const n = approved(g).length;
  const ok = await confirm({
    title: `إضافة المحتوى المعتمد إلى الدرس ${g.lesson.position}`,
    body: `سيضيف العامل ${n} عنصرًا معتمدًا إلى «${g.lesson.title}» على منصة قطر للتعليم. `
      + "إضافة فقط: يُقرأ الدرس قبل كل إضافة، وما له وصف أو صورة أو قسم بالاسم نفسه يُتخطّى.",
    confirm: "أضف إلى هذا الدرس",
    danger: true,
  });
  if (!ok) return;
  try {
    await jobs.enqueue("content_apply", { run: g.run, lesson: g.lesson.id });
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const count = (p: ContentProposal) => (Array.isArray(p.payload.questions) ? p.payload.questions.length : 0);
async function applyAll() {
  const ok = await confirm({
    title: "إضافة كل المحتوى المعتمد في الصف",
    body: `سيضيف العامل ${allApproved.value.length} عنصرًا معتمدًا إلى دروس الصف على منصة قطر للتعليم، درسًا درسًا، `
      + "ثم يدقّق الجودة تلقائيًا. إضافة فقط: ما هو موجود يُتخطّى.",
    confirm: "أضف الكل",
    danger: true,
  });
  if (!ok) return;
  try {
    await jobs.enqueue("content_apply", { run: latestRun.value });
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const imageUrl = (p: ContentProposal) => `/api/neo/proposals/content/${p.id}/image/?v=${p.applied_at ?? ""}`;
</script>

<template>
  <header class="page-head">
    <div>
      <h1>محرك المحتوى</h1>
      <p>لكل درس ناقص: وصف من نتاجاته، وصورة بطاقة بلون وحدته، وقسم تهيئة، وتقييم من بنك أسئلة موضوعه. عدّل ثم اعتمد، ثم أضف إلى درس واحد.</p>
    </div>
    <div class="actions">
      <button v-if="allPending.length" class="btn ghost sm" @click="decide(allPending.map((p) => p.id), 'approve')">
        اعتمد كل المنتظر ({{ allPending.length }})
      </button>
      <button v-if="allApproved.length" class="btn sm" :disabled="jobs.busy('content_apply', undefined, latestRun)" @click="applyAll">
        <i v-if="jobs.busy('content_apply', undefined, latestRun)" class="spinner" /> أضف كل المعتمد ({{ allApproved.length }})
      </button>
      <button class="btn sm" :disabled="!lms || jobs.busy('content_plan', lms)" @click="plan">
        <i v-if="jobs.busy('content_plan', lms)" class="spinner" /> اقترح للدروس الناقصة
      </button>
    </div>
  </header>

  <nav class="seg" aria-label="الصف">
    <button v-for="c in classes.items" :key="c.lms_id" :class="{ on: c.lms_id === lms }"
            @click="router.replace({ query: { class: c.lms_id } })">{{ c.name }}</button>
  </nav>

  <div v-if="error" class="error-box">{{ error }}</div>
  <p v-else-if="loading && !items.length" class="empty"><i class="spinner" /> تحميل...</p>
  <p v-else-if="!groups.length" class="empty">لا اقتراحات بعد. شغّل تدقيق الجودة من صفحة الدروس، ثم «اقترح للدروس الناقصة».</p>

  <section v-for="g in groups" :key="g.lesson.id" class="card lesson" :class="{ old: g.run !== latestRun }">
    <header class="l-head">
      <div>
        <h2>{{ g.lesson.position }}. {{ g.lesson.title }}</h2>
        <small class="muted">
          <span v-for="p in g.props" :key="p.id" class="pill" :class="TONE[p.status]">{{ p.kind_label }} · {{ p.status_label }}</span>
        </small>
      </div>
      <div class="actions">
        <button v-if="pending(g).length" class="btn ghost sm" @click="decide(pending(g).map((p) => p.id), 'approve')">
          اعتمد الكل ({{ pending(g).length }})
        </button>
        <button v-if="approved(g).length" class="btn sm" :disabled="jobs.busy('content_apply', undefined, g.run)" @click="apply(g)">
          <i v-if="jobs.busy('content_apply', undefined, g.run)" class="spinner" /> أضف المعتمد ({{ approved(g).length }})
        </button>
        <button class="btn ghost sm" @click="open = open === g.lesson.id ? null : g.lesson.id">
          {{ open === g.lesson.id ? "طيّ" : "عرض" }}
        </button>
      </div>
    </header>

    <div v-if="open === g.lesson.id" class="props">
      <article v-for="p in g.props" :key="p.id" class="prop">
        <div class="p-head">
          <b>{{ p.kind_label }}</b>
          <span class="pill" :class="TONE[p.status]">{{ p.status_label }}</span>
          <span v-if="p.error" class="err">{{ p.error }}</span>
          <span class="grow" />
          <template v-if="p.status === 'pending'">
            <button v-if="drafts[p.id] !== undefined" class="btn sm" @click="save(p)">احفظ التعديل</button>
            <button class="btn ghost sm" @click="decide([p.id], 'approve')">اعتمد</button>
            <button class="btn ghost sm" @click="decide([p.id], 'reject')">ارفض</button>
          </template>
          <button v-else-if="p.status === 'approved'" class="btn ghost sm" @click="decide([p.id], 'reset')">أعد للمراجعة</button>
        </div>
        <img v-if="p.kind === 'image'" :src="imageUrl(p)" :alt="`صورة البطاقة: ${p.payload.title}`" class="tile">
        <textarea v-else :value="text(p)" :readonly="p.status !== 'pending'" :rows="p.kind === 'description' ? 5 : p.kind === 'section' ? 8 : p.kind === 'outcomes' ? 3 : 14"
                  dir="rtl" @input="drafts[p.id] = ($event.target as HTMLTextAreaElement).value" />
        <small v-if="p.kind === 'section'" class="muted">القسم يُنشأ باسم «{{ p.payload.name }}» ومحتواه HTML أعلاه.</small>
        <small v-else-if="p.kind === 'outcomes'" class="muted">تُربط نتاجات المنهج أعلاه بالدرس (درس بلا نتاجات فقط).</small>
        <small v-else-if="p.kind === 'assessment'" class="muted">
          تقييم ذاتي التصحيح باسم «{{ p.payload.name }}»، {{ count(p) }} أسئلة بدرجة لكل سؤال.
          الصيغة: «س:» للسؤال، «*» للخيار الصحيح و«-» لغيره، أو «= صح/خطأ». يُحفظ التعديل بعد التحقق من الصيغة.
        </small>
      </article>
    </div>
  </section>
</template>

<style scoped>
.lesson { gap: 10px; }
.lesson.old { opacity: .7; }
.l-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: start; gap: 10px; }
.l-head h2 { font-size: 18px; margin: 0; }
.l-head small { display: flex; flex-wrap: wrap; gap: 4px; margin-block-start: 4px; }
.actions { display: flex; flex-wrap: wrap; gap: 6px; }
.props { display: grid; gap: 12px; }
.prop { display: grid; gap: 8px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); }
.p-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.grow { flex: 1; }
.err { color: var(--bad); font-size: 13px; }
textarea { inline-size: 100%; font: 14px/1.6 var(--f-body); padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--fg); resize: vertical; }
.tile { inline-size: min(100%, 320px); border-radius: 8px; border: 1px solid var(--line); }
</style>
