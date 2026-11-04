<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { neo } from "@/api/neo";
import type {
  AssignProposal, DateProposal, Decision, Proposal, ProposalKind, PublishProposal, RunNotes as Notes,
} from "@/api/types";
import RunNotes from "@/components/RunNotes.vue";
import { useConfirm } from "@/composables/useConfirm";
import { STAGES, stageOf, TONE } from "@/domain";
import { useClassesStore } from "@/stores/classes";
import { useJobsStore } from "@/stores/jobs";
import { fmtDay, fmtShort, fmtStamp, fmtWhen } from "@/utils/format";

const route = useRoute();
const router = useRouter();
const classes = useClassesStore();
const jobs = useJobsStore();
const confirm = useConfirm();

// بلا مرحلة في الرابط: أول مرحلة فيها ما ينتظرك، وإلا أولها (التواريخ)
const kind = computed<ProposalKind>(() => (route.params.kind as ProposalKind)
  || STAGES.find((s) => classes.openReview[s.kind])?.kind || "date");
const stage = computed(() => stageOf(kind.value));
const lms = computed(() => Number(route.query.class) || undefined);
/** open: المعلّق والمعتمد من كل العمليات · latest: آخر اقتراح لكل صف بكل حالاته */
const scope = ref<"open" | "latest">("open");

const items = ref<Proposal[]>([]);
const loading = ref(false);
const error = ref("");
const selected = ref(new Set<number>());

