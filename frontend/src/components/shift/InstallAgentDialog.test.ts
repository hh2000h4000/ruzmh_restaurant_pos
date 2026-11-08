// @vitest-environment jsdom

/**
 * The print agent from the till, in one step (`D-424`).
 *
 * What the manager depends on: the file downloads under the name the server
 * gave it — that name is the pairing — and another computer's agent is never
 * taken without asking.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as printing from "@/api/printing";
import InstallAgentDialog from "@/components/shift/InstallAgentDialog.vue";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

const NAME = "RPOS-Print-Agent_https_pos.example.com_443_48217735.exe";

function dialog() {
  useSessionStore().data = { pos_profile: { name: "كاشير 1" } } as unknown as PosSession;
  return mount(InstallAgentDialog, { props: { open: true }, global: { stubs: { teleport: true } } });
}

let clicked: { href: string; download: string }[];

beforeEach(() => {
  setActivePinia(createPinia());
  clicked = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ href: this.href, download: this.download });
  });
});

afterEach(() => vi.restoreAllMocks());

describe("installing the print agent from the till", () => {
  it("downloads the program under the name that pairs it", async () => {
    vi.spyOn(printing, "installAgent").mockResolvedValue({ ticket: "T", filename: NAME });

    dialog();
    await flushPromises();

    expect(printing.installAgent).toHaveBeenCalledWith("كاشير 1", false);
    expect(clicked).toEqual([{ href: expect.stringContaining("agent_file?ticket=T"), download: NAME }]);
  });

  it("asks before taking the agent from another computer, and only moves it when told", async () => {
    const asked = vi
      .spyOn(printing, "installAgent")
      .mockResolvedValueOnce({ needs_move: "POS1" })
      .mockResolvedValue({ ticket: "T", filename: NAME });

    const view = dialog();
    await flushPromises();

    expect(view.text()).toContain("POS1");
    expect(clicked).toEqual([]);

    const buttons = view.findAll("button");
    await buttons[buttons.length - 1].trigger("click");
    await flushPromises();

    expect(asked).toHaveBeenLastCalledWith("كاشير 1", true);
    expect(clicked).toHaveLength(1);
  });

  it("says the server's refusal rather than nothing", async () => {
    vi.spyOn(printing, "installAgent").mockRejectedValue(new Error("Upload the print agent's program first."));

    const view = dialog();
    await flushPromises();

    expect(view.text()).toContain("Upload the print agent's program first.");
    expect(clicked).toEqual([]);
  });
});
