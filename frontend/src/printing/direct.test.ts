// @vitest-environment jsdom

/**
 * The till hands the server's paper to its agent (`D-415`, `docs/15` §5.3).
 *
 * What the cashier depends on: each printer's papers in order, a dead printer
 * never holding another's, an agent that does not answer said to the server as
 * unconfirmed — and a till printing through the server taking no paper at all.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";

import { configure, handPapers, type Paper } from "./direct";

vi.mock("@/api/client", () => ({
  command: vi.fn().mockResolvedValue({ ok: true }),
  onPapers: vi.fn(),
  setTillName: vi.fn(),
}));

const DIRECT = { direct: true, agent_url: "http://127.0.0.1:17891/", token: "k".repeat(43), ink_threshold: 170, band_rows: 128 };

function paper(job: string, printer = "PRT-1"): Paper {
  return { job, printer: { name: printer, title: printer }, copies: 1, raw: "G0A=" };
}

function answered(status = 200) {
  return { ok: status < 400, status, json: async () => ({ ok: status < 400, status: "printed" }) };
}

beforeEach(() => {
  vi.clearAllMocks();
  configure("كاشير 2", DIRECT);
});

afterEach(() => vi.unstubAllGlobals());

describe("a direct till", () => {
  it("names itself on every request and takes the paper that comes back", () => {
    expect(client.setTillName).toHaveBeenLastCalledWith("كاشير 2");
    expect(client.onPapers).toHaveBeenLastCalledWith(handPapers);
  });

  it("hands each paper to its agent with the key", async () => {
    const fetched = vi.fn().mockResolvedValue(answered());
    vi.stubGlobal("fetch", fetched);

    await handPapers([paper("JOB-1")]);

    const [url, init] = fetched.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:17891/print");
    expect(init.headers["X-RPOS-Token"]).toBe(DIRECT.token);
    expect(JSON.parse(init.body)).toMatchObject({ job: "JOB-1", payload: "G0A=", copies: 1 });
    expect(client.command).not.toHaveBeenCalled();
  });

  it("says unconfirmed when the agent does not answer", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await handPapers([paper("JOB-2")]);

    expect(client.command).toHaveBeenCalledWith("printing.not_handed", {
      job: "JOB-2",
      error: "TypeError: Failed to fetch",
    });
  });

  it("says unconfirmed when the agent refuses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answered(401)));

    await handPapers([paper("JOB-3")]);

    expect(client.command).toHaveBeenCalledWith("printing.not_handed", { job: "JOB-3", error: "agent answered 401" });
  });

  it("keeps one printer's papers in order and never holds another printer behind it", async () => {
    const order: string[] = [];
    let releaseKitchen: () => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: { body: string }) => {
        const job = JSON.parse(init.body).job as string;
        order.push(`start ${job}`);
        if (job === "KOT-1") {
          return new Promise((resolve) => {
            releaseKitchen = () => {
              order.push("end KOT-1");
              resolve(answered());
            };
          });
        }
        order.push(`end ${job}`);
        return Promise.resolve(answered());
      }),
    );

    const done = handPapers([paper("KOT-1", "kitchen"), paper("KOT-2", "kitchen"), paper("RCPT-1", "cashier")]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    releaseKitchen();
    await done;

    expect(order.indexOf("end RCPT-1")).toBeLessThan(order.indexOf("end KOT-1"));
    expect(order.indexOf("start KOT-2")).toBeGreaterThan(order.indexOf("end KOT-1"));
  });
});

describe("a till printing through the server", () => {
  it("names nothing and takes no paper", () => {
    configure("كاشير 2", { direct: false });

    expect(client.setTillName).toHaveBeenLastCalledWith(null);
    expect(client.onPapers).toHaveBeenLastCalledWith(null);
  });

  it("is the same before its agent has a key", () => {
    configure("كاشير 2", { direct: true, agent_url: "http://127.0.0.1:17891" });

    expect(client.setTillName).toHaveBeenLastCalledWith(null);
  });
});
