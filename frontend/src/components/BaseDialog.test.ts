// @vitest-environment jsdom

/**
 * Getting out of a dialog (`D-138`).
 *
 * Vue casts an **absent** Boolean prop to `false`, so `dismissible?: boolean`
 * meant that every dialog which did not think to pass it was sealed: no
 * Escape, no backdrop, and a way out only where somebody had drawn a button.
 * Seven were like that, the tender sheet among them, and the roster screen had
 * no button at all — the user found it by being unable to leave.
 *
 * The prop reads like an opt-out and now behaves like one. These are here
 * because the trap is invisible: the code looked correct in every one of those
 * seven files.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import BaseDialog from "@/components/BaseDialog.vue";

function open(props: Record<string, unknown> = {}) {
  return mount(BaseDialog, {
    props: { open: true, title: "طلب", ...props },
    global: { stubs: { teleport: true } },
  });
}

describe("leaving a dialog", () => {
  it("closes on the backdrop when nothing says otherwise", async () => {
    const wrapper = open();

    await wrapper.find('[role="dialog"]').element.parentElement!.dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );

    expect(wrapper.emitted("close")).toBeTruthy();
  });

  it("closes on Escape when nothing says otherwise", async () => {
    const wrapper = open();

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));

    expect(wrapper.emitted("close")).toBeTruthy();
  });

  it("stays put for a dialog that must be answered", async () => {
    const wrapper = open({ dismissible: false });

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await wrapper.find('[role="dialog"]').element.parentElement!.dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );

    expect(wrapper.emitted("close")).toBeFalsy();
  });

  /**
   * A click that started inside and ended on the backdrop is a drag, not a
   * dismissal — and on a bill panel a cashier drags all the time.
   */
  it("ignores a click that came from inside the panel", async () => {
    const wrapper = open();

    await wrapper.find('[role="dialog"]').trigger("click");

    expect(wrapper.emitted("close")).toBeFalsy();
  });
});
