// @vitest-environment jsdom

/**
 * Why, tapped rather than typed (`D-239`).
 *
 * "Why was this voided" and "why was this bill cancelled" are answered
 * one-handed, in a rush, with a customer waiting — and the answers are the same
 * handful every day. The user asked for them as buttons, and they come from the
 * list a manager already keeps for quick notes, so there is one screen in the
 * desk and one mechanism in the till.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import ReasonDialog from "@/components/order/ReasonDialog.vue";
import { useSessionStore } from "@/stores/session";

const NOTES = [
  { name: "n1", title: "No onion", title_ar: "بدون بصل", scope: "item" },
  { name: "n2", title: "Cutlery", title_ar: "أدوات مائدة", scope: "both" },
  { name: "n3", title: "Rung up by mistake", title_ar: "انضاف بالغلط", scope: "void_reason" },
  { name: "n4", title: "Out of stock", title_ar: "الصنف خلص", scope: "void_reason" },
  { name: "n5", title: "Customer left", title_ar: "الزبون انسحب", scope: "cancel_reason" },
];

function dialog(scope: "void_reason" | "cancel_reason") {
  return mount(ReasonDialog, {
    props: {
      open: true,
      title: "لماذا؟",
      explain: "شيش طاووق",
      placeholder: "اكتب السبب",
      confirm: "إلغاء الصنف",
      scope,
    },
    global: { stubs: { teleport: true } },
  });
}

describe("asking why", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useSessionStore().data = { quick_notes: NOTES } as never;
  });

  it("offers only the reasons for this act, never the kitchen notes", () => {
    const view = dialog("void_reason");
    const chips = view.findAll("button").map((button) => button.text());

    expect(chips).toContain("انضاف بالغلط");
    expect(chips).toContain("الصنف خلص");
    expect(chips).not.toContain("الزبون انسحب");
    // `both` is a note scope: an item note is not a reason for voiding one.
    expect(chips).not.toContain("أدوات مائدة");
  });

  it("a tap answers the question, and the confirm button comes alive", async () => {
    const view = dialog("cancel_reason");
    expect(view.find("button.bg-danger").attributes("disabled")).toBeDefined();

    await view.findAll("button").find((b) => b.text() === "الزبون انسحب")?.trigger("click");

    expect((view.find("textarea").element as HTMLTextAreaElement).value).toBe("الزبون انسحب");
    expect(view.find("button.bg-danger").attributes("disabled")).toBeUndefined();
  });

  it("a second tap replaces the answer rather than adding to it", async () => {
    const view = dialog("void_reason");
    const tap = async (label: string) =>
      view.findAll("button").find((b) => b.text() === label)?.trigger("click");

    await tap("انضاف بالغلط");
    await tap("الصنف خلص");

    // One question, one answer — not "rung up by mistake، out of stock".
    expect((view.find("textarea").element as HTMLTextAreaElement).value).toBe("الصنف خلص");
  });

  it("still takes a reason nobody listed", async () => {
    const view = dialog("void_reason");

    await view.find("textarea").setValue("وقع من الويتر");

    expect(view.find("button.bg-danger").attributes("disabled")).toBeUndefined();
  });
});
