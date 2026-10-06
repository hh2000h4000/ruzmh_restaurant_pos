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

function line(row: string, item_name: string, wasted: boolean): returnsApi.ReturnableLine {
  return { row, idx: 1, item: row, item_name, qty: 2, rate: 10, amount: 20, returned: 0, returnable: 2, wasted };
}

const BILL: returnsApi.Returnable = {
  order_name: "RO-1002-01-000007",
  sales_invoice: "1002-01-000007",
  // A dish opens as waste; a thing sold as it came opens as going back.
  items: [line("burger-row", "برغر", true), line("water-row", "قارورة ماء", false)],
  reasons: ["goods_returned"],
  methods: ["Cash"],
  paid_with: [{ method: "Cash", amount: 40 }],
  returns: [],
  fully_returned: false,
  needs_manager: false,
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

function where(view: Sheet, name: string) {
  return rowOf(view, name)
    .findAll("button")
    .find((one) => [t("ret.wasted"), t("ret.restocked")].includes(one.text().trim()));
}

async function confirm(view: Sheet) {
  const reason = view.findAll("button").find((one) => one.text().trim() === t("ret.reasonReturned"));
  await reason!.trigger("click");
  const button = view.findAll("button").find((one) => one.text().trim() === t("ret.confirm"));
  await button!.trigger("click");
  await flushPromises();
}

describe("where a returned line goes", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("says nothing about a line that is not coming back", async () => {
    const view = await sheet();

    expect(where(view, "برغر")).toBeUndefined();
    expect(where(view, "قارورة ماء")).toBeUndefined();
  });

  it("opens each line on what the server says its item is", async () => {
    const view = await sheet();

    await takeOne(view, "برغر");
    await takeOne(view, "قارورة ماء");

    expect(where(view, "برغر")!.text()).toBe(t("ret.wasted"));
    expect(where(view, "برغر")!.attributes("aria-pressed")).toBe("true");
    expect(where(view, "قارورة ماء")!.text()).toBe(t("ret.restocked"));
    expect(where(view, "قارورة ماء")!.attributes("aria-pressed")).toBe("false");
  });

  it("sends what the cashier left it at, line by line", async () => {
    const view = await sheet();
    await takeOne(view, "برغر");
    await takeOne(view, "قارورة ماء");

    // The plate came back untouched: the cashier says it is not waste.
    await where(view, "برغر")!.trigger("click");
    await confirm(view);

    expect(vi.mocked(returnsApi.createReturn).mock.calls[0][0].items).toEqual([
      { row: "burger-row", qty: 1, wasted: false },
      { row: "water-row", qty: 1, wasted: false },
    ]);
  });

  it("sends the default when the cashier leaves it alone", async () => {
    const view = await sheet();
    await takeOne(view, "برغر");

    await confirm(view);

    expect(vi.mocked(returnsApi.createReturn).mock.calls[0][0].items).toEqual([
      { row: "burger-row", qty: 1, wasted: true },
    ]);
  });

  it("does not ask the server for the refund again when only the destination changes", async () => {
    // Where the food goes changes the stock, never the money.
    const view = await sheet();
    await takeOne(view, "برغر");
    const asked = vi.mocked(returnsApi.previewReturn).mock.calls.length;

    await where(view, "برغر")!.trigger("click");
    await flushPromises();

    expect(vi.mocked(returnsApi.previewReturn).mock.calls.length).toBe(asked);
    expect(where(view, "برغر")!.text()).toBe(t("ret.restocked"));
  });
});
