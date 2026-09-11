// @vitest-environment jsdom

/**
 * A held table asks before anybody sits at it (`D-191`).
 *
 * The server does not refuse a walk-in on a table held for a booking — the
 * party may have cancelled by phone — so the whole protection is on this
 * screen: the cashier is told, and chooses. A tap that seated a stranger on
 * table four at seven, with the booked party due at eight, would be the host's
 * first complaint and nothing in the backend suite could see it.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as tableApi from "@/api/table";
import type { FloorTable } from "@/api/table";
import FloorPane from "@/components/order/FloorPane.vue";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

vi.mock("@/api/table", () => ({ getFloorPlan: vi.fn() }));

const HALL = "Main Hall";

function table(extra: Partial<FloorTable> = {}): FloorTable {
  return {
    name: "T-4",
    table_number: "4",
    status: "available",
    capacity: 4,
    shape: null,
    current_order: null,
    orders: [],
    reservation: null,
    ...extra,
  };
}

const HELD = {
  name: "RES-2026-09-00001",
  guest: "Hamza",
  party_size: 4,
  time: "20:00",
  held: true,
};

async function open(rows: FloorTable[]) {
  vi.mocked(tableApi.getFloorPlan).mockResolvedValue({
    section: { name: HALL, title: HALL, title_ar: HALL },
    floor_plan: { canvas_width: 1200, canvas_height: 800 },
    tables: rows,
  });

  const wrapper = mount(FloorPane, { global: { stubs: { teleport: true } } });
  await flushPromises();
  return wrapper;
}

async function tapTable(wrapper: Awaited<ReturnType<typeof open>>) {
  const tile = wrapper.findAll("button").find((button) => button.text().includes("4"));
  if (!tile) throw new Error("no table 4 on the floor");
  await tile.trigger("click");
  await flushPromises();
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  useSessionStore().data = {
    restaurant_section: { name: HALL },
    sections: [],
  } as unknown as PosSession;
});

describe("a table held for a booking", () => {
  it("asks who is sitting down instead of seating anybody", async () => {
    const wrapper = await open([table({ status: "reserved", reservation: HELD })]);

    await tapTable(wrapper);

    expect(wrapper.find("[data-seat-booking]").exists()).toBe(true);
    expect(wrapper.emitted("seat")).toBeUndefined();
  });

  it("seats the booking when the booked party has arrived", async () => {
    const wrapper = await open([table({ status: "reserved", reservation: HELD })]);

    await tapTable(wrapper);
    await wrapper.find("[data-seat-booking]").trigger("click");

    expect(wrapper.emitted("seatBooking")).toEqual([[HELD.name, "4"]]);
    expect(wrapper.emitted("seat")).toBeUndefined();
  });

  it("still lets the cashier seat somebody else, having been told", async () => {
    const wrapper = await open([table({ status: "reserved", reservation: HELD })]);

    await tapTable(wrapper);
    await wrapper.find("[data-seat-other]").trigger("click");

    expect(wrapper.emitted("seat")).toHaveLength(1);
    expect(wrapper.emitted("seatBooking")).toBeUndefined();
  });
});

describe("a booking that is only a note", () => {
  it("seats a walk-in straight away — the table works until the hold begins", async () => {
    const wrapper = await open([table({ reservation: { ...HELD, held: false } })]);

    await tapTable(wrapper);

    expect(wrapper.find("[data-seat-booking]").exists()).toBe(false);
    expect(wrapper.emitted("seat")).toHaveLength(1);
  });

  it("is drawn on the table, even one with people at it", async () => {
    const wrapper = await open([
      table({
        status: "occupied",
        reservation: HELD,
        orders: [
          {
            name: "RO-1",
            daily_number: 12,
            status: "active",
            total_amount: 50,
            item_count: 2,
            opened_at: "2026-09-11 18:00:00",
          },
        ],
      }),
    ]);

    expect(wrapper.find("[data-booking]").text()).toContain("20:00");
  });
});
