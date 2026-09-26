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

import { locale, t } from "@/i18n";

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

function setCsrfToken(value: string): void {
  (window as unknown as { csrf_token?: string }).csrf_token = value;
}

/**
 * Make sure this page can write, fetching the token if it has none.
 *
 * Frappe rejects a write without a CSRF token with a bare 400, which looks
 * identical to a malformed request while every GET keeps working — the app
 * appears half-broken with nothing in the console to explain it. It has cost
 * two separate rounds of debugging (D-030, D-031).
 *
 * The token is injected into the page by Jinja (`frontend/vite.config.ts`),
 * and that covers every load except one: HTML the *browser* kept from a visit
 * made while nobody was signed in comes back with an empty token. So when it
 * is missing, ask the server.
 *
 * **A guest is allowed through without one** (`D-102`). `session.csrf_token`
 * needs a session and answers 403 without one — which was the honest answer
 * while Frappe owned the login screen, and became a deadlock the moment this
 * app grew its own: signing in is a POST, made by somebody with no session, so
 * the one call that could produce a session was the one call this refused to
 * let through. Frappe does not ask a Guest for a CSRF token, so there is
 * nothing to send and nothing to fail.
 */
async function ensureCsrfToken(): Promise<void> {
  if (csrfToken()) return;

  let fresh: { csrf_token?: string } | null = null;
  try {
    fresh = await query<{ csrf_token: string }>("session.csrf_token");
  } catch (cause) {
    // Not signed in: the write about to happen is either the sign-in itself,
    // which needs no token, or one that will be refused on its own merits.
    if (cause instanceof ApiError && (cause.status === 403 || cause.status === 401)) return;
    throw cause;
  }

  if (!fresh?.csrf_token) {
    throw new ApiError(t("err.noCsrf"), 0, "CSRFTokenMissing");
  }

  setCsrfToken(fresh.csrf_token);
}

/**
 * Forget the token, so the next write fetches one for the session in hand.
 *
 * Signing in **replaces the session**, and a token minted for the previous one
 * is refused with a bare 400 — the failure this whole dance exists to avoid,
 * arriving one step later.
 */
export function resetCsrfToken(): void {
  setCsrfToken("");
}

/**
 * Frappe returns `{"message": ...}` on success and messages in a few shapes on failure.
 *
 * **The refusal, not the first thing said.** `_server_messages` is every
 * `msgprint` of the request, in order, and ERPNext prints its own notes on the
 * way — building a credit note announces «Payment methods refreshed» — before
 * our `frappe.throw` is reached. Taking the first one showed a refund refused
 * for a reason the cashier could not see (`D-270`). The message Frappe marks
 * `raise_exception` is the refusal; failing that, the last one that is not a
 * passing alert.
 */
export function readError(payload: unknown, status: number): ApiError {
  const body = payload as {
    exc_type?: string;
    exception?: string;
    _server_messages?: string;
    message?: string;
  } | null;

  let message = body?.message ?? "";

  if (body?._server_messages) {
    try {
      const said = (JSON.parse(body._server_messages) as string[]).map(
        (row) => JSON.parse(row) as { message?: string; raise_exception?: number; alert?: number },
      );
      const latest = [...said].reverse();
      const refusal =
        latest.find((row) => row.raise_exception) ?? latest.find((row) => !row.alert) ?? latest[0];
      message = refusal?.message ?? message;
    } catch {
      // Leave whatever we already have.
    }
  }

  if (!message) {
    message = status === 0 ? t("err.offline") : t("err.failed", { status });
  }

  return new ApiError(stripHtml(message), status, body?.exception ?? body?.exc_type ?? "");
}

function stripHtml(value: string): string {
  return value.replace(/<[^>]*>/g, "").trim();
}

/**
 * Ask the server to answer in the language on the screen (`D-104`, `FR-17`).
 *
 * `frappe.throw` messages are translated with the *user's* language, which is a
 * setting on their ERPNext account and has nothing to do with the toggle the
 * cashier just used. A till showing Arabic was refusing an order in English.
 *
 * `_lang` is the first thing Frappe's `get_language` looks at, ahead of the
 * user document, so this is the supported way to say it per request rather
 * than per account.
 */
function withLanguage(body: unknown): unknown {
  if (body === undefined) return { _lang: locale.value };
  if (body === null || typeof body !== "object") return body;

  return { ...(body as Record<string, unknown>), _lang: locale.value };
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (method !== "GET") await ensureCsrfToken();

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
      body: method === "GET" ? undefined : JSON.stringify(withLanguage(body)),
    });
  } catch (cause) {
    // Network failure, not an application error. The caller decides whether to
    // queue it (09 §5).
    throw new ApiError(t("err.offline"), 0, String(cause));
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

  // A GET has no body to carry it in (`D-104`).
  search.set("_lang", locale.value);

  return request<T>("GET", `${path}?${search.toString()}`);
}

/**
 * A POST that is not a business write: no `queue_id`, nothing to replay.
 *
 * Used for anything that must not travel in a URL — a manager PIN in a query
 * string would be copied into the web server's access log and the browser's
 * history, where it outlives the sixty-second approval it bought.
 */
export function command<T>(path: string, payload: Record<string, unknown> = {}): Promise<T> {
  return request<T>("POST", path, payload);
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

/**
 * Send a write under a `queue_id` the caller chose.
 *
 * Used by the offline queue: replaying with the original id is what makes it
 * safe, because if the first attempt did reach the server after all, the
 * backend returns that first result instead of acting twice (09 §8).
 */
export function sendQueued<T>(
  path: string,
  payload: Record<string, unknown>,
  queueId: string,
): Promise<T> {
  return request<T>("POST", path, { ...payload, queue_id: queueId });
}

export function ping(): Promise<{ status: string; timestamp: string }> {
  return query("session.ping");
}
