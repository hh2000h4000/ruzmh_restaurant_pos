// @vitest-environment jsdom

/**
 * The dialog must not move while a number is being typed (`D-236`).
 *
 * The cashier types a phone number on the pad inside this dialog. The row that
 * offers to create a customer used to appear at the third digit and vanish
 * again on every keystroke while the search ran, so the pad below it jumped up
 * and down under the finger — the user described the whole dialog as shaking.
 *
 * Nothing above the pad may come and go: the row is always rendered and merely
 * disabled, and a list already on screen is not replaced by the word "loading".
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CustomerDialog from "@/components/order/CustomerDialog.vue";

const searchCustomers = vi.fn();

vi.mock("@/api/customer", () => ({
  searchCustomers: (...args: unknown[]) => searchCustomers(...args),
  createCustomer: vi.fn(),
  updateCustomer: vi.fn(),
  customerAddresses: vi.fn().mockResolvedValue([]),
  addCustomerAddress: vi.fn(),
}));

function dialog() {
  return mount(CustomerDialog, {
    props: { open: true, orderName: "RO-1", required: false },
    // The dialog teleports to `body`; stubbing the teleport keeps its content
    // inside the wrapper where this test can read it.
    global: { stubs: { AppIcon: true, DigitPad: true, teleport: true } },
  });
}

/** The row that opens the create step, whatever state it is in. */
function createRow(view: ReturnType<typeof dialog>) {
  return view.findAll("button").find((button) => button.classes().includes("border-dashed"));
}

describe("typing a phone number", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    searchCustomers.mockReset();
    searchCustomers.mockResolvedValue([]);
    vi.useFakeTimers();
  });

  it("keeps the create row in place from the first digit", async () => {
    const view = dialog();

    const before = createRow(view);
    expect(before?.exists()).toBe(true);
    expect(before?.attributes("disabled")).toBeDefined();

    await view.find("input").setValue("0506");
    expect(createRow(view)?.exists()).toBe(true);

    vi.advanceTimersByTime(300);
    await flushPromises();

    const after = createRow(view);
    expect(after?.exists()).toBe(true);
    expect(after?.attributes("disabled")).toBeUndefined();
  });

  it("leaves the results on screen while the next search runs", async () => {
    searchCustomers.mockResolvedValue([
      { name: "CUST-1", customer_name: "نورة", mobile_no: "0506000000" },
    ]);
    const view = dialog();

    await view.find("input").setValue("0506");
    vi.advanceTimersByTime(300);
    await flushPromises();
    expect(view.text()).toContain("نورة");

    // One more digit: the search is in flight again, and the list stays.
    await view.find("input").setValue("05060");
    expect(view.text()).toContain("نورة");
  });
});
