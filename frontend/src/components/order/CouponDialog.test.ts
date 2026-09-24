// @vitest-environment jsdom

/**
 * The guest's coupon code, from either door (`D-248`).
 *
 * One dialog serves the order screen's More menu and the payment screen, so the
 * claims are the ones both rest on: an empty box sends nothing, the code goes up
 * as typed, a code already on the bill can be taken back off, and the server's
 * own refusal is what the cashier reads — expired, used up and switched off are
 * different problems and each has an answer.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CouponDialog from "@/components/order/CouponDialog.vue";

const applyCoupon = vi.fn();
const removeCoupon = vi.fn();

vi.mock("@/api/payment", () => ({
  applyCoupon: (...args: unknown[]) => applyCoupon(...args),
  removeCoupon: (...args: unknown[]) => removeCoupon(...args),
}));

function dialog(applied: { name: string; code: string; campaign: string } | null = null) {
  return mount(CouponDialog, {
    props: { open: true, orderName: "RO-1", applied },
    global: { stubs: { teleport: true } },
  });
}

async function tap(view: ReturnType<typeof dialog>, text: string) {
  const button = view.findAll("button").find((one) => one.text().trim() === text);
  expect(button, `no button reading "${text}"`).toBeTruthy();
  await button!.trigger("click");
  await flushPromises();
}

describe("entering a coupon", () => {
  beforeEach(() => {
    applyCoupon.mockReset();
    applyCoupon.mockResolvedValue({ coupon: { name: "SAVE10", coupon_code: "SAVE10" } });
    removeCoupon.mockReset();
    removeCoupon.mockResolvedValue({});
  });

  it("sends nothing while the box is empty", async () => {
    const view = dialog();

    await tap(view, "تطبيق");

    expect(applyCoupon).not.toHaveBeenCalled();
  });

  it("sends the code as it was typed", async () => {
    const view = dialog();

    await view.find("input").setValue("  save10 ");
    await tap(view, "تطبيق");

    expect(applyCoupon).toHaveBeenCalledWith({ order_name: "RO-1", code: "save10" });
    expect(view.emitted("changed")).toHaveLength(1);
  });

  it("names the code already on the bill, and takes it back off", async () => {
    const view = dialog({ name: "SAVE10", code: "SAVE10", campaign: "RPOS Influencer" });

    expect(view.text()).toContain("SAVE10");
    expect(view.text()).toContain("RPOS Influencer");

    await tap(view, "إزالة");

    expect(removeCoupon).toHaveBeenCalledWith("RO-1");
    expect(view.emitted("changed")).toHaveLength(1);
  });

  it("shows the server's refusal rather than a guess of its own", async () => {
    applyCoupon.mockRejectedValue(new Error("This coupon has been used already."));
    const view = dialog();

    await view.find("input").setValue("SAVE10");
    await tap(view, "تطبيق");

    expect(view.text()).toContain("used already");
    expect(view.emitted("changed")).toBeUndefined();
  });
});
