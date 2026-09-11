// @vitest-environment jsdom

/**
 * The day's bookings, and only the buttons the server will accept (`D-191`).
 *
 * The same question the payment screen's tests ask (`D-125`): is a control the
 * host can reach a control the server will honour? Seating tomorrow's booking,
 * or marking a guest a no-show at five to eight for eight o'clock, are both
 * refused by the server — and a host who is refused after telling a guest
 * "your table is ready" has been let down by the screen, not the rule.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { reactive } from "vue";

import * as reservationApi from "@/api/reservation";
import type { Reservation } from "@/api/reservation";
import ReasonDialog from "@/components/order/ReasonDialog.vue";
import ReservationsPane from "@/components/order/ReservationsPane.vue";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

vi.mock("@/api/reservation", () => ({
  listReservations: vi.fn(),
  saveReservation: vi.fn(),
  seatReservation: vi.fn(),
  cancelReservation: vi.fn(),
  markNoShow: vi.fn(),
}));
vi.mock("@/api/customer", () => ({ searchCustomers: vi.fn() }));
vi.mock("@/api/table", () => ({ getFloorPlan: vi.fn() }));

// A store-shaped object the test can take offline, so these tests depend on
// what the pane reads — `isOnline` — and not on how the store decides it.
const connection = reactive({ isOnline: true });
vi.mock("@/stores/connection", () => ({ useConnectionStore: () => connection }));

function isoToday(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function booking(extra: Partial<Reservation> = {}): Reservation {
  return {
    name: "RES-1",
    customer_name: "Hamza",
    phone: "0501234567",
    party_size: 4,
    customer: null,
    reservation_date: isoToday(),
    reservation_time: "20:00",
    section: "Main Hall",
    table: "T-4",
    table_number: "4",
    status: "confirmed",
    phase: "held",
    restaurant_order: null,
    notes: null,
    cancel_reason: null,
    auto_no_show: 0,
    created_by_name: "Noura",
    ...extra,
  };
}

async function open(rows: Reservation[]) {
  vi.mocked(reservationApi.listReservations).mockResolvedValue(rows);
  const wrapper = mount(ReservationsPane, { global: { stubs: { teleport: true } } });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  connection.isOnline = true;
  useSessionStore().data = { pos_profile: { name: "T1" }, sections: [] } as unknown as PosSession;
});

describe("the day's bookings", () => {
  it("asks the server for today's, on this terminal", async () => {
    await open([]);

    expect(reservationApi.listReservations).toHaveBeenCalledWith("T1", isoToday());
  });

  it("hands a booking up to be seated rather than seating it here", async () => {
    // One place decides which kind of order opens on a table (`D-191`), and it
    // is not this pane.
    const wrapper = await open([booking()]);

    await wrapper.find("[data-seat]").trigger("click");

    expect(wrapper.emitted("seat")?.[0]?.[0]).toMatchObject({ name: "RES-1" });
    expect(reservationApi.seatReservation).not.toHaveBeenCalled();
  });

  it("offers no seat for a booking without a table", async () => {
    const wrapper = await open([booking({ table: null, table_number: null })]);

    expect(wrapper.find("[data-seat]").exists()).toBe(false);
  });

  it("offers no seat once the host is looking at another day", async () => {
    // The server seats today's bookings only. The list follows the day being
    // looked at — a row's own date is whatever the server sent for that day —
    // so the rule is about the day on screen.
    const wrapper = await open([booking()]);
    expect(wrapper.find("[data-seat]").exists()).toBe(true);

    const next = wrapper
      .findAll("button")
      .find((button) => button.attributes("aria-label") === "اليوم التالي");
    if (!next) throw new Error("no next-day button");
    await next.trigger("click");
    await flushPromises();

    expect(wrapper.find("[data-seat]").exists()).toBe(false);
  });

  it("offers nothing to do on a booking no longer expected", async () => {
    const wrapper = await open([booking({ status: "seated", phase: null })]);

    expect(wrapper.find("[data-seat]").exists()).toBe(false);
    expect(wrapper.find("[data-cancel]").exists()).toBe(false);
  });
});

describe("cancelling and missing", () => {
  it("asks for a reason and sends it", async () => {
    vi.mocked(reservationApi.cancelReservation).mockResolvedValue({ status: "cancelled" });
    const wrapper = await open([booking()]);

    await wrapper.find("[data-cancel]").trigger("click");
    // The dialog renders once more as it settles, and an input captured before
    // that is a node no longer on the page: typing into it reaches nothing,
    // and the confirm button stays disabled. Everything below is read from the
    // page as it now stands — which is what a cashier's finger touches.
    await flushPromises();

    await wrapper.find('[role="dialog"] input').setValue("the guest called");

    const confirm = wrapper
      .find('[role="dialog"]')
      .findAll("button")
      .find((button) => button.text() === "إلغاء الحجز");
    if (!confirm) throw new Error("no confirm button in the reason dialog");
    // A disabled button swallows the click silently; say which step broke.
    expect((confirm.element as HTMLButtonElement).disabled).toBe(false);
    await confirm.trigger("click");
    await flushPromises();

    expect(wrapper.findComponent(ReasonDialog).emitted("confirm")).toEqual([["the guest called"]]);

    expect(reservationApi.cancelReservation).toHaveBeenCalledWith("RES-1", "the guest called");
  });

  it("offers no-show only once the booking is late", async () => {
    const wrapper = await open([booking({ phase: "held" })]);

    expect(wrapper.find("[data-no-show]").exists()).toBe(false);
  });

  it("marks a late booking as a no-show", async () => {
    vi.mocked(reservationApi.markNoShow).mockResolvedValue({ status: "no_show" });
    const wrapper = await open([booking({ phase: "late" })]);

    await wrapper.find("[data-no-show]").trigger("click");
    await flushPromises();

    expect(reservationApi.markNoShow).toHaveBeenCalledWith("RES-1");
  });
});

describe("without a connection", () => {
  it("says so and asks the server nothing", async () => {
    connection.isOnline = false;

    const wrapper = await open([booking()]);

    expect(reservationApi.listReservations).not.toHaveBeenCalled();
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
  });
});
