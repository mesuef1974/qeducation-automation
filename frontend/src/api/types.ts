// أشكال ردود /api/neo/ كما يعيدها Django (neo/api/serializers.py)

export type ProposalKind = "date" | "assign" | "publish" | "content";
export type ProposalStatus = "pending" | "approved" | "rejected" | "applied" | "skipped" | "failed";
export type Decision = "approve" | "reject" | "reset";

export interface LessonRef {
  id: number;
  position: number;
  title: string;
  date: string | null;
  period: number | null;
}

export interface ReviewCount {
  pending: number;
  approved: number;
  latest_run: number | null;
}

export interface Overview {
  lessons: { total: number; dated: number; hidden: number; points: number };
  today: LessonRef[];
  upcoming: LessonRef[];
  review: Record<ProposalKind, ReviewCount>;
  last_verify: { id: number; ok: boolean; at: string | null; summary: Record<string, unknown> } | null;
  prep: PrepOverview;
}

/** حزمة التحضير الأسبوعية (قراءة فقط من المنصة) */
export interface PrepFile {
  name: string;
  role: "prep" | "worksheet" | "presentation" | "section";
  source: string;
  note?: string;
}

export interface PrepLesson {
  position: number;
  title: string;
  part: string;
  folder: string;
  day: string;
  date: string;
  period: number;
  platform_date: string | null;
  platform_period: number | null;
  platform_differs: boolean;
  files: PrepFile[];
  missing: string[];
  extra: string[];
}

export interface PrepCheck {
  template: string;
  file: string;
  ok: boolean | null;
  problems?: string[];
  note?: string;
  pdf?: string;
  years_seen?: string[];
}

export interface PrepRun {
  id: number;
  ok: boolean;
  at: string;
  week: number;
  week_range?: [string, string];
  folder?: string;
  section?: string;
  lessons?: PrepLesson[];
  message?: { header: string[]; row: string[]; file: string };
  pages_unknown?: string[];
  downloads?: number;
  files?: number;
  stale_years?: Record<string, string[]>;
  word_check?: PrepCheck[];
  same_as_previous?: boolean | null;
  platform_differs?: number[];
  errors?: string[];
  teacher_missing?: boolean;
  error?: string;
}

export interface PrepOverview {
  weeks: { week_no: number; start_date: string; end_date: string }[];
  next_week: number | null;
  last: PrepRun | null;
}

export interface PlatformClass {
  lms_id: number;
  name: string;
  active: boolean;
  plan: number;
  plan_title: string;
  points_game: string;
  points: number | null;
  last_fetched_at: string | null;
  /** نقص في دروس المنصة أوقف المزامنة، بانتظار تأكيد المعلم ({} إن لم يكن) */
  shrink_pending: { saved?: number; platform?: number; at?: string; missing?: string[] };
  allow_shrink: boolean;
  overview: Overview;
}

export interface LessonAudit {
  image_default: boolean;
  sections: string[];
  has_outcomes: boolean;
  issues: string[];
  issue_labels: string[];
  audited_at: string;
}

export interface Lesson {
  lms_lesson_id: number;
  lms_id: number;
  position: number;
  title: string;
  description: string;
  date: string | null;
  period: number | null;
  hidden: boolean;
  awards_points: boolean;
  match_code: string;
  match_score: number | null;
  override_code: string;
  /** رمز المطابقة الآلية الذي أكّده المعلم مرة واحدة */
  confirmed_code: string;
  effective_code: string;
  /** المطابقة مؤكدة (يدوية، أو آلية تامة، أو أكّدها المعلم): وحدها تدخل الاقتراح والكتابة */
  match_sure: boolean;
  fetched_at: string;
  audit: LessonAudit | null;
}

/** ما يكتبه الخادم في ملخص العملية ويحتاج نظر المعلم (sync/assign/publish/content services) */
export interface RunNotes {
  unconfirmed_match?: string[];
  stopped?: string;
  not_attempted?: number;
  kept_on_platform?: string[];
  error?: string;
  plan_run?: number;
}

export interface Run {
  id: number;
  lms_id: number;
  class_name: string;
  kind: string;
  kind_label: string;
  started_at: string;
  finished_at: string | null;
  ok: boolean;
  summary: Record<string, unknown> & RunNotes;
}

interface ProposalBase {
  id: number;
  run: number;
  lms_id: number;
  status: ProposalStatus;
  status_label: string;
  error: string;
  applied_at: string | null;
  approved_at: string | null;
  /** الخطوة 4: قبل/بعد والسبب من الخطة والأثر على الطالب؛ soon = درسه خلال 48 ساعة */
  evidence: Evidence;
}

