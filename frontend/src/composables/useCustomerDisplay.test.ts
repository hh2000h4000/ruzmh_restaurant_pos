// @vitest-environment jsdom

/**
 * What reaches the screen the room can read (`FR-13`, `D-162`).
 *
 * This is the one screen in the app **facing away from the staff**, so the
 * question it is tested on is not only "does it show the bill" but "what can it
 * possibly show". The answer is enforced by what crosses the channel rather
 * than by what the template happens to render: a field never sent cannot be
 * leaked by a later edit to the view.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OrderDetail, OrderLine } from "@/api/order";
import { isReactive, reactive } from "vue";

import {
  HELLO_EVERY_MS,
  IDLE,
  linkUp,
  NO_BRAND,
  received,
  sendable,
  toDisplayState,
} from "@/composables/useCustomerDisplay";

function line(extra: Partial<OrderLine> = {}): OrderLine {
  return {
    idx: 1,
    item: "RPOS-BURGER",
    item_name: "برغر",
    qty: 2,
    rate: 25,
    amount: 50,
    status: "pending",
    notes: null,
    modifiers: [],
    production_center: null,
    ...extra,
  } as OrderLine;
}

function bill(extra: Partial<OrderDetail> = {}): OrderDetail {
  return {
    order_name: "RO-2026-09-00042",
    status: "active",
    daily_number: 7,
    subtotal: 50,
    discount_amount: 0,
    promotion_amount: 0,
    promotion_title: "",
    promotion_title_ar: "",
    tax_amount: 6.52,
    total_amount: 50,
    cashier: "cashier@example.com",
    cashier_name: "سعيد الغامدي",
    table: "TBL-4",
    ...extra,
  } as OrderDetail;
}

describe("what the guest's screen is given", () => {
  /**
   * `D-202`. The display window asks the server for nothing, so everything it
   * shows has to arrive over the channel — the name did already, the logo and
   * the manager's message now do.
   */
  it("carries the logo and the manager's message, on a bill and while waiting", () => {
    const brand = { ...NO_BRAND, logo: "/files/logo.png", message: "وجبة الغداء ٤٩" };
    const shown = { logo: "/files/logo.png", message: "وجبة الغداء ٤٩" };

    expect(toDisplayState(bill(), [line()], brand)).toMatchObject(shown);
    expect(toDisplayState(null, [], brand)).toMatchObject({ mode: "idle", ...shown });
  });

  it("says nothing about a brand the till did not send", () => {
    expect(IDLE).toMatchObject({ house: "", logo: null, message: "", banners: [] });
  });

  /**
   * The two windows are refreshed at different moments, so the newer screen
   * will read an older till's message. It did, and `state.banners.length`
   * threw: **the render failed and the guest's bill vanished with it** — found
   * by the user on a till not yet refreshed after `D-203`.
   */
  it("fills out a message from a till that has not been refreshed yet", () => {
    const yesterday = {
      mode: "order" as const,
      house: "فرع الزيتون",
      lines: [{ name: "برغر", qty: 1, amount: 25, options: [] }],
      total: 25,
    };

    const state = received(yesterday);

    expect(state.banners).toEqual([]);
    expect(state.seconds).toBe(IDLE.seconds);
    expect(state.logo).toBeNull();
    // And nothing it did send is lost on the way through.
    expect(state.lines).toEqual(yesterday.lines);
    expect(state.total).toBe(25);
  });

  it("survives a message carrying no state at all", () => {
    expect(received(undefined)).toEqual(IDLE);
  });
});

/**
 * **The browser will not clone a `Proxy`**, and anything from a store is one.
 *
 * The bill's fields were built fresh every time and crossed fine, until the
 * banners began travelling straight out of the session store: from then on
 * every `postMessage` threw and the guest's screen received *nothing* — no
 * banners, no bill, not even the restaurant's name. The user found it; a state
 * posted by hand on the same channel arrived, which is what proved the channel
 * innocent.
 */
describe("what is safe to hand to another window", () => {
  it("sends a plain copy of a state held in a store", () => {
    const live = reactive({ ...IDLE, house: "فرع الزيتون", banners: ["/files/a.png"] });

    const copy = sendable(live);

    expect(isReactive(copy)).toBe(false);
    expect(isReactive(copy.banners)).toBe(false);
    expect(copy).toEqual({ ...IDLE, house: "فرع الزيتون", banners: ["/files/a.png"] });
  });

  it("hands over everything a structured clone would carry", () => {
    const state = toDisplayState(bill(), [line()], { ...NO_BRAND, banners: ["/files/a.png"] });

    expect(() => structuredClone(sendable(state))).not.toThrow();
    expect(sendable(state)).toEqual(state);
  });
});

/**
 * The handshake, which is where the guest's screen actually failed.
 *
 * It asked the till once, when it opened. A till reloading at that moment — or
 * a window the browser had frozen because nobody was looking at it — never
 * heard the question, and sends nothing again until the bill changes. The guest
 * reads a welcome screen while their order is being rung up.
 */
