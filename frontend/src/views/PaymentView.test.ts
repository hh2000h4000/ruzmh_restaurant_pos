// @vitest-environment jsdom

/**
 * The payment screen's buttons, and only its buttons.
 *
 * Six defects in three days shared one shape: the server refused something the
 * screen had left tappable, and the cashier found out with money already on the
 * counter (`D-125`, `D-126`). Every test here asks that one question — **is a
 * control the cashier can reach a control the server will accept** — because it
 * is the question nothing else in the suite asks. The 491 backend tests prove
 * the server refuses correctly; none of them can see a live button.
 *
 * Nothing here asserts appearance. A test that pins a class name breaks on the
 * next redesign and protects nobody; `disabled` is the whole vocabulary.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PaymentMethodOption, PaymentSummary } from "@/api/payment";
import * as paymentApi from "@/api/payment";
import PaymentView from "@/views/PaymentView.vue";

const ORDER = "RO-2026-09-00001";

vi.mock("@/api/payment", () => ({
  getPaymentSummary: vi.fn(),
  previewTotals: vi.fn(),
  processPayment: vi.fn(),
  splitEvenly: vi.fn(),
  validateDiscountOverride: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { orderName: ORDER }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

function method(name: string, extra: Partial<PaymentMethodOption> = {}): PaymentMethodOption {
  return {
    payment_method: name,
    is_forced: 0,
    is_default: 0,
    is_cash: 0,
    is_credit: 0,
    ...extra,
  };
}

function summary(extra: Partial<PaymentSummary> = {}): PaymentSummary {
  return {
    order_name: ORDER,
    subtotal: 100,
    discount_amount: 0,
    tax_amount: 15,
    total_amount: 115,
    payment_methods: [method("Cash", { is_cash: 1 }), method("mada")],
    already_paid: false,
    sales_invoice: null,
    blocker: null,
    ...extra,
  };
}

/** Mount the screen with this summary and wait for it to settle. */
async function open(payload: PaymentSummary) {
  vi.mocked(paymentApi.getPaymentSummary).mockResolvedValue(payload);

  const wrapper = mount(PaymentView, { global: { stubs: { RouterLink: true } } });
  await flushPromises();
  return wrapper;
}

type Wrapper = Awaited<ReturnType<typeof open>>;

/** The method button by its name, which is the label a cashier reads. */
function methodButton(wrapper: Wrapper, name: string) {
  const found = wrapper
    .findAll("button")
    .find((button) => button.text().trim() === name);

  if (!found) throw new Error(`no button labelled ${name}`);
  return found;
}

function isDisabled(wrapper: Wrapper, name: string): boolean {
  return (methodButton(wrapper, name).element as HTMLButtonElement).disabled;
}

/** The single button that ends the sale, found by its own label. */
function confirmButton(wrapper: Wrapper) {
  const found = wrapper
    .findAll("button")
    .find((button) => button.text().includes("تأكيد الدفع"));

  if (!found) throw new Error("no confirm button");
  return found.element as HTMLButtonElement;
}

/**
 * Take money on a method the way a cashier does: tap it, then tap the first
 * amount the sheet offers — which is always what is still owed (`D-124`).
 */
async function tender(wrapper: Wrapper, name: string) {
  await methodButton(wrapper, name).trigger("click");
  await flushPromises();

  // Inside the sheet only. The screen behind it also has buttons labelled with
  // bare numbers — the split chips — and reaching one of those from here would
  // be the test doing something no cashier can do while the sheet is open.
  const sheet = wrapper.find('[role="dialog"]');
  if (!sheet.exists()) throw new Error(`tapping ${name} opened no tender sheet`);

  const amount = sheet
    .findAll("button")
    .find((button) => /^[\d,.]+$/.test(button.text().trim()));

  if (!amount) throw new Error("the tender sheet offered no amount");
  await amount.trigger("click");
  await flushPromises();
}

/**
 * Take a part of the bill: tap the method, ask for another amount, key it in.
 *
 * The sheet's ready-made options are the balance and the notes above it, so a
 * *partial* tender can only be reached through the keypad — which is also the
 * only way a real cashier reaches one.
 */