export interface Evidence {
  before: string;
  after: string;
  reason: string;
  impact: string;
  lesson_date: string | null;
  soon: boolean;
  /** مطابقة الدرس بالخطة مؤكدة؛ وإلا لا يُعتمد (أكّدها من «الدروس») */
  sure: boolean;
  /** موعد سقوط الاعتماد (48 ساعة من اعتماده)، للمعتمد فقط */
  expires_at: string | null;
}

export interface DateProposal extends ProposalBase {
  lesson: LessonRef;
  proposed_date: string;
  proposed_period: number;
  plan_week_no: number;
  flags: string;
}

export interface PublishProposal extends ProposalBase {
  lesson: LessonRef;
  show: boolean;
  add_points: boolean;
}

export interface AssignProposal extends ProposalBase {
  assessment: { id: number; title: string; lesson_id: number | null; given: boolean };
  lesson_date: string;
  begin_at: string;
  end_at: string;
  allow_late: boolean;
  flags: string;
}

export interface ContentProposal extends ProposalBase {
  lesson: LessonRef;
  kind: "description" | "image" | "section" | "assessment" | "outcomes";
  kind_label: string;
  payload: Record<string, string | number>;
}

export type Proposal = DateProposal | PublishProposal | AssignProposal | ContentProposal;

export type JobKind =
  | "login" | "sync_plan" | "sync_apply" | "assign_plan" | "assign_apply" | "publish_plan" | "publish_apply" | "verify"
  | "weekly" | "audit" | "content_plan" | "content_apply" | "prep_pack" | "session" | "usage_verify";
export type JobStatus = "queued" | "running" | "done" | "failed";

export interface JobParams {
  classes?: number[];
  run?: number;
  approve?: "all" | "future";
  limit?: number;
  cycle?: string;
  lesson?: number;
  class?: number;
  week?: number;
}

