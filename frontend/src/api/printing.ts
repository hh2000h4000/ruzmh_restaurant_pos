/**
 * Paper, asked for a second time (`FR-7.5`, `D-143`).
 *
 * One call for a sale and for a refund, because it is one question: put this
 * invoice on the cashier's printer again. Nothing is created — the reprint
 * renders the document that exists, so what comes out is what was issued.
 */
import { command, mutate } from "./client";

/**
 * The print agent, set up from the till in one step (`D-424`).
 *
 * Either a ticket for the file — named with this page's address and the
 * agent's code, so it pairs itself — or the computer the terminal's agent is
 * on already, to ask about before taking it from there.
 */
export interface AgentInstall {
  ticket?: string;
  filename?: string;
  needs_move?: string;
}

export function installAgent(posProfile: string, move = false): Promise<AgentInstall> {
  return command("printing.install_agent", { pos_profile: posProfile, move: move ? 1 : 0 });
}

/** The file itself, downloaded by the browser as it downloads anything. */
export function agentFileUrl(ticket: string): string {
  return `/api/method/restaurant_pos.api.printing.agent_file?ticket=${encodeURIComponent(ticket)}`;
}

export function reprintReceipt(invoiceName: string): Promise<{
  invoice: string;
  order_name: string;
  queued: boolean;
}> {
  return mutate("printing.reprint_receipt", { invoice_name: invoiceName });
}