async function load() {
  loading.value = true;
  error.value = "";
  try {
    if (scope.value === "open") {
      items.value = await neo.proposals(kind.value, { class: lms.value, status: "pending,approved" });
    } else {
      const runs = classes.items
        .filter((c) => !lms.value || c.lms_id === lms.value)
        .map((c) => c.overview.review[kind.value].latest_run)
        .filter((r): r is number => r !== null);
      items.value = (await Promise.all(runs.map((run) => neo.proposals(kind.value, { run })))).flat();
    }
    const ids = new Set(items.value.map((p) => p.id));
    selected.value = new Set([...selected.value].filter((id) => ids.has(id)));
    void loadNotes();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

/** ملاحظات كل اقتراح: ما استُبعد عند الاقتراح، وما توقف أو بقي على المنصة في آخر تطبيق له */
const notes = ref<Record<number, Notes>>({});
async function loadNotes() {
  const runs = [...new Set(items.value.map((p) => p.run))];
  const got = await Promise.all(runs.map(async (run) => {
    try {
      const [plan, applied] = await Promise.all([neo.runs({ id: run, limit: 1 }), neo.runs({ plan_run: run, limit: 1 })]);
      const a = applied.results[0]?.summary ?? {};
      const n: Notes = { unconfirmed_match: plan.results[0]?.summary.unconfirmed_match,
                         stopped: a.stopped, not_attempted: a.not_attempted, kept_on_platform: a.kept_on_platform, error: a.error };
      return [run, n] as const;
    } catch {
      return [run, {}] as const;
    }
  }));
  notes.value = Object.fromEntries(got);
}

watch([kind, lms, scope, () => classes.items.length], () => {
  selected.value = new Set();
  load();
}, { immediate: true });
const off = jobs.onFinished(load);
onUnmounted(off);

interface Group { run: number; lms: number; items: Proposal[]; approved: number }
const groups = computed<Group[]>(() => {
  const by = new Map<number, Group>();
  for (const p of items.value) {
    const g = by.get(p.run) ?? { run: p.run, lms: p.lms_id, items: [], approved: 0 };
    g.items.push(p);
    if (p.status === "approved") g.approved += 1;
    by.set(p.run, g);
  }
  return [...by.values()].sort((a, b) => b.run - a.run);
});

const decidable = (p: Proposal) => p.status === "pending" || p.status === "approved";
/** المنتظر الذي يقبل الاعتماد: مطابقة درسه مؤكدة */
const approvable = (g: Group) => g.items.filter((p) => p.status === "pending" && p.evidence.sure);
const halted = computed(() => !!jobs.session?.halted);
const notice = ref("");
function toggle(id: number) {
  const s = new Set(selected.value);
  if (s.has(id)) s.delete(id);
  else s.add(id);
  selected.value = s;
}
function toggleGroup(g: Group) {
  const ids = g.items.filter(decidable).map((p) => p.id);
  const all = ids.every((id) => selected.value.has(id));
  const s = new Set(selected.value);
  ids.forEach((id) => (all ? s.delete(id) : s.add(id)));
  selected.value = s;
}
const groupChecked = (g: Group) => g.items.some(decidable) && g.items.filter(decidable).every((p) => selected.value.has(p.id));

const busy = ref(false);
async function decide(decision: Decision, ids = [...selected.value]) {
  if (!ids.length) return;
  busy.value = true;
  notice.value = "";
  const byId = new Map(items.value.map((p) => [p.id, p]));
  const unsure = decision === "approve" ? ids.filter((id) => byId.get(id)?.status === "pending" && !byId.get(id)?.evidence.sure) : [];
  try {
    const { changed } = await neo.decide(kind.value, ids, decision);
    if (unsure.length)
      notice.value = `اعتُمد ${changed}، ولم يُعتمد ${unsure.length} لأن مطابقة درسه بالخطة غير مؤكدة: أكّدها من «الدروس» ثم اعتمد.`;
    selected.value = new Set();
    await Promise.all([load(), classes.load()]);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}

async function apply(g: Group, limit?: number) {
  const n = limit ?? g.approved;
  const ok = await confirm({
    title: limit ? "تجربة على عنصر واحد" : `تطبيق ${stage.value.label} على المنصة`,
    body: `سيكتب العامل على منصة قطر للتعليم ${limit ? "أول عنصر معتمد فقط" : `${n} عنصرًا معتمدًا`} في ${classes.name(g.lms)}. `
      + "تُقرأ الحالة قبل كل كتابة، ولا يُكرَّر ما طُبّق سابقًا. " + (stage.value.after ?? ""),
    confirm: limit ? "جرّب على واحد" : "طبّق على المنصة",
    danger: true,
  });
  if (!ok) return;
  try {
    await jobs.enqueue(stage.value.apply, limit ? { run: g.run, limit } : { run: g.run });
  } catch (e) {
    error.value = (e as Error).message;
  }
}

function setClass(e: Event) {
  const v = (e.target as HTMLSelectElement).value;
  router.replace({ query: v ? { class: v } : {} });
}

// خانات كل نوع
const asDate = (p: Proposal) => p as DateProposal;
const asAssign = (p: Proposal) => p as AssignProposal;
const asPublish = (p: Proposal) => p as PublishProposal;
</script>

<template>
  <header class="page-head">
    <div>
      <h1>المراجعة</h1>
      <p>اعتمد ما تريده، ثم طبّقه على المنصة. لا يُكتب شيء قبل ضغط «طبّق».</p>
    </div>
  </header>

  <div class="controls">
    <nav class="seg" aria-label="المرحلة">
      <RouterLink v-for="s in STAGES" :key="s.kind" :to="{ name: 'review', params: { kind: s.kind }, query: route.query }"
                  :class="{ on: s.kind === kind }">
        {{ s.label }} <span v-if="classes.openReview[s.kind]" class="muted">({{ classes.openReview[s.kind] }})</span>
      </RouterLink>
    </nav>
    <select :value="lms ?? ''" aria-label="الصف" @change="setClass">
      <option value="">كل الصفوف</option>
      <option v-for="c in classes.items" :key="c.lms_id" :value="c.lms_id">{{ c.name }}</option>
    </select>
    <div class="seg" role="group" aria-label="النطاق">
      <button :class="{ on: scope === 'open' }" @click="scope = 'open'">قيد المراجعة</button>
      <button :class="{ on: scope === 'latest' }" @click="scope = 'latest'">آخر اقتراح كاملًا</button>
    </div>
  </div>

  <div v-if="selected.size" class="bulk card">
    <b>{{ selected.size }} محدد</b>
    <button class="btn primary sm" :disabled="busy" @click="decide('approve')">اعتماد</button>
    <button class="btn sm" :disabled="busy" @click="decide('reset')">إرجاع للمراجعة</button>
    <button class="btn sm" :disabled="busy" @click="decide('reject')">رفض</button>
    <button class="btn ghost sm" @click="selected = new Set()">إلغاء التحديد</button>
  </div>

  <div v-if="halted" class="error-box">
    الكتابة على المنصة موقوفة آليًا: {{ jobs.session?.halt_reason }}. يمكنك المراجعة والاعتماد، ولا يُطبَّق شيء حتى تعيد التفعيل من الشريط العلوي.
  </div>
  <div v-if="notice" class="note-box">{{ notice }}</div>
  <div v-if="error" class="error-box">{{ error }}</div>
  <p class="muted rule">الاعتماد صالح 48 ساعة، ويعود للمراجعة إن تغيّر الدرس على المنصة بعده. لا يُعتمد درس مطابقته بالخطة غير مؤكدة.</p>
  <p v-if="loading && !items.length" class="empty"><i class="spinner" /> تحميل...</p>
  <p v-else-if="!groups.length" class="empty">
    {{ scope === "open" ? `لا اقتراحات تنتظر المراجعة في ${stage.label}.` : `آخر اقتراح في ${stage.label} لم يتضمن عناصر.` }}
    اطلب «جلب واقتراح» من شاشة اليوم لإنشاء اقتراح جديد.
  </p>

  <section v-for="g in groups" :key="g.run" class="group">
    <header class="g-head">
      <label class="check">
        <input type="checkbox" :checked="groupChecked(g)" :disabled="!g.items.some(decidable)" @change="toggleGroup(g)">
        <b>{{ classes.name(g.lms) }}</b>
      </label>
      <span class="muted">الاقتراح #{{ g.run }} · {{ g.items.length }} عنصر</span>
      <span class="spacer" />
      <button v-if="approvable(g).length" class="btn sm" :disabled="busy"
              @click="decide('approve', approvable(g).map((p) => p.id))">
        اعتماد الكل ({{ approvable(g).length }})
      </button>
      <button v-if="stage.trial && g.approved > 1" class="btn sm" :disabled="halted || jobs.busy(stage.apply, undefined, g.run)"
              @click="apply(g, 1)">
        جرّب على واحد
      </button>
      <button class="btn primary sm" :disabled="halted || !g.approved || jobs.busy(stage.apply, undefined, g.run)"
              :title="halted ? 'الكتابة موقوفة آليًا' : ''" @click="apply(g)">
        <i v-if="jobs.busy(stage.apply, undefined, g.run)" class="spinner" /> طبّق المعتمد ({{ g.approved }})
      </button>
    </header>
    <RunNotes v-if="notes[g.run]" :notes="notes[g.run]" compact />

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="tight" />
            <template v-if="kind === 'assign'"><th>التقييم</th><th>تاريخ الدرس</th><th>البداية</th><th>الاستحقاق</th></template>
            <template v-else><th>الدرس</th></template>
            <template v-if="kind === 'date'"><th>التاريخ المقترح</th><th>الحصة</th><th>الأسبوع</th></template>
            <template v-if="kind === 'publish'"><th>إظهار</th><th>نقاط</th></template>
            <th v-if="kind !== 'publish'">تنبيهات</th>
            <th>قبل ← بعد، والسبب والأثر</th>
            <th>الحالة</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in g.items" :key="p.id" :class="{ sel: selected.has(p.id) }">
            <td class="tight">
              <input type="checkbox" :checked="selected.has(p.id)" :disabled="!decidable(p)"
                     :aria-label="`تحديد ${p.id}`" @change="toggle(p.id)">
            </td>
            <template v-if="kind === 'assign'">
              <td>{{ asAssign(p).assessment.title }}</td>
              <td>{{ fmtShort(asAssign(p).lesson_date) }}</td>
              <td>{{ fmtStamp(asAssign(p).begin_at) }}</td>
              <td>{{ fmtStamp(asAssign(p).end_at) }} <span v-if="asAssign(p).allow_late" class="muted">· يقبل التأخير</span></td>
            </template>
            <template v-else>
              <td>{{ asDate(p).lesson.position }}. {{ asDate(p).lesson.title }}</td>
            </template>
            <template v-if="kind === 'date'">
              <td>{{ fmtDay(asDate(p).proposed_date) }}</td>
              <td>{{ asDate(p).proposed_period }}</td>
              <td>{{ asDate(p).plan_week_no }}</td>
            </template>
            <template v-if="kind === 'publish'">
              <td>{{ asPublish(p).show ? "نعم" : "-" }}</td>
              <td>{{ asPublish(p).add_points ? "نعم" : "-" }}</td>
            </template>
            <td v-if="kind !== 'publish'" class="muted">{{ asDate(p).flags || "-" }}</td>
            <td class="ev">
              <span v-if="p.evidence.soon" class="pill bad">خلال 48 ساعة</span>
              {{ p.evidence.before }} ← <b>{{ p.evidence.after }}</b>
              <small class="muted">{{ p.evidence.reason }}</small>
              <small>{{ p.evidence.impact }}</small>
            </td>
            <td>
              <span class="pill" :class="TONE[p.status]">{{ p.status_label }}</span>
              <RouterLink v-if="decidable(p) && !p.evidence.sure" class="pill warn as-link"
                          :to="{ name: 'lessons', query: { class: p.lms_id } }" title="لا يُعتمد حتى تؤكد مطابقة الدرس بالخطة">
                مطابقة غير مؤكدة · أكّدها
              </RouterLink>
              <small v-if="p.status === 'approved' && p.evidence.expires_at" class="muted exp">
                يسقط الاعتماد {{ fmtWhen(p.evidence.expires_at) }}
              </small>
              <small v-if="p.error" class="err">{{ p.error }}</small>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.bulk { position: sticky; inset-block-start: calc(var(--topbar-h, 50px) + 6px); z-index: 5; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 14px; }
.group { display: grid; gap: 8px; }
.g-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.check { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; }
.spacer { flex: 1; }
.err { display: block; color: var(--bad); }
.ev small { display: block; }
.exp { display: block; }
.rule { margin: 0; font-size: 13px; }
.as-link { text-decoration: none; display: inline-block; margin-block-start: 4px; }
</style>