export interface Job {
  id: number;
  kind: JobKind;
  kind_label: string;
  params: JobParams;
  status: JobStatus;
  status_label: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_kind: string;
  error_label: string;
  error: string;
  runs: Run[];
  report: WeeklyReport | Record<string, never>;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface SessionState {
  expired: boolean;
  checked_at: string | null;
  /** للعامل نبض حديث (neo_worker يعمل فعلًا) */
  worker_alive: boolean;
  worker_busy: boolean;
  queued: number;
  /** مفتاح الإيقاف الآلي: الكتابة على المنصة موقوفة حتى تعيد تفعيلها */
  halted: boolean;
  halt_reason: string;
  halted_at: string | null;
}

export interface Criterion {
  key: string; title: string; value: number | null; target: number; unit: string;
  level: number | null; target_level: number | null; measured: boolean; detail: string; next: string;
}
export interface ScorecardData {
  day: string;
  criteria: Criterion[];
  tasks: { key: string; title: string; area: string; level: number; target: number; minutes: number }[];
  levels: Record<string, string>;
  capabilities: { title: string; group: "tab" | "inner"; enabled: boolean; used: boolean; automated: boolean }[];
  compliance: { title: string; ok: boolean }[];
}
export interface Scorecard {
  current: ScorecardData;
  baseline: ScorecardData | null;
  series: { day: string; values: Record<string, number | null> }[];
}

export interface WeeklyStage {
  proposals?: number; eligible?: number; held?: number; approved?: number;
  applied?: number; failed?: number; ok?: boolean; anomaly?: string;
  /** الدورة للمراجعة فقط: لم يُعتمد شيء آليًا */
  review_only?: boolean;
  /** الحد: عدد حصص الصف في النافذة */
  limit?: number;
  /** مرحلة حزمة التحضير: الأسبوع ومجلده أو سبب تعذّرها */
  week?: number;
  folder?: string;
  error?: string;
}
export interface WeeklyReport {
  /** الملخص ثابت أعلى «اليوم» حتى يقرأه المعلم */
  read_at?: string;
  today?: string;
  horizon?: string;
  attention?: number;
  classes?: Record<string, Record<string, WeeklyStage & { missing_past?: number[]; missing_today?: number[] }>>;
}
export interface WeeklyState {
  enabled: boolean;
  /** false = للمراجعة فقط: تقترح وتتحقق ولا يُعتمد شيء إلا بموافقة المعلم */
  auto_approve: boolean;
  next_at: string;
  due: string | null;
  cycle: string;
  last: Job | null;
}

/**
 * تبويب «الاستهلاك»: استهلاك Claude من قاعدة البيانات (neo/services/usage.py)، بكياناتها المطبَّعة:
 * مشروع ← جلسة ← خطوة ← نموذج وأدوات. العامل يستورد سجلات مجلد Claude كل 10 دقائق.
 */
export interface UsageSum {
  /** بوحدة «رمز إدخال عادي»: قراءة السياق ×0.1، وحفظه ×2، والمخرجات ×5 */
  effective: number;
  tokens: number;
  input: number;
  cache_read: number;
  cache_write: number;
  output: number;
  turns: number;
  sessions: number;
}
export type UsagePeriod = "session" | "today" | "week" | "month";
export interface Usage {
  today: string;
  week_start: string;
  month_start: string;
  session: string | null;
  weights: { cache_read: number; cache_write: number; output: number };
  sources: { path: string; found: boolean; files: number }[];
  /** نتيجة الاستيراد عند «حدّث الآن» (POST)؛ null في القراءة العادية. pending = بقي ما يُستأنف */
  imported: { files: number; new: number; pending: boolean } | null;
  imported_at: string | null;
  /** أول خطوة مستوردة؛ null = لا سجلات بعد */
  first: string | null;
  totals: Record<UsagePeriod, UsageSum>;
  models: Record<UsagePeriod, UsageByModel[]>;
  groups: Record<UsagePeriod, UsageByGroup[]>;
  /** عائلات النماذج (Fable ظاهر دائمًا ولو صفرًا) */
  families: Record<UsagePeriod, UsageByFamily[]>;
  /** المشاريع في آخر 30 يومًا */
  projects: UsageByProject[];
  daily: UsageDay[];
  sessions: UsageSessionRow[];
}
export interface UsageByModel extends UsageSum { model: string }
export interface UsageByFamily { family: string; effective: number; tokens: number; turns: number; models: string[] }
export interface UsageByGroup { name: string; effective: number }
export interface UsageByProject { project: string; effective: number; turns: number }
export interface UsageDay { day: string; effective: number; tokens: number; turns: number }
export interface UsageSessionRow extends UsageSum { session: string; project: string; first: string; last: string; models: string[] }

/** تقرير مهمة usage_verify: عدّ مستقل لملفات السجل مقارنًا بقاعدة البيانات (neo/services/usage_verify.py) */
export interface UsageCheckFields { input: number; cache_read: number; cache_write: number; output: number; turns: number }
export interface UsageVerify {
  ok: boolean;
  checked_at: string;
  roots: { path: string; found: boolean }[];
  files: number;
  lines: number;
  messages: number;
  dup_lines: number;
  dup_differ: number;
  synthetic: number;
  bad_json: number;
  windows: Record<"week" | "month", {
    since: string; files: UsageCheckFields; db: UsageCheckFields; diff: UsageCheckFields;
    model_diff: Record<string, number>; match: boolean; output_if_max: number;
  }>;
}

/** تبويب «مباشر»: البث الحي من العامل */
export type LiveKind = "start" | "stage" | "step" | "net" | "file" | "warn" | "error" | "end";

export interface LiveEvent {
  seq: number;
  at: string;
  t: number;
  kind: LiveKind;
  text: string;
  stage: string;
  current?: number;
  total?: number;
  status?: number | string;
  ms?: number;
  size?: number;
  cached?: boolean;
  lesson?: number;
  path?: string;
  retry?: number;
  op?: "download" | "cache" | "edit";
  /** عقدة رسم الأتمتة التي يجري فيها الحدث (utils/automation: NodeKey) */
  node?: string;
  /** طريقة الطلب حين لا تكون GET (كتابة على المنصة) */
  method?: string;
}

export interface LiveJob {
  id: number;
  kind: JobKind;
  kind_label: string;
  target: string;
  status: JobStatus;
  status_label: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string;
  error_label: string;
  seconds: number | null;
}

export interface LiveSummary {
  counts: Partial<Record<LiveKind, number>>;
  ops: Partial<Record<"download" | "cache" | "edit", number>>;
  stages: { text: string; t: number; node?: string }[];
  /** العقد التي مرت بها المهمة بترتيبها */
  nodes?: string[];
  progress: { text: string; current: number; total: number; stage: string } | null;
  end: { status: string; text: string; t: number } | null;
  last_seq: number;
  t: number;
}

export interface LiveFeed {
  now: string;
  worker: { alive: boolean; pid: number | null; seen_at: string | null };
  session: SessionState;
  job: (LiveJob & { live: LiveSummary }) | null;
  events: LiveEvent[];
  queue: LiveJob[];
  recent: LiveJob[];
  weekly: { enabled: boolean; auto_approve: boolean; next_at: string };
}