describe("asking the till what is on the bill", () => {
  function fakeBus() {
    const sent: unknown[] = [];
    const bus = {
      sent,
      postMessage: (message: unknown) => sent.push(message),
      onmessage: null as ((event: MessageEvent) => void) | null,
    };
    return bus;
  }

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("asks again until an answer comes, then stops asking", () => {
    const bus = fakeBus();
    const answers: unknown[] = [];

    linkUp(bus, (state) => answers.push(state));
    expect(bus.sent).toHaveLength(1);

    vi.advanceTimersByTime(HELLO_EVERY_MS * 2);
    expect(bus.sent.length).toBeGreaterThan(1);

    const asked = bus.sent.length;
    bus.onmessage?.({ data: { type: "state", state: { ...IDLE, house: "فرع الزيتون" } } } as MessageEvent);
    vi.advanceTimersByTime(HELLO_EVERY_MS * 3);

    expect(answers).toHaveLength(1);
    expect(bus.sent).toHaveLength(asked);
  });

  it("ignores anything that is not a state, and keeps asking", () => {
    const bus = fakeBus();
    const answers: unknown[] = [];

    linkUp(bus, (state) => answers.push(state));
    bus.onmessage?.({ data: { type: "hello" } } as MessageEvent);
    vi.advanceTimersByTime(HELLO_EVERY_MS);

    expect(answers).toHaveLength(0);
    expect(bus.sent.length).toBeGreaterThan(1);
  });

  /**
   * `D-163`. An offer the guest came in for is the thing they are checking this
   * screen for, and a bare "discount" line does not tell them it was honoured.
   */
  it("names the offer that was applied", () => {
    const state = toDisplayState(
      bill({
        discount_amount: 10,
        promotion_amount: 10,
        promotion_title: "Breakfast offer",
        promotion_title_ar: "عرض الإفطار",
      }),
      [line()],
    );

    expect(state.promotion).toEqual({ title: "عرض الإفطار", amount: 10 });
  });

  it("shows nothing but the house name when there is no bill", () => {
    expect(toDisplayState(null, [], { ...NO_BRAND, house: "فرع الرياض" })).toEqual({
      ...IDLE,
      house: "فرع الرياض",
    });
  });

  /**
   * The display window loads no session — it asks the server for nothing — so
   * its own stores are empty and reading the branch there left the header
   * blank. Found on the first real screen; the name travels with the bill.
   */
  it("carries the restaurant's name, because the other window cannot look it up", () => {
    expect(toDisplayState(bill(), [line()], { ...NO_BRAND, house: "فرع الرياض" }).house).toBe(
      "فرع الرياض",
    );
  });

  /**
   * VAT is inclusive here (`D-091`), so `subtotal` already contains the tax.
   * Printed beside the tax and the total it gave the guest `60.00 + 7.83 =
   * 60.00` — true, and unreadable as anything but a mistake. Derived from the
   * total, the three figures add up on the screen.
   */
  it("gives the guest three figures that add up", () => {
    const state = toDisplayState(bill({ total_amount: 60, tax_amount: 7.83 }), [line()]);

    expect(state.beforeTax).toBeCloseTo(52.17, 2);
    expect(state.beforeTax + state.tax).toBeCloseTo(state.total, 2);
  });

  it("carries the lines, the options and the totals", () => {
    const state = toDisplayState(bill(), [
      line({
        modifiers: [
          { group: "G", option: "No onion", option_ar: "بدون بصل", amount: 0 },
        ] as OrderLine["modifiers"],
      }),
    ]);

    expect(state.mode).toBe("order");
    expect(state.lines).toEqual([
      { name: "برغر", qty: 2, amount: 50, options: ["بدون بصل"] },
    ]);
    expect(state.total).toBe(50);
    expect(state.tax).toBe(6.52);
  });

  /**
   * **The point of the whole shape.** The room reads this screen: a cashier's
   * name, a document id or a terminal on it is a leak, and the way to be sure
   * is that they never leave the till.
   */
  it("carries nothing that identifies a person or a document", () => {
    const sent = JSON.stringify(toDisplayState(bill(), [line()]));

    expect(sent).not.toContain("RO-2026-09-00042");
    expect(sent).not.toContain("cashier@example.com");
    expect(sent).not.toContain("سعيد الغامدي");
    expect(sent).not.toContain("TBL-4");
  });

  /**
   * A line taken off is not part of what is owed. Leaving it on the guest's
   * screen is how somebody queries a total that is already right.
   */
  it("leaves a voided line off", () => {
    const state = toDisplayState(bill(), [
      line({ item_name: "برغر" }),
      line({ idx: 2, item_name: "بيبسي", status: "void" }),
    ]);

    expect(state.lines.map((row) => row.name)).toEqual(["برغر"]);
  });

  /**
   * `FR-2.10` — and this is the number's right home. It came off the orders
   * list because that list mixes days and the number restarts daily, so two
   * rows could read the same (`D-159`). Here there is one bill.
   */
  it("carries the number the guest will be called by", () => {
    expect(toDisplayState(bill(), [line()]).number).toBe(7);
  });

  it("has no number to show when the branch does not number bills", () => {
    expect(toDisplayState(bill({ daily_number: 0 }), [line()]).number).toBeNull();
  });
});
