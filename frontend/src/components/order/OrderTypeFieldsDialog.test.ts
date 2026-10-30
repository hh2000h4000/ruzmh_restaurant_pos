// @vitest-environment jsdom

/**
 * The order type's questions, asked once for every path (`D-409`).
 *
 * The claims the cashier meets: the type names the dialog, a required field
 * keeps the button off until it is filled, the keys under the finger type into
 * it on a till with no keyboard, and backing out answers nothing.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import OrderTypeFieldsDialog from "@/components/order/OrderTypeFieldsDialog.vue";
import { t } from "@/i18n";
import { useTypeFieldsStore } from "@/stores/typeFields";
import type { OrderType } from "@/types/session";

const HUNGER = {
  name: "OT-HUNGER",
  title: "HungerStation",
  title_ar: "هنقرستيشن",
  additional_fields: [
    {
      label: "App Order No",
      label_ar: "رقم الطلب في التطبيق",
      type: "text",
      options: [],
      is_required: 1,
      show_at: "on_open",
      placeholder: "HS-29541",
    },
  ],
} as unknown as OrderType;

beforeEach(() => setActivePinia(createPinia()));

async function asked() {
  const view = mount(OrderTypeFieldsDialog, { global: { stubs: { teleport: true } } });
  const answer = useTypeFieldsStore().ask(HUNGER);
  await flushPromises();
  return { view, answer };
}

function button(view: ReturnType<typeof mount>, text: string) {
  const found = view.findAll("button").find((one) => one.text().trim() === text);
  expect(found, `no button reading "${text}"`).toBeTruthy();
  return found!;
}

describe("the type's questions", () => {
  it("is titled by the type and asks its field in Arabic", async () => {
    const { view } = await asked();

    expect(view.text()).toContain("هنقرستيشن");
    expect(view.text()).toContain("رقم الطلب في التطبيق");
  });

  it("keeps the button off until the required number is in", async () => {
    const { view, answer } = await asked();
    const go = () => button(view, t("typeFields.continue"));

    expect(go().attributes("disabled")).toBeDefined();
    await view.find("input").setValue("29541");
    expect(go().attributes("disabled")).toBeUndefined();

    await go().trigger("click");
    await expect(answer).resolves.toEqual({ "App Order No": "29541" });
  });

  it("types with the keys under the finger", async () => {
    const { view, answer } = await asked();

    for (const key of ["2", "9", "5"]) await button(view, key).trigger("click");
    await button(view, t("typeFields.continue")).trigger("click");

    await expect(answer).resolves.toEqual({ "App Order No": "295" });
  });

  it("answers nothing when the cashier backs out", async () => {
    const { view, answer } = await asked();

    await button(view, t("action.cancel")).trigger("click");

    await expect(answer).resolves.toBeNull();
  });
});
