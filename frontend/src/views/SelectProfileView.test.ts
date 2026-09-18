// @vitest-environment jsdom

/**
 * Pairing a till, and what happens when the pairing stops working (`D-226`).
 *
 * The screen has two jobs the server cannot do for it: keep the token where a
 * reload finds it, and throw it away the moment the server stops accepting it —
 * otherwise a till freed by a manager retries a dead token forever and the
 * cashier has no way back to the code box.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { pairedDevice } from "@/device";
import { useSessionStore } from "@/stores/session";
import SelectProfileView from "@/views/SelectProfileView.vue";

const push = vi.fn();

vi.mock("vue-router", () => ({
  useRouter: () => ({ push, currentRoute: { value: { query: {} } } }),
}));

const query = vi.fn();
vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return { ...actual, query: (...args: unknown[]) => query(...args) };
});

function screen() {
  return mount(SelectProfileView, { global: { stubs: { LocaleToggle: true } } });
}

describe("pairing this machine", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    query.mockReset();
    push.mockReset();
  });

  it("keeps the token so the next load does not ask again", async () => {
    query.mockResolvedValueOnce({ pos_profile: "T1", device_token: "tok-1" });
    const session = useSessionStore();
    vi.spyOn(session, "load").mockImplementation(async () => {
      session.data = { pos_profile: { name: "T1" } } as never;
    });

    const view = screen();
    await flushPromises();
    await view.find("input").setValue("1234-5678");
    await view.find("form").trigger("submit");
    await flushPromises();

    expect(query).toHaveBeenCalledWith("session.pair_device", expect.objectContaining({ code: "1234-5678" }));
    expect(pairedDevice()).toEqual({ posProfile: "T1", token: "tok-1" });
    expect(session.load).toHaveBeenCalledWith("T1", "tok-1");
    expect(push).toHaveBeenCalled();
  });

  it("forgets a pairing the server has stopped accepting", async () => {
    localStorage.setItem("rpos.pos_profile", "T1");
    localStorage.setItem("rpos.device_token", "stale");
    const session = useSessionStore();
    vi.spyOn(session, "load").mockRejectedValue(new ApiError("paired elsewhere", 403));

    const view = screen();
    await flushPromises();

    expect(pairedDevice()).toBeNull();
    expect(view.find("form").exists()).toBe(true);
  });
});
