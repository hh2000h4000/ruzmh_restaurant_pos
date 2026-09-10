// @vitest-environment jsdom

/**
 * The rules a popover is dismissed by.
 *
 * The user found this on the order screen: **«عندما أفتح شاشة المزيد وبعدين أنقر
 * أي مكان على الشاشة ما تروح الويندو»** — the sheet opened and never left. These
 * hold the four things that decide whether it does: a tap outside closes it, a
 * tap on the trigger does not (or it would close the tap that opened it),
 * Escape closes it, and the listeners leave with the component.
 *
 * Mounted on a real element rather than called bare, because the whole
 * mechanism is a `document` listener and a `contains` check — asserting on the
 * ref alone would test nothing that ships.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { defineComponent, ref } from "vue";

import { useDismiss } from "@/composables/useDismiss";

const Popover = defineComponent({
  setup() {
    const open = ref(true);
    const anchor = useDismiss(open);
    return { open, anchor };
  },
  template: `
    <div>
      <div ref="anchor">
        <button id="trigger" @click="open = !open">more</button>
        <div v-if="open" id="panel"><button id="entry">entry</button></div>
      </div>
      <button id="outside">something else</button>
    </div>
  `,
});

function popover() {
  return mount(Popover, { attachTo: document.body });
}

describe("useDismiss", () => {
  it("closes when the tap lands outside the anchor", async () => {
    const wrapper = popover();

    document.querySelector<HTMLElement>("#outside")!.click();
    await wrapper.vm.$nextTick();

    expect(wrapper.vm.open).toBe(false);
    expect(wrapper.find("#panel").exists()).toBe(false);
    wrapper.unmount();
  });

  it("leaves the trigger alone, or it would close what it opened", async () => {
    const wrapper = popover();
    wrapper.vm.open = false;
    await wrapper.vm.$nextTick();

    // The real gesture: one click, which both toggles and reaches the document.
    document.querySelector<HTMLElement>("#trigger")!.click();
    await wrapper.vm.$nextTick();

    expect(wrapper.vm.open).toBe(true);
    wrapper.unmount();
  });

  it("leaves a tap inside the panel to the entry's own handler", async () => {
    const wrapper = popover();

    document.querySelector<HTMLElement>("#entry")!.click();
    await wrapper.vm.$nextTick();

    expect(wrapper.vm.open).toBe(true);
    wrapper.unmount();
  });

  it("closes on Escape", async () => {
    const wrapper = popover();

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await wrapper.vm.$nextTick();

    expect(wrapper.vm.open).toBe(false);
    wrapper.unmount();
  });

  it("takes its listeners with it when the component goes", () => {
    const wrapper = popover();
    const state = wrapper.vm.open;
    wrapper.unmount();

    // Nothing left listening to flip a ref belonging to a dead component.
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    document.body.click();

    expect(wrapper.vm.open).toBe(state);
  });
});