async function tenderSome(wrapper: Wrapper, name: string, digits: string) {
  await methodButton(wrapper, name).trigger("click");
  await flushPromises();

  const sheet = wrapper.find('[role="dialog"]');
  const inSheet = (label: string) =>
    sheet.findAll("button").find((button) => button.text().trim() === label);

  await inSheet("مبلغ آخر")!.trigger("click");
  for (const digit of digits) await inSheet(digit)!.trigger("click");
  await inSheet("تم")!.trigger("click");
  await flushPromises();
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("what the payment screen lets a cashier reach", () => {
  it("offers every permitted method on an ordinary bill", async () => {
    const wrapper = await open(summary());

    expect(isDisabled(wrapper, "Cash")).toBe(false);
    expect(isDisabled(wrapper, "mada")).toBe(false);
  });

  it("will not confirm a bill nothing has been taken on", async () => {
    const wrapper = await open(summary());

    expect(confirmButton(wrapper).disabled).toBe(true);
  });

  it("confirms once the bill is covered", async () => {
    const wrapper = await open(summary());

    await tender(wrapper, "Cash");

    expect(confirmButton(wrapper).disabled).toBe(false);
  });

  /**
   * `BR-002` — an app order is settled by the app. Taking cash for one puts
   * money in the till that the platform also pays out, and the server has
   * always refused it; what it did not do was refuse it *early*.
   */
  it("quietens every method an order type does not force", async () => {
    const wrapper = await open(
      summary({
        payment_methods: [
          method("Cash", { is_cash: 1 }),
          method("HungerStation", { is_forced: 1, is_credit: 1 }),
        ],
      }),
    );

    expect(isDisabled(wrapper, "HungerStation")).toBe(false);
    expect(isDisabled(wrapper, "Cash")).toBe(true);
  });

  it("accepts either of two forced methods, matching the server", async () => {
    const wrapper = await open(
      summary({
        payment_methods: [
          method("Cash", { is_cash: 1 }),
          method("mada", { is_forced: 1 }),
          method("Credit Card", { is_forced: 1 }),
        ],
      }),
    );

    expect(isDisabled(wrapper, "mada")).toBe(false);
    expect(isDisabled(wrapper, "Credit Card")).toBe(false);
    expect(isDisabled(wrapper, "Cash")).toBe(true);
  });

  /**
   * `D-029` — a bill is settled at the till **or** billed to an account, never
   * both. Half to a delivery platform and half in cash leaves a
   * partly-outstanding invoice inside a cash-drawer reconciliation.
   */
  it("closes off account methods once money has entered the till", async () => {
    const wrapper = await open(
      summary({
        total_amount: 200,
        payment_methods: [
          method("Cash", { is_cash: 1 }),
          method("Jahez", { is_credit: 1 }),
        ],
      }),
    );

    // Fifty of two hundred, deliberately: with the bill still uncovered, a
    // quiet Jahez can only be the settlement rule and not the balance.
    await tenderSome(wrapper, "Cash", "50");

    expect(isDisabled(wrapper, "Jahez")).toBe(true);
    expect(isDisabled(wrapper, "Cash")).toBe(false);
  });

  it("stops offering methods once the bill is covered", async () => {
    const wrapper = await open(summary());

    await tender(wrapper, "Cash");

    expect(isDisabled(wrapper, "mada")).toBe(true);
  });

  /**
   * The worst of the family: a terminal with no default customer threw from
   * inside the Sales Invoice, which is after the drawer is open and after the
   * customer has counted out the money.
   */
  it("takes nothing at all when the terminal cannot raise an invoice", async () => {
    const wrapper = await open(summary({ blocker: "اضبط عميلاً افتراضياً على الطرفية." }));

    expect(isDisabled(wrapper, "Cash")).toBe(true);
    expect(isDisabled(wrapper, "mada")).toBe(true);
    expect(confirmButton(wrapper).disabled).toBe(true);
    expect(wrapper.text()).toContain("اضبط عميلاً افتراضياً");
  });

  /** `BR-016` — a bill with an invoice on it does not take a second payment. */
  it("takes nothing on a bill that is already paid", async () => {
    const wrapper = await open(
      summary({ already_paid: true, sales_invoice: "ACC-SINV-2026-00001" }),
    );

    expect(isDisabled(wrapper, "Cash")).toBe(true);
    expect(confirmButton(wrapper).disabled).toBe(true);
  });

  /**
   * `D-123` — a refused payment is the cashier's next move, not the end of the
   * screen. The old version replaced everything with a red sentence and threw
   * away the amounts they had just entered.
   */
  it("keeps the screen when the server refuses the payment", async () => {
    const wrapper = await open(summary());
    vi.mocked(paymentApi.processPayment).mockRejectedValue(new Error("رُفض الدفع"));

    await tender(wrapper, "Cash");
    await confirmButton(wrapper).click();
    await flushPromises();

    expect(wrapper.text()).toContain("رُفض الدفع");
    // Still a payment screen, with the tender the cashier took still on it.
    expect(wrapper.findAll("button").some((b) => b.text().trim() === "mada")).toBe(true);
  });
});
