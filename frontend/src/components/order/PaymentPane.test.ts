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

import type { LoyaltyOffer } from "@/api/order";
import type { PaymentMethodOption, PaymentSummary } from "@/api/payment";
import * as giftCardApi from "@/api/giftCard";
import * as paymentApi from "@/api/payment";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";
import PaymentPane from "@/components/order/PaymentPane.vue";

const ORDER = "RO-2026-09-00001";

vi.mock("@/api/giftCard");
vi.mock("@/api/payment", () => ({
  getPaymentSummary: vi.fn(),
  previewTotals: vi.fn(),
  processPayment: vi.fn(),
  promotionOffers: vi.fn(),
  splitEvenly: vi.fn(),
  validateDiscountOverride: vi.fn(),
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
    promotion_amount: 0,
    promotion_title: "",
    promotion_title_ar: "",
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
async function open(
  payload: PaymentSummary,
  promotions: { offers: paymentApi.PromotionOffer[]; may_choose: boolean } = {
    offers: [],
    may_choose: true,
  },
) {
  vi.mocked(paymentApi.getPaymentSummary).mockResolvedValue(payload);
  vi.mocked(paymentApi.promotionOffers).mockResolvedValue(promotions);

  const wrapper = mount(PaymentPane, {
    props: { orderName: ORDER },
    // `BaseDialog` teleports to `<body>`, which is right in the app and puts
    // the tender sheet outside the wrapper's tree here. Stubbing the teleport
    // renders it where it was written, so the sheet can be reached the way the
    // cashier reaches it — through the screen that opened it.
    global: { stubs: { teleport: true } },
  });
  await flushPromises();
  return wrapper;
}

type Wrapper = Awaited<ReturnType<typeof open>>;

/** Whether a button is the method of that name — its label, beside its initial. */
function isMethod(button: ReturnType<Wrapper["find"]>, name: string): boolean {
  const label = button.find("[data-method-label]");
  return (label.exists() ? label.text() : button.text()).trim() === name;
}

/** The method button by its name, which is the label a cashier reads. */
function methodButton(wrapper: Wrapper, name: string) {
  const found = wrapper
    .findAll("button")
    .find((button) => isMethod(button, name));

  if (!found) throw new Error(`no button labelled ${name}`);
  return found;
}

function isDisabled(wrapper: Wrapper, name: string): boolean {
  return (methodButton(wrapper, name).element as HTMLButtonElement).disabled;
}

/**
 * The button that ends the sale, found by its own label — the summary card's.
 * Narrower than three columns the bar at the foot carries the same one
 * (`D-278`); CSS shows one or the other, and jsdom draws both.
 */
function confirmButton(wrapper: Wrapper) {
  const found = wrapper
    .findAll("button")
    .find((button) => button.text().includes("تأكيد الدفع"));

  if (!found) throw new Error("no confirm button");
  return found.element as HTMLButtonElement;
}

/**
 * Everything tappable inside the open sheet.
 *
 * Scoped deliberately: the screen behind it also carries buttons labelled with
 * bare numbers — the split chips — and reaching one of those from here would be
 * the test doing something no cashier can do while a sheet is over them.
 */
function sheetButtons(wrapper: Wrapper, opened: string) {
  const sheet = wrapper.find('[role="dialog"]');
  if (!sheet.exists()) throw new Error(`tapping ${opened} opened no tender sheet`);

  return sheet.findAll("button");
}

function tap(buttons: ReturnType<typeof sheetButtons>, label: string) {
  const found = buttons.find((button) => button.text().trim() === label);
  if (found) return found;

  throw new Error(
    `no "${label}" in the sheet — it offers: ${buttons.map((b) => b.text().trim()).join(" | ")}`,
  );
}

/** Take money on a method the way a cashier does: tap it, then tap an amount. */
async function tender(wrapper: Wrapper, name: string) {
  await methodButton(wrapper, name).trigger("click");
  await flushPromises();

  // The first option is always what is still owed (`D-124`), and it is the
  // first thing in the sheet carrying a figure.
  const amount = sheetButtons(wrapper, name).find((button) => /\d/.test(button.text()));
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

  await tap(sheetButtons(wrapper, name), "مبلغ آخر").trigger("click");
  for (const digit of digits) {
    await tap(sheetButtons(wrapper, name), digit).trigger("click");
  }
  await tap(sheetButtons(wrapper, name), "تم").trigger("click");
  await flushPromises();
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();

  // A drawer of this cashier's own, open. `BR-044` is checked on the press
  // rather than standing on the screen (`D-058`), so without this every
  // Confirm stops at "open a shift first" and never reaches the server —
  // which is correct behaviour, and would quietly hollow out the tests below.
  useSessionStore().data = { can_sell: true } as PosSession;
});

describe("what the payment screen lets a cashier reach", () => {
  it("offers every permitted method on an ordinary bill", async () => {
    const wrapper = await open(summary());

    expect(isDisabled(wrapper, "نقد")).toBe(false);
    expect(isDisabled(wrapper, "mada")).toBe(false);
  });

  it("will not confirm a bill nothing has been taken on", async () => {
    const wrapper = await open(summary());

    expect(confirmButton(wrapper).disabled).toBe(true);
  });

  it("confirms once the bill is covered", async () => {
    const wrapper = await open(summary());

    await tender(wrapper, "نقد");

    expect(confirmButton(wrapper).disabled).toBe(false);
  });

  it("keeps the total and the button at the foot of a narrow screen", async () => {
    // `D-278` — on a phone the button was below the screen, on a tablet cut in
    // half. The bar answers exactly as the card's button does.
    const wrapper = await open(summary());
    const bar = wrapper.find("[data-pay-bar]");
    const barButton = () =>
      bar.findAll("button").find((b) => b.text().includes("تأكيد الدفع"))!.element as HTMLButtonElement;

    expect(bar.text()).toContain("تأكيد الدفع");
    expect(barButton().disabled).toBe(true);

    await tender(wrapper, "نقد");

    expect(barButton().disabled).toBe(confirmButton(wrapper).disabled);
    expect(barButton().disabled).toBe(false);
  });

  /**
   * `BR-002` — an app order is settled by the app. Taking cash for one puts
   * money in the till that the platform also pays out, and the server has
   * always refused it; what it did not do was refuse it *early*.
   */
  it("shows only the methods an order type forces", async () => {
    const wrapper = await open(
      summary({
        payment_methods: [
          method("Cash", { is_cash: 1 }),
          method("HungerStation", { is_forced: 1, is_credit: 1 }),
        ],
      }),
    );

    expect(isDisabled(wrapper, "HungerStation")).toBe(false);
    // Not greyed but gone (`D-386`): the bill shows only what it may take.
    expect(wrapper.findAll("button").some((b) => isMethod(b, "نقد"))).toBe(false);
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
    expect(isDisabled(wrapper, "بطاقة ائتمان")).toBe(false);
    expect(wrapper.findAll("button").some((b) => isMethod(b, "نقد"))).toBe(false);
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
    await tenderSome(wrapper, "نقد", "50");

    expect(isDisabled(wrapper, "Jahez")).toBe(true);
    expect(isDisabled(wrapper, "نقد")).toBe(false);
  });

  it("takes what is owed on one tap of a card, and Pay is the second", async () => {
    // `D-386` — a card is never handed more than the bill, so it asks nothing.
    const wrapper = await open(summary());

    await methodButton(wrapper, "mada").trigger("click");
    await flushPromises();

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(confirmButton(wrapper).disabled).toBe(false);
  });

  it("stops offering methods once the bill is covered", async () => {
    const wrapper = await open(summary());

    await tender(wrapper, "نقد");

    expect(isDisabled(wrapper, "mada")).toBe(true);
  });

  /**
   * The worst of the family: a terminal with no default customer threw from
   * inside the Sales Invoice, which is after the drawer is open and after the
   * customer has counted out the money.
   */
  it("takes nothing at all when the terminal cannot raise an invoice", async () => {
    const wrapper = await open(summary({ blocker: "اضبط عميلاً افتراضياً على الطرفية." }));

    expect(isDisabled(wrapper, "نقد")).toBe(true);
    expect(isDisabled(wrapper, "mada")).toBe(true);
    expect(confirmButton(wrapper).disabled).toBe(true);
    expect(wrapper.text()).toContain("اضبط عميلاً افتراضياً");
  });

  /** `BR-016` — a bill with an invoice on it does not take a second payment. */
  it("takes nothing on a bill that is already paid", async () => {
    const wrapper = await open(
      summary({ already_paid: true, sales_invoice: "ACC-SINV-2026-00001" }),
    );

    expect(isDisabled(wrapper, "نقد")).toBe(true);
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

    await tender(wrapper, "نقد");
    await confirmButton(wrapper).click();
    await flushPromises();

    expect(wrapper.text()).toContain("رُفض الدفع");
    // Still a payment screen, with the tender the cashier took still on it.
    expect(wrapper.findAll("button").some((b) => isMethod(b, "mada"))).toBe(true);
  });
});

/**
 * The offers list (`D-165`).
 *
 * **The hole this closes was invisible from the server.** `is_auto_apply = 0`
 * means the promotion is offered rather than taken, the engine returned such
 * promotions correctly, and no screen ever drew them — so a manager could
 * configure one, save it, watch it listed as active, and it did nothing. Every
 * backend test passed throughout.
 */
function offer(extra: Partial<paymentApi.PromotionOffer> = {}): paymentApi.PromotionOffer {
  return {
    name: "PROMO-001",
    title: "Breakfast offer",
    title_ar: "عرض الإفطار",
    benefit: 10,
    is_auto_apply: 0,
    is_chosen: 0,
    ...extra,
  };
}

/** The offer button by the title a cashier reads. */
function offerButton(wrapper: Wrapper, title: string) {
  const found = wrapper.findAll("button").find((button) => button.text().includes(title));
  if (!found) throw new Error(`no offer button for ${title}`);
  return found;
}

describe("choosing an offer the shop configured", () => {
  it("shows what is on offer, with what it takes off", async () => {
    const wrapper = await open(summary(), { offers: [offer()], may_choose: true });

    expect(offerButton(wrapper, "عرض الإفطار").text()).toContain("10");
  });

  it("re-prices on the server rather than working the figure out here", async () => {
    vi.mocked(paymentApi.previewTotals).mockResolvedValue({
      subtotal: 100,
      discount_amount: 10,
      promotion_amount: 10,
      promotion_title: "Breakfast offer",
      promotion_title_ar: "عرض الإفطار",
      tax_amount: 13.5,
      total_amount: 90,
      discount_percentage: 0,
      max_discount_percentage: 20,
      requires_override: false,
    });
    const wrapper = await open(summary(), { offers: [offer()], may_choose: true });

    await offerButton(wrapper, "عرض الإفطار").trigger("click");
    await flushPromises();

    // The fifth argument is the points being spent — none here (`D-189`).
    expect(paymentApi.previewTotals).toHaveBeenCalledWith(ORDER, null, 0, "PROMO-001", 0);
  });

  /**
   * The permission is reported with the list so the screen says so **before**
   * a choice is made, rather than letting a cashier tell the customer a price
   * the server then refuses (`D-125`).
   */
  it("is not tappable by a cashier without the right", async () => {
    const wrapper = await open(summary(), { offers: [offer()], may_choose: false });

    const button = offerButton(wrapper, "عرض الإفطار").element as HTMLButtonElement;

    expect(button.disabled).toBe(true);
  });

  it("carries the choice into the payment", async () => {
    vi.mocked(paymentApi.previewTotals).mockResolvedValue({
      subtotal: 100,
      discount_amount: 10,
      promotion_amount: 10,
      promotion_title: "Breakfast offer",
      promotion_title_ar: "عرض الإفطار",
      tax_amount: 13.5,
      total_amount: 90,
      discount_percentage: 0,
      max_discount_percentage: 20,
      requires_override: false,
    });
    vi.mocked(paymentApi.processPayment).mockResolvedValue({
      order_name: ORDER,
      sales_invoice: "ACC-SINV-2026-00001",
      change: 0,
    } as never);
    const wrapper = await open(summary(), { offers: [offer()], may_choose: true });

    await offerButton(wrapper, "عرض الإفطار").trigger("click");
    await flushPromises();
    await tender(wrapper, "نقد");
    await confirmButton(wrapper).click();
    await flushPromises();

    expect(vi.mocked(paymentApi.processPayment).mock.calls[0][0]).toMatchObject({
      promotion: "PROMO-001",
    });
  });

  it("draws nothing at all when this bill qualifies for none", async () => {
    const wrapper = await open(summary(), { offers: [], may_choose: true });

    expect(wrapper.text()).not.toContain("عروض على هذي الفاتورة");
  });
});

/**
 * `FR-10.5`, `D-189`. The server sends the most this bill can take; the button
 * offers exactly that, and the payment carries exactly what was chosen. The
 * server refuses anything else under a lock — these ask whether the screen ever
 * lets a cashier promise a guest something it would refuse.
 */
describe("loyalty points on the bill", () => {
  function pointsOffer(extra: Partial<LoyaltyOffer> = {}): LoyaltyOffer {
    return {
      balance: 400,
      worth: 20,
      point_value: 0.05,
      min_points: 100,
      max_points: 250,
      max_amount: 12.5,
      ...extra,
    };
  }

  function priced(offer: LoyaltyOffer) {
    return {
      subtotal: 100,
      discount_amount: 12.5,
      promotion_amount: 0,
      promotion_title: "",
      promotion_title_ar: "",
      loyalty_points: 250,
      loyalty_amount: 12.5,
      loyalty: offer,
      tax_amount: 11.41,
      total_amount: 87.5,
      discount_percentage: 0,
      max_discount_percentage: 20,
      requires_override: false,
    };
  }

  function pointsButton(wrapper: Wrapper) {
    return wrapper.find("[data-loyalty]");
  }

  it("draws nothing on a bill outside the scheme", async () => {
    const wrapper = await open(summary({ loyalty: null }));

    expect(pointsButton(wrapper).exists()).toBe(false);
    expect(wrapper.text()).not.toContain("نقاط الولاء");
  });

  it("previews and pays with exactly the points the server offered", async () => {
    vi.mocked(paymentApi.previewTotals).mockResolvedValue(priced(pointsOffer()));
    vi.mocked(paymentApi.processPayment).mockResolvedValue({ order_name: ORDER } as never);
    const wrapper = await open(summary({ loyalty: pointsOffer() }));

    await pointsButton(wrapper).trigger("click");
    await flushPromises();
    await tender(wrapper, "نقد");
    await confirmButton(wrapper).click();
    await flushPromises();

    expect(vi.mocked(paymentApi.previewTotals)).toHaveBeenLastCalledWith(ORDER, null, 0, null, 250);
    expect(vi.mocked(paymentApi.processPayment).mock.calls[0][0]).toMatchObject({
      loyalty_points_redeemed: 250,
    });
  });

  it("spends nothing once the cashier taps it again", async () => {
    vi.mocked(paymentApi.previewTotals).mockResolvedValue(priced(pointsOffer()));
    vi.mocked(paymentApi.processPayment).mockResolvedValue({ order_name: ORDER } as never);
    const wrapper = await open(summary({ loyalty: pointsOffer() }));
    await pointsButton(wrapper).trigger("click");
    await flushPromises();
    await pointsButton(wrapper).trigger("click");
    await flushPromises();
    await tender(wrapper, "نقد");
    await confirmButton(wrapper).click();
    await flushPromises();

    expect(vi.mocked(paymentApi.processPayment).mock.calls[0][0]).toMatchObject({
      loyalty_points_redeemed: 0,
    });
  });

  it("brings the points down when the bill can take fewer than were chosen", async () => {
    // A discount chosen after the points leaves less for them to pay: the
    // server says 100 now, and the screen must not carry 250 to Confirm.
    vi.mocked(paymentApi.previewTotals).mockResolvedValue(
      priced(pointsOffer({ max_points: 100, max_amount: 5 })),
    );
    const wrapper = await open(summary({ loyalty: pointsOffer() }));

    await pointsButton(wrapper).trigger("click");
    await flushPromises();

    expect(vi.mocked(paymentApi.previewTotals)).toHaveBeenLastCalledWith(ORDER, null, 0, null, 100);
  });

  it("says why there is no button when the balance is below the minimum", async () => {
    const wrapper = await open(
      summary({ loyalty: pointsOffer({ balance: 50, worth: 2.5, max_points: 0, max_amount: 0 }) }),
    );

    expect(pointsButton(wrapper).exists()).toBe(false);
    expect(wrapper.text()).toContain("تُستخدم النقاط من");
  });
});

describe("paying with a gift card", () => {
  it("asks which card before offering an amount to take", async () => {
    // `D-256` — a card is the one method whose limit the cashier cannot see.
    // Tapping it must open the lookup, not the tender keypad: an amount taken
    // first would be refused at Confirm, after the guest was told a figure.
    vi.mocked(giftCardApi.lookupGiftCard).mockResolvedValue({
      gift_card: "GC-1",
      card_number: "GC1",
      balance: 40,
      expires_on: null,
    });
    const wrapper = await open(
      summary({ payment_methods: [method("بطاقة هدايا", { is_gift_card: 1 })] }),
    );

    await methodButton(wrapper, "بطاقة هدايا").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("رقم البطاقة");
  });
});
