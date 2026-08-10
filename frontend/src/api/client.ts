/**
 * The only place this app talks to Frappe.
 *
 * Components and views never call `fetch` (03_frontend_vue_rules.md). Two
 * things are enforced here rather than left to each call site:
 *
 * 1. **Every mutating call carries a `queue_id`.** `CLAUDE.md` §5.3 requires
 *    it, and a call that forgets one becomes a duplicate order the first time
 *    the network drops mid-request. `mutate()` generates it; there is no way
 *    to send a write without one.
 * 2. **Frappe's error envelope is unwrapped once.** Errors arrive as
 *    `_server_messages` or `exception`; turning that into a readable message
 *    in twenty components would produce twenty different results.
 */

const BASE = "/api/method/restaurant_pos.api";

export class ApiError extends Error {
  readonly status: number;
  readonly exception: string;

  constructor(message: string, status: number, exception = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.exception = exception;
  }

  /** True when the request never reached the server. */
  get isOffline(): boolean {
    return this.status === 0;
  }

  get isPermissionDenied(): boolean {
    return this.status === 403 || this.exception.includes("PermissionError");
  }
}

export function newQueueId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();

  // Older Safari on iPad. Still a v4-shaped random id.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0;
    const value = char === "x" ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

function csrfToken(): string {
  return (window as unknown as { csrf_token?: string }).csrf_token ?? "";
}

/** Frappe returns `{"message": ...}` on success and messages in a few shapes on failure. */
function readError(payload: unknown, status: number): ApiError {
  const body = payload as {
    exc_type?: string;
    exception?: string;
    _server_messages?: string;
    message?: string;
  } | null;

  let message = body?.message ?? "";

  if (body?._server_messages) {
    try {
      const parsed = JSON.parse(body._server_messages) as string[];
      const first = JSON.parse(parsed[0]) as { message?: string };
      message = first.message ?? message;
    } catch {
      // Leave whatever we already have.
    }
  }

  if (!message) {
    message =
      status === 0
        ? "لا يوجد اتصال بالخادم"
        : `تعذّر تنفيذ الطلب (${status})`;
  }

  return new ApiError(stripHtml(message), status, body?.exception ?? body?.exc_type ?? "");
}

function stripHtml(value: string): string {
  return value.replace(/<[^>]*>/g, "").trim();
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${BASE}.${path}`, {
      method,
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Frappe-CSRF-Token": csrfToken(),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    // Network failure, not an application error. The caller decides whether to
    // queue it (09 §5).
    throw new ApiError("لا يوجد اتصال بالخادم", 0, String(cause));
  }

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw readError(payload, response.status);
  }

  return (payload as { message: T }).message;
}

/** A read. Safe to retry, carries no queue id. */
export function query<T>(path: string, params: Record<string, unknown> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    search.set(key, typeof value === "object" ? JSON.stringify(value) : String(value));
  }

  const suffix = search.toString();
  return request<T>("GET", suffix ? `${path}?${suffix}` : path);
}

/**
 * A write. Always carries a `queue_id`, so replaying it is safe (09 §8).
 *
 * Pass an existing `queueId` when re-sending something the offline queue held:
 * reusing the id is what makes the server return the first result instead of
 * acting twice.
 */
export function mutate<T>(
  path: string,
  payload: Record<string, unknown> = {},
  queueId: string = newQueueId(),
): Promise<T> {
  return request<T>("POST", path, { ...payload, queue_id: queueId });
}

export function ping(): Promise<{ status: string; timestamp: string }> {
  return query("session.ping");
}
