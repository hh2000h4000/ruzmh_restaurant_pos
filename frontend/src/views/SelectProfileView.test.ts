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
import { t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import SelectProfileView from "@/views/SelectProfileView.vue";

const push = vi.fn();

vi.mock("vue-router", () => ({
  useRouter: () => ({ push, currentRoute: { value: { query: {} } } }),
}));

const command = vi.fn();
vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return { ...actual, command: (...args: unknown[]) => command(...args) };
});

function screen() {
  return mount(SelectProfileView, { global: { stubs: { LocaleToggle: true } } });
}

describe("pairing this machine", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    command.mockReset();
    push.mockReset();
  });

  it("keeps the token so the next load does not ask again", async () => {
    command.mockResolvedValueOnce({ pos_profile: "T1", device_token: "tok-1" });
    const session = useSessionStore();
    vi.spyOn(session, "load").mockImplementation(async () => {
      session.data = { pos_profile: { name: "T1" } } as never;
    });

    const view = screen();
    await flushPromises();
    await view.find("input").setValue("1234-5678");
    await view.find("form").trigger("submit");
    await flushPromises();

    // A POST: Frappe discards what a GET writes, so pairing over one handed
    // back a token the server had already rolled away.
    expect(command).toHaveBeenCalledWith("session.pair_device", { code: "1234-5678" });
    expect(pairedDevice()).toEqual({ posProfile: "T1", token: "tok-1" });
    expect(session.load).toHaveBeenCalledWith("T1", "tok-1");
    expect(push).toHaveBeenCalled();
  });

  it("does not ask a paired till for a code while it opens", async () => {
    // `D-272` — every load passes through here; the pairing prompt showed on each.
    localStorage.setItem("rpos.pos_profile", "T1");
    localStorage.setItem("rpos.device_token", "tok-1");
    const session = useSessionStore();
    vi.spyOn(session, "load").mockImplementation(() => new Promise(() => {}));

    const view = screen();
    await flushPromises();

    expect(view.text()).toContain(t("common.loading"));
    expect(view.text()).not.toContain(t("setup.hint"));
    expect(view.find("form").exists()).toBe(false);
  });

  it("says what the server said, not a guess at it", async () => {
    command.mockRejectedValueOnce(new ApiError("Not permitted", 403, "PermissionError"));

    const view = screen();
    await flushPromises();
    await view.find("input").setValue("1111-2222");
    await view.find("form").trigger("submit");
    await flushPromises();

    expect(view.find('[role="alert"]').text()).toBe("Not permitted");
  });

  it("forgets a pairing the server refuses by name", async () => {
    localStorage.setItem("rpos.pos_profile", "T1");
    localStorage.setItem("rpos.device_token", "stale");
    const session = useSessionStore();
    // 401: the terminal is paired with another machine, or with none.
    vi.spyOn(session, "load").mockRejectedValue(new ApiError("paired elsewhere", 401));

    const view = screen();
    await flushPromises();

    expect(pairedDevice()).toBeNull();
    expect(view.find("form").exists()).toBe(true);
  });

  it("sends a paired till to the PIN pad when nobody is signed in", async () => {
    // The ordinary state right after pairing: the machine is known, the person
    // is not. The terminal payload carries permissions, so it needs a person.
    localStorage.setItem("rpos.pos_profile", "T1");
    localStorage.setItem("rpos.device_token", "good");
    const session = useSessionStore();
    vi.spyOn(session, "load").mockRejectedValue(new ApiError("Login to access", 403, "PermissionError"));

    screen();
    await flushPromises();

    expect(push).toHaveBeenCalledWith({ name: "sign-in" });
    expect(pairedDevice()).toEqual({ posProfile: "T1", token: "good" });
  });
});
