import { api } from "./client";
import type {
  Decision, Job, JobKind, JobParams, Lesson, Page, PlatformClass, Proposal, ProposalKind, Run, Scorecard, SessionState, WeeklyState,
} from "./types";

function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const neo = {
  session: () => api.get<SessionState>("neo/session/"),
  classes: () => api.get<PlatformClass[]>("neo/classes/"),
  lessons: (lms: number) => api.get<Lesson[]>(`neo/lessons/${query({ class: lms })}`),
  runs: (p: { class?: number; kind?: string; limit?: number; offset?: number }) =>
    api.get<Page<Run>>(`neo/runs/${query(p)}`),
  proposals: <T extends Proposal>(kind: ProposalKind, p: { class?: number; run?: number; status?: string }) =>
    api.get<T[]>(`neo/proposals/${kind}/${query(p)}`),
  decide: (kind: ProposalKind, ids: number[], decision: Decision) =>
    api.post<{ changed: number }>(`neo/proposals/${kind}/decide/`, { ids, decision }),
  jobs: (p: { status?: string; limit?: number; offset?: number } = {}) => api.get<Page<Job>>(`neo/jobs/${query(p)}`),
  enqueue: (kind: JobKind, params: JobParams = {}) => api.post<Job>("neo/jobs/", { kind, params }),
  scorecard: () => api.get<Scorecard>("neo/scorecard/"),
  weekly: () => api.get<WeeklyState>("neo/weekly/"),
  snapshot: () => api.post<void>("neo/scorecard/"),
  cancel: (id: number) => api.post<Job>(`neo/jobs/${id}/cancel/`),
};
