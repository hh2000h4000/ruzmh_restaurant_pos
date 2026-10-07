// @vitest-environment jsdom

/**
 * Where a returned line goes: back on the shelf, or in the bin (`D-315`).
 *
 * The till used to put every return back in stock — the ingredients of a burger
 * that had been eaten included — so the warehouse on screen grew past the real
 * one with each refund. The server now decides what each line *opens* on and
 * posts whatever the cashier leaves it at; what only this screen can get wrong
 * is the part in between: showing that default, letting it be flipped, and
 * sending what was chosen rather than what was offered.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as returnsApi from "@/api/returns";
import ReturnDialog from "@/components/order/ReturnDialog.vue";
import { t } from "@/i18n";

vi.mock("@/api/returns", () => ({
  getReturnable: vi.fn(),
  previewReturn: vi.fn(),
  createReturn: vi.fn(),
}));
vi.mock("@/api/payment", () => ({ validateManagerOverride: vi.fn() }));

function line(row: string, item_name: string, moves_stock: boolean): returnsApi.ReturnableLine {
  return { row, idx: 1, item: row, item_name, qty: 2, rate: 10, amount: 20, returned: 0, returnable: 2, moves_stock };
}

const BILL: returnsApi.Returnable = {
  order_name: "RO-1002-01-000007",
  sales_invoice: "1002-01-000007",
  // The burger took its ingredients; the service charge took nothing from the shelf.
  items: [line("burger-row", "برغر", true), line("service-row", "خدمة", false)],
  reasons: ["goods_returned"],
  methods: ["Cash"],
  paid_with: [{ method: "Cash", amount: 40 }],
  returns: [],
  fully_returned: false,
  needs_manager: false,
  manager_methods: [],
};

async function sheet() {
  vi.mocked(returnsApi.getReturnable).mockResolvedValue(BILL);
  vi.mocked(returnsApi.previewReturn).mockResolvedValue({ refund_amount: 10, net_amount: 8.7, tax_amount: 1.3 });
  vi.mocked(returnsApi.createReturn).mockResolvedValue({
    order_name: BILL.order_name,
    sales_invoice: BILL.sales_invoice,
    credit_note: "1002-01-000008",
    refund_amount: 10,
    returnable: BILL,
  });

  const wrapper = mount(ReturnDialog, {
    props: { open: false, orderName: BILL.order_name },
    global: { stubs: { teleport: true } },
  });
  await wrapper.setProps({ open: true });
  await flushPromises();
  return wrapper;
}

type Sheet = Awaited<ReturnType<typeof sheet>>;

/** The row of one item, by the name the cashier reads. */
function rowOf(view: Sheet, name: string) {
  // The line itself, not the list around it: the list's text holds every name.
  const row = view.findAll("div").find((one) => one.classes("px-3") && one.text().includes(name));
  expect(row, `no line for "${name}"`).toBeTruthy();
  return row!;
}

async function takeOne(view: Sheet, name: string) {
  await rowOf(view, name).find(`button[aria-label="${t("picker.qtyMore")}"]`).trigger("click");
  await flushPromises();
}

/** The two answers under a line, once it is coming back. */
function answers(view: Sheet, name: string) {
  return rowOf(view, name).findAll("[data-where] button");
}

async function answer(view: Sheet, name: string, wasted: boolean) {
  const label = wasted ? t("ret.wasted") : t("ret.restocked");
  await answers(view, name)
    .find((one) => one.text().trim() === label)!
    .trigger("click");
  await flushPromises();
}

function confirmButton(view: Sheet) {
  return view.findAll("button").find((one) => one.text().trim() === t("ret.confirm"))!;
}

async function confirm(view: Sheet) {
  const reason = view.findAll("button").find((one) => one.text().trim() === t("ret.reasonReturned"));
  await reason!.trigger("click");
  await confirmButton(view).trigger("click");
  await flushPromises();
}

describe("where a returned line goes", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("asks nothing about a line that is not coming back", async () => {
    const view = await sheet();

    expect(answers(view, "برغر")).toHaveLength(0);
  });

  it("asks, with neither answer chosen — the till does not presume waste (`D-327`)", async () => {
    // A guest who cancels before the kitchen starts has wasted nothing.
    const view = await sheet();

    await takeOne(view, "برغر");

    const both = answers(view, "برغر");
    expect(both.map((one) => one.text().trim())).toEqual([t("ret.restocked"), t("ret.wasted")]);
    expect(both.map((one) => one.attributes("aria-pressed"))).toEqual(["false", "false"]);
  });

  it("does not refund until it is answered, and says why", async () => {
    const view = await sheet();
    await takeOne(view, "برغر");
    await view.findAll("button").find((one) => one.text().trim() === t("ret.reasonReturned"))!.trigger("click");

    expect(confirmButton(view).attributes("disabled")).toBeDefined();
    expect(view.find("[data-say-where]").text()).toBe(t("ret.sayWhere"));

    await answer(view, "برغر", false);

    expect(confirmButton(view).attributes("disabled")).toBeUndefined();
    expect(view.find("[data-say-where]").exists()).toBe(false);
  });

  it("sends what the cashier said, and nothing for a line that took no stock", async () => {
    const view = await sheet();
    await takeOne(view, "برغر");
    await takeOne(view, "خدمة");
    expect(answers(view, "خدمة")).toHaveLength(0);

    await answer(view, "برغر", true);
    await confirm(view);

    expect(vi.mocked(returnsApi.createReturn).mock.calls[0][0].items).toEqual([
      { row: "burger-row", qty: 1, wasted: true },
      { row: "service-row", qty: 1 },
    ]);
  });

  it("lets the answer be changed before confirming", async () => {
    const view = await sheet();
    await takeOne(view, "برغر");

    await answer(view, "برغر", true);
    await answer(view, "برغر", false);
    await confirm(view);

    expect(vi.mocked(returnsApi.createReturn).mock.calls[0][0].items).toEqual([
      { row: "burger-row", qty: 1, wasted: false },
    ]);
  });

  it("does not ask the server for the refund again when only the answer changes", async () => {
    // Where the food goes changes the stock, never the money.
    const view = await sheet();
    await takeOne(view, "برغر");
    const asked = vi.mocked(returnsApi.previewReturn).mock.calls.length;

    await answer(view, "برغر", true);

    expect(vi.mocked(returnsApi.previewReturn).mock.calls.length).toBe(asked);
  });
});

describe("a platform's bill paid back another way", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("says a manager is needed for cash, and not for the platform itself (`D-326`)", async () => {
    const view = await sheet();
    Object.assign(BILL, {
      methods: ["Cash", "HungerStation"],
      paid_with: [{ method: "HungerStation", amount: 40 }],
      manager_methods: ["Cash"],
    });
    await view.setProps({ open: false });
    await view.setProps({ open: true });
    await flushPromises();
    const hint = t("ret.needsManagerForMethod", { method: "Cash" });

    expect(view.text()).not.toContain(hint);

    await view.findAll("button").find((one) => one.text().trim() === "Cash")!.trigger("click");

    expect(view.text()).toContain(hint);
  });
});
