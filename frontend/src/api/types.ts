// أشكال ردود /api/neo/ كما يعيدها Django (neo/api/serializers.py)

export type ProposalKind = "date" | "assign" | "publish";
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
  overview: Overview;
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
  effective_code: string;
  fetched_at: string;
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
  summary: Record<string, unknown>;
}

interface ProposalBase {
  id: number;
  run: number;
  lms_id: number;
  status: ProposalStatus;
  status_label: string;
  error: string;
  applied_at: string | null;
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

export type Proposal = DateProposal | PublishProposal | AssignProposal;

export type JobKind =
  | "login" | "sync_plan" | "sync_apply" | "assign_plan" | "assign_apply" | "publish_plan" | "publish_apply" | "verify";
export type JobStatus = "queued" | "running" | "done" | "failed";

export interface JobParams {
  classes?: number[];
  run?: number;
  approve?: "all" | "future";
  limit?: number;
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
}
