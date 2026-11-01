// @vitest-environment jsdom

/**
 * Which of the server's messages the cashier reads (`D-270`).
 *
 * A refund refused because a gift card paid the bill came back as «Payment
 * methods refreshed» — ERPNext's own note, printed before our refusal and
 * picked because it was first.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { onPapers, query, readError, setTillName } from "@/api/client";

function messages(...rows: Record<string, unknown>[]): { _server_messages: string } {
  return { _server_messages: JSON.stringify(rows.map((row) => JSON.stringify(row))) };
}

describe("reading a refusal", () => {
  it("reads the refusal, not a note printed before it", () => {
    const error = readError(
      messages(
        { message: "Payment methods refreshed. Please review before proceeding.", alert: 1 },
        { message: "The gift card paid 53.00 of this bill.", raise_exception: 1 },
      ),
      417,
    );

    expect(error.message).toBe("The gift card paid 53.00 of this bill.");
  });

  it("reads the last message that is not an alert when none is marked", () => {
    const error = readError(messages({ message: "note", alert: 1 }, { message: "the reason" }), 417);

    expect(error.message).toBe("the reason");
  });

  it("still reads a single message", () => {
    expect(readError(messages({ message: "only one" }), 417).message).toBe("only one");
  });
});

/**
 * `D-415` — paper beside any answer reaches the till's printing, and only then.
 */
describe("paper beside an answer", () => {
  afterEach(() => {
    setTillName(null);
    onPapers(null);
    vi.unstubAllGlobals();
  });

  function server(status: number, body: unknown) {
    return vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body });
  }

  it("names the till on every request once it prints direct", async () => {
    const fetched = server(200, { message: 1 });
    vi.stubGlobal("fetch", fetched);
    setTillName("كاشير 2");

    await query("anything");

    expect(fetched.mock.calls[0][1].headers["X-RPOS-Till"]).toBe(encodeURIComponent("كاشير 2"));
  });

  it("sends no name from a till printing through the server", async () => {
    const fetched = server(200, { message: 1 });
    vi.stubGlobal("fetch", fetched);

    await query("anything");

    expect(fetched.mock.calls[0][1].headers).not.toHaveProperty("X-RPOS-Till");
  });

  it("passes the paper on, and still answers with the message", async () => {
    const taken = vi.fn();
    onPapers(taken);
    vi.stubGlobal("fetch", server(200, { message: { paid: true }, rpos_papers: [{ job: "J" }] }));

    await expect(query("anything")).resolves.toEqual({ paid: true });
    expect(taken).toHaveBeenCalledWith([{ job: "J" }]);
  });

  it("takes no paper from a refused request: it was rolled back with it", async () => {
    const taken = vi.fn();
    onPapers(taken);
    vi.stubGlobal("fetch", server(417, { exception: "x", rpos_papers: [{ job: "J" }] }));

    await expect(query("anything")).rejects.toThrow();
    expect(taken).not.toHaveBeenCalled();
  });
});
