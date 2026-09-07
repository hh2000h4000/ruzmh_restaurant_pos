// @vitest-environment jsdom

/**
 * *Why?* — the one box the till has for it.
 *
 * `BR-013` says a reason is mandatory. Until now the rule was written twice, in
 * two dialogs that were the same but for four strings, and the copies had
 * already drifted. What is asserted here is the rule itself — mandatory, and
 * trimmed, and never carried over from the last time it was asked — so it can
 * only be right or wrong once.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ReasonDialog from "@/components/order/ReasonDialog.vue";

function open(props: Record<string, unknown> = {}) {
  return mount(ReasonDialog, {
    props: {
      open: true,
      title: "سبب الإلغاء",
      explain: "برغر لحم",
      placeholder: "مثال: طلب الزبون التغيير",
      confirm: "إلغاء الصنف",
      ...props,
    },
    global: { stubs: { teleport: true } },
  });
}

type Wrapper = ReturnType<typeof open>;

/** The destructive button is the last one; the first goes back. */
const act = (wrapper: Wrapper) => wrapper.findAll("button").at(-1)!;

describe("asking why", () => {
  it("will not act on an empty box", () => {
    expect(act(open()).attributes("disabled")).toBeDefined();
  });

  it("will not act on spaces either", async () => {
    const wrapper = open();
    await wrapper.find("input").setValue("   ");

    expect(act(wrapper).attributes("disabled")).toBeDefined();
  });

  it("acts once a reason is given, and hands it over trimmed", async () => {
    const wrapper = open();
    await wrapper.find("input").setValue("  الزبون غيّر رأيه  ");

    expect(act(wrapper).attributes("disabled")).toBeUndefined();
    await act(wrapper).trigger("click");

    expect(wrapper.emitted("confirm")).toEqual([["الزبون غيّر رأيه"]]);
  });

  it("holds still while the last answer is in flight", async () => {
    const wrapper = open({ busy: true });
    await wrapper.find("input").setValue("خطأ في الطلب");

    expect(act(wrapper).attributes("disabled")).toBeDefined();
  });

  it("does not offer the last line's reason for the next one", async () => {
    const wrapper = open();
    await wrapper.find("input").setValue("سقط على الأرض");

    await wrapper.setProps({ open: false });
    await wrapper.setProps({ open: true });

    expect((wrapper.find("input").element as HTMLInputElement).value).toBe("");
    expect(act(wrapper).attributes("disabled")).toBeDefined();
  });

  it("says what is being reversed and what the button will do", () => {
    const wrapper = open();

    expect(wrapper.text()).toContain("برغر لحم");
    expect(act(wrapper).text()).toBe("إلغاء الصنف");
  });
});
