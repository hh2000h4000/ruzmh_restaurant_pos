// @vitest-environment jsdom

/**
 * Coming back online has to replace the copy, not just the banner (`D-230`).
 *
 * A till that starts while the server is unreachable sells from the cached
 * terminal configuration (09 §3). Nothing used to replace that copy once the
 * server came back: the cache stayed in hand for the rest of the shift.
 *
 * The user met it as **every tile reading "no price"** while the bill above
 * them priced correctly — the cached menu predated a price list their order
 * type had been given, and signing out and in did not help, because none of
 * that re-fetches the terminal.
 */
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useConnectionStore } from "@/stores/connection";
import { useSessionStore } from "@/stores/session";

const ping = vi.fn();
vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return { ...actual, ping: () => ping() };
});

vi.mock("@/offline/queue", () => ({
  flush: vi.fn().mockResolvedValue(undefined),
  pendingCount: vi.fn().mockResolvedValue(0),
  failedCount: vi.fn().mockResolvedValue(0),
}));

describe("a till that has been running on its cached terminal", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    localStorage.setItem("rpos.pos_profile", "T1");
    localStorage.setItem("rpos.device_token", "tok");
    ping.mockReset();
  });

  it("fetches the terminal again the moment the server answers", async () => {
    const session = useSessionStore();
    session.cachedAt = "2026-09-18 21:00:00";
    const load = vi.spyOn(session, "load").mockResolvedValue(undefined);

    const connection = useConnectionStore();
    ping.mockRejectedValueOnce(new Error("down"));
    await connection.probe();
    expect(connection.state).toBe("offline");

    ping.mockResolvedValueOnce({ status: "ok", timestamp: "" });
    await connection.probe();

    expect(connection.state).toBe("online");
    expect(load).toHaveBeenCalledWith("T1", "tok");
  });

  it("leaves a terminal loaded from the server alone", async () => {
    const session = useSessionStore();
    session.cachedAt = null;
    const load = vi.spyOn(session, "load").mockResolvedValue(undefined);

    const connection = useConnectionStore();
    ping.mockRejectedValueOnce(new Error("down"));
    await connection.probe();
    ping.mockResolvedValueOnce({ status: "ok", timestamp: "" });
    await connection.probe();

    expect(load).not.toHaveBeenCalled();
  });
});
