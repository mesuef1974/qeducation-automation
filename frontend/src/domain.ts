import type { JobKind, ProposalKind } from "@/api/types";

// المراحل التي لها مراجعة: نوع الاقتراح ← مهمة الجلب والاقتراح، ومهمة التطبيق
export interface Stage {
  kind: ProposalKind;
  label: string;
  plan: JobKind;
  apply: JobKind;
  /** يقبل التطبيق التجريبي على أول عنصر (limit) */
  trial: boolean;
  /** ما يحدث بعد التطبيق، يُعرض في تأكيد الكتابة */
  after?: string;
}

export const STAGES: Stage[] = [
  { kind: "date", label: "التواريخ", plan: "sync_plan", apply: "sync_apply", trial: false },
  { kind: "assign", label: "الإسناد", plan: "assign_plan", apply: "assign_apply", trial: true },
  { kind: "publish", label: "النشر والنقاط", plan: "publish_plan", apply: "publish_apply", trial: true,
    after: "ثم يتحقق تلقائيًا مما يراه الطالب." },
];

export const stageOf = (kind: ProposalKind): Stage => STAGES.find((s) => s.kind === kind)!;

// لون الشارة لكل حالة (pages.css: ok | warn | bad | info | read | prep)
export const TONE: Record<string, string> = {
  pending: "warn", approved: "info", rejected: "prep", applied: "ok", skipped: "prep", failed: "bad",
  queued: "warn", running: "read", done: "ok",
};

export const todayIso = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
