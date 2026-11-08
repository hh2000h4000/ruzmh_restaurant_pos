/**
 * Paper the server handed back, taken straight to this till's print agent (`D-415`, `docs/15` §5.3).
 *
 * The server puts it beside the answer to whatever action made it — a payment,
 * a kitchen send, a reprint — as `rpos_papers`; the API client passes it here.
 * The till draws it (`raster.ts`) and posts it to its agent on `127.0.0.1`, or
 * to the computer that prints for this phone or tablet.
 *
 * **What the cashier is told is the server's to say.** The agent reports each
 * paper to the server itself, and a kitchen ticket that did not print rings the
 * bell from there (`D-413`). When the agent does not answer at all, this says
 * so to the server — unconfirmed, never printed again (`D-405`). Only when the
 * agent says **nothing left it** does the paper go on, to its backup (`D-417`).
 */
import { ref } from "vue";

import { command, onPapers, query, setTillName } from "@/api/client";
import { pairedDevice } from "@/device";

import { drawHtml, packRaster, toBase64, type Ink } from "./raster";

/** One paper, as `printing._hand_to_till` puts it in a response. */
export interface Paper {
  job: string;
  printer: { name: string; title: string } & Record<string, unknown>;
  copies: number;
  /** Drawn here. */
  html?: string;
  width?: number;
  cut?: boolean;
  /** Bytes already made — a drawer kick. */
  raw?: string;
  /**
   * The backup printer, when this till's agent reaches it (`D-417`): where the
   * same paper goes if the agent says nothing left it. The server makes the
   * row under `job` from the agent's own report, so this asks the server nothing.
   */
  fallback?: { job: string; printer: Paper["printer"]; width: number; cut: boolean };
}

/** The session's `printing` block. */
export interface TillPrinting {
  direct: boolean;
  agent_url?: string;
  token?: string;
  ink_threshold?: number;
  band_rows?: number;
}

/**
 * How long a paper may take, from handing it over to the agent's answer —
 * longer than the agent's slowest known answer (`docs/15` §5.3). Past it the
 * paper may still print; it is unconfirmed, and the agent's own report settles it.
 */
export const HAND_OVER_MS = 20_000;

/** How long the opening check waits for the agent; the browser's own prompt may hold it. */
export const REACH_MS = 10_000;

let till: { name: string; agentUrl: string; token: string; ink: Ink } | null = null;

/**
 * The browser refuses this page its print agent (`D-420`, `docs/15` §5.10).
 *
 * A setting on this machine, not a fault: said on the screen, with how to
 * change it, until it is changed. Nothing goes to the server instead — the
 * person who set the till up fixes it once, as Odoo asks of its users.
 */
export const blockedByBrowser = ref(false);

let watching: PermissionStatus | null = null;

/**
 * Set from the session: a direct till names itself on every request and takes
 * the paper that comes back; any other till does neither, and the server draws.
 */
export function configure(name: string | null, printing: TillPrinting | null | undefined): void {
  const direct = Boolean(name && printing?.direct && printing.agent_url && printing.token);
  till = direct
    ? {
        name: name!,
        agentUrl: printing!.agent_url!.replace(/\/$/, ""),
        token: printing!.token!,
        ink: { threshold: printing!.ink_threshold ?? 170, bandRows: printing!.band_rows ?? 128 },
      }
    : null;
  setTillName(direct ? name : null);
  onPapers(direct ? handPapers : null);
  if (!till) {
    blockedByBrowser.value = false;
    watching = null;
  }
}

/**
 * When the till opens, and again when the browser's answer changes: can this
 * page reach its agent? Asked of the agent itself — the browser's answer alone
 * is not trusted, since a browser that cannot show its prompt says "denied" to
 * a page that prints. Blocked only when the agent was not reached **and** the
 * browser says it refused. Asking also brings the browser's prompt up now,
 * not in the middle of the first sale.
 */
export async function checkReach(): Promise<void> {
  if (!till) return;
  const status = await localNetworkPermission(till.agentUrl);
  if (status && !watching) {
    watching = status;
    status.onchange = () => void checkReach();
  }
  const reached = await reachesAgent();
  blockedByBrowser.value = !reached && status?.state === "denied";
}

async function reachesAgent(): Promise<boolean> {
  if (!till) return false;
  const url = `${till.agentUrl}/health`;
  try {
    // Any answer, a refusal included, is an agent this page reached.
    await fetch(url, {
      headers: { "X-RPOS-Token": till.token },
      signal: AbortSignal.timeout(REACH_MS),
      ...addressSpace(url),
    } as RequestInit);
    return true;
  } catch {
    return false;
  }
}

