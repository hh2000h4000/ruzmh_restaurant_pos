// @vitest-environment jsdom

/**
 * What the cashier sees after tapping a refund row (`D-171`).
 *
 * The row carries the **sale's** name so its card can wear the sale's table and
 * customer, and tapping it therefore opened the sale: four items at positive
 * prices, on a row labelled *refund* showing a negative figure. The two dishes
 * that came back were nowhere on the screen.
 *
 * No backend test can see which document a tap opens. The endpoint can return
 * the credit note perfectly and the screen still route to the sale, and the
 * suite stays green either way (`D-130`).
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as returnsApi from "@/api/returns";
import RefundDialog from "@/components/order/RefundDialog.vue";
import { t } from "@/i18n";

vi.mock("@/api/returns", () => ({ getRefund: vi.fn() }));

const REFUND: returnsApi.RefundDetail = {
  credit_note: "ACC-SINV-2026-00011",
  daily_number: 18,
  returns_daily_number: 17,
  order_name: "RO-2026-09-00017",
  reason: "Return of ACC-SINV-2026-00010: goods_returned",
  refunded_at: "2026-09-09 12:00:00",
  total_amount: -26,
  tax_amount: -3.39,
  items: [
    { item: "SAL-1", item_name: "تبولة", qty: -1, rate: 14, amount: -14 },
    { item: "SAL-2", item_name: "سلطة خضراء", qty: -1, rate: 12, amount: -12 },
  ],
};

async function sheet(detail: returnsApi.RefundDetail | Error = REFUND) {
  if (detail instanceof Error) {
    vi.mocked(returnsApi.getRefund).mockRejectedValue(detail);
  } else {
    vi.mocked(returnsApi.getRefund).mockResolvedValue(detail);
  }

  const wrapper = mount(RefundDialog, {
    props: { open: true, creditNote: "ACC-SINV-2026-00011" },
    global: { stubs: { teleport: true } },
  });
  await flushPromises();
  return wrapper;
}

beforeEach(() => vi.clearAllMocks());

describe("the sheet a refund row opens", () => {
  it("shows what came back and nothing else", async () => {
    const text = (await sheet()).text();

    expect(text).toContain("تبولة");
    expect(text).toContain("سلطة خضراء");
  });

  /**
   * The complaint in one line: the bill had four items and two came back.
   * Anything that reads the sale instead puts the other two on this screen.
   */
  it("does not show the lines that stayed on the bill", async () => {
    const wrapper = await sheet();

    expect(wrapper.findAll("li")).toHaveLength(2);
  });

  it("reads every figure as money going out", async () => {
    const text = (await sheet()).text();

    expect(text).toContain("-26.00");
    expect(text).toContain("-14.00");
  });

  it("names its own number and the bill it reverses", async () => {
    const text = (await sheet()).text();

    expect(text).toContain(t("ret.detailAgainst", { number: "18", against: "17" }));
  });

  it("asks for the refund it was given, not for the sale", async () => {
    await sheet();

    expect(returnsApi.getRefund).toHaveBeenCalledWith("ACC-SINV-2026-00011");
  });

  it("offers the paper again, with the refund's own number", async () => {
    const wrapper = await sheet();

    await wrapper.findAll("button").find((button) => button.text() === t("print.receiptAgain"))
      ?.trigger("click");

    expect(wrapper.emitted("reprint")).toEqual([[18]]);
  });

  /**
   * `D-074` — a sheet that opens empty is indistinguishable from a refund with
   * nothing on it.
   */
  it("says so when it cannot read the refund", async () => {
    const wrapper = await sheet(new Error("لا صلاحية على هذا الفرع"));

    expect(wrapper.text()).toContain("لا صلاحية على هذا الفرع");
  });
});
