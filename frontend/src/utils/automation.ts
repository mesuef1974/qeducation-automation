import type { JobKind } from "@/api/types";

/**
 * نموذج رسم الأتمتة المشترك بين صفحتي «الأتمتة» و«مباشر»: العقد ومواضعها، وأنواع العمليات (SyncRun) لكل عقدة،
 * والعقدة الافتراضية لكل نوع مهمة. مفاتيح العقد هي نفسها حقل node في البث الحي (neo/services/live.py: NODES).
 */
export type NodeKey = "platform" | "fetch" | "audit" | "plan" | "approve" | "apply" | "verify" | "scorecard" | "prep";

export interface NodeSpec {
  key: NodeKey;
  title: string;
  sub: string;
  /** أنواع العمليات التي تعرض العقدة آخرها */
  kinds: string[];
  x: number;
  y: number;
  human?: boolean;
}

export const NODES: NodeSpec[] = [
  { key: "platform", title: "منصة قطر للتعليم", sub: "LMS · الصفان 10/3 و12/2", kinds: [], x: 816, y: 60 },
  { key: "fetch", title: "مزامنة", sub: "قراءة الدروس والتقييمات", kinds: ["fetch"], x: 612, y: 60 },
  { key: "audit", title: "تدقيق الجودة", sub: "صورة، وصف، أقسام، تقييم، نتاج", kinds: ["audit"], x: 408, y: 60 },
  { key: "plan", title: "اقتراح", sub: "تواريخ، إسناد، نشر، محتوى", kinds: ["plan", "assign_plan", "publish_plan", "content_plan"], x: 204, y: 60 },
  { key: "approve", title: "اعتماد المعلم", sub: "البوابة البشرية: كل كتابة بقرارك", kinds: [], x: 204, y: 250, human: true },
  { key: "apply", title: "تطبيق", sub: "إضافة فقط · آمن التكرار", kinds: ["apply", "assign_apply", "publish_apply", "content_apply"], x: 408, y: 250 },
  { key: "verify", title: "تحقق", sub: "منظور الطالب وتدقيق بعدي", kinds: ["verify", "audit"], x: 612, y: 250 },
  { key: "scorecard", title: "بطاقة الأداء", sub: "8 معايير · لقطة يومية", kinds: [], x: 816, y: 250 },
  { key: "prep", title: "حزمة التحضير", sub: "سطح المكتب · قراءة فقط", kinds: ["prep"], x: 16, y: 60 },
];

/** عقدة المهمة قبل أن تعلن مرحلتها (وللمهام القديمة التي سبق بثُّها حقلَ node) */
export const KIND_NODE: Record<JobKind, NodeKey> = {
  login: "platform", sync_plan: "fetch", sync_apply: "apply", assign_plan: "fetch", assign_apply: "apply",
  publish_plan: "fetch", publish_apply: "apply", verify: "verify", weekly: "fetch", audit: "audit",
  content_plan: "plan", content_apply: "apply", prep_pack: "prep", session: "platform", usage_verify: "scorecard",
};

export const isNode = (k: unknown): k is NodeKey => typeof k === "string" && NODES.some((n) => n.key === k);

/** ما يُكتب تحت عنوان العقدة: آخر عملية لها أو حالتها الآن */
export interface NodeNote {
  note: string;
  /** تاريخ آخر عملية ووقتها، في سطر مستقل تحت الملاحظة */
  when?: string;
  ok: boolean | null;
}

/**
 * إشارة تتحرك في الرسم: read = صفحة قُرئت من المنصة (تسري من المنصة إلى العقدة)،
 * write = طلب كتابة من التطبيق (يسري من التطبيق إلى المنصة)، file = ملف نُزّل أو عُدّل (وميض على العقدة).
 */
export interface Signal {
  id: number;
  node: NodeKey;
  kind: "read" | "write" | "file";
  /** تأخير البدء بالملّي ثانية، لتتتابع إشارات الدفعة الواحدة ولا تتراكب */
  delay: number;
}