/** The browser's permission for this agent, by the names Chrome has used; null where it has none. */
async function localNetworkPermission(url: string): Promise<PermissionStatus | null> {
  const names = isLoopback(url)
    ? ["loopback-network", "local-network-access"]
    : ["local-network", "local-network-access"];
  for (const name of names) {
    try {
      return await navigator.permissions.query({ name } as unknown as PermissionDescriptor);
    } catch {
      // Not a name this browser knows: an older one has no such permission at all.
    }
  }
  return null;
}

/**
 * Hand every paper to the agent: each printer's papers in the order they came,
 * different printers side by side — so a dead kitchen printer never holds the
 * receipt (`D-411`).
 */
export async function handPapers(papers: Paper[]): Promise<void> {
  const lines = new Map<string, Paper[]>();
  for (const paper of papers) {
    const key = paper.printer.name ?? paper.printer.title;
    lines.set(key, [...(lines.get(key) ?? []), paper]);
  }
  await Promise.all(
    [...lines.values()].map(async (line) => {
      for (const paper of line) await handOver(paper);
    }),
  );
}

/** The one key request in flight, shared by every paper the old key had refused. */
let renewing: Promise<string | null> | null = null;

/**
 * The agent's current key, after it refused ``sent`` (`D-425`).
 *
 * The key changes when the agent is paired again, and this till loaded before.
 * Asked once however many papers were refused together, and not at all when
 * another paper has already brought the new one. Null when there is none to
 * be had — the server unreachable, or the same key again.
 */
async function freshToken(sent: string): Promise<string | null> {
  if (!till) return null;
  if (till.token !== sent) return till.token;
  renewing ??= query<TillPrinting>("session.till_printing", {
    pos_profile: till.name,
    device_token: pairedDevice()?.token ?? "",
  })
    .then((printing) => {
      if (till && printing.direct && printing.token) till.token = printing.token;
      return till?.token ?? null;
    })
    .catch(() => null)
    .finally(() => {
      renewing = null;
    });
  const token = await renewing;
  return token && token !== sent ? token : null;
}

async function handOver(paper: Paper, renewed = false): Promise<void> {
  if (!till) return;
  const { agentUrl, token, ink } = till;
  try {
    const bytes = paper.raw ?? toBase64(packRaster(await drawHtml(paper.html!, paper.width!), ink, Boolean(paper.cut)));
    const url = `${agentUrl}/print`;
    const answer = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-RPOS-Token": token },
      body: JSON.stringify({ job: paper.job, printer: paper.printer, payload: bytes, copies: paper.copies }),
      signal: AbortSignal.timeout(HAND_OVER_MS),
      ...addressSpace(url),
    } as RequestInit);
    // `D-425` — the agent checks the key before anything else, so a refused
    // key printed nothing: the one refusal sent again, once, with the key it
    // holds now. A second refusal is said like any other.
    if (answer.status === 401 && !renewed && (await freshToken(token))) {
      await handOver(paper, true);
      return;
    }
    if (!answer.ok) {
      // Refused — wrong page, wrong key: nothing was printed, but the till
      // cannot know that the agent is not merely confused, so it asks.
      await notHanded(paper, `agent answered ${answer.status}`);
      return;
    }
    // An answer of any status was also reported to the server by the agent.
    const outcome = (await answer.json().catch(() => ({}))) as { status?: string };
    if (outcome.status === "failed" && paper.fallback) {
      // One hop: the backup's own paper names no backup.
      await handOver({ ...paper, ...paper.fallback, fallback: undefined });
    }
  } catch (cause) {
    // No answer, a timeout, or a drawing that failed: "never arrived" and
    // "arrived, answer lost" look the same from here (`docs/15` §5.3).
    await notHanded(paper, cause instanceof Error ? `${cause.name}: ${cause.message}` : String(cause));
  }
}

/**
 * Chrome's local-network rule names the target only for an `https` page
 * (`docs/15` §11): `loopback` for this computer, `local` for another one.
 * Named on a plain-`http` page, it failed outright in Chrome 156.
 */
function addressSpace(url: string): { targetAddressSpace?: "loopback" | "local" } {
  if (location.protocol !== "https:") return {};
  return { targetAddressSpace: isLoopback(url) ? "loopback" : "local" };
}

function isLoopback(url: string): boolean {
  const host = new URL(url).hostname;
  return host === "127.0.0.1" || host === "localhost";
}

async function notHanded(paper: Paper, error: string): Promise<void> {
  try {
    await command("printing.not_handed", { job: paper.job, error: error.slice(0, 400) });
  } catch {
    // The server unreachable as well: in a minute it marks the paper
    // unconfirmed by itself (`printing.sweep_jobs`).
  }
}
