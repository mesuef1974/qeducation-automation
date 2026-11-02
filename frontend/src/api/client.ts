/**
 * عميل /api: جلسة Django (ملف csrftoken يضبطه /api/neo/session/)، ولا أسرار في التخزين المحلي.
 */
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly body: unknown) {
    super(message);
  }
}

function csrfToken(): string {
  const row = document.cookie.split("; ").find((c) => c.startsWith("csrftoken="));
  return row ? decodeURIComponent(row.slice("csrftoken=".length)) : "";
}

function messageOf(body: unknown, status: number): string {
  if (Array.isArray(body)) return body.join("، ");
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.detail === "string") return b.detail;
    const [field, value] = Object.entries(b)[0] ?? [];
    if (field) return `${field}: ${[value].flat().join("، ")}`;
  }
  return status === 0 ? "تعذّر الاتصال بالخادم المحلي" : `خطأ ${status}`;
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/${path}`, {
      method,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(method === "POST" ? { "Content-Type": "application/json", "X-CSRFToken": csrfToken() } : {}),
      },
      body: method === "POST" ? JSON.stringify(body ?? {}) : undefined,
    });
  } catch {
    throw new ApiError(messageOf(null, 0), 0, null);
  }
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(messageOf(data, res.status), res.status, data);
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
};
