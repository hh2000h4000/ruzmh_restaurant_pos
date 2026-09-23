// @vitest-environment jsdom

/**
 * Saying a table is wiped down (`D-242`).
 *
 * `cleaning` was a one-way door: the server set it when the last bill was paid
 * and nothing on the till could clear it, so a table that took one order was
 * out of service until somebody opened the desk. The user found it with three
 * tables on the floor and two of them stuck.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FloorTable } from "@/api/table";
import TableReadyDialog from "@/components/order/TableReadyDialog.vue";

const setTableStatus = vi.fn();

vi.mock("@/api/table", () => ({
  setTableStatus: (...args: unknown[]) => setTableStatus(...args),
}));

const TABLE = {
  name: "T-2",
  table_number: "2",
  status: "cleaning",
  capacity: 4,
  shape: null,
  current_order: null,
  orders: [],
} satisfies FloorTable;

function dialog(table: FloorTable | null = TABLE) {
  return mount(TableReadyDialog, {
    props: { table },
    global: { stubs: { teleport: true } },
  });
}

describe("a table waiting to be cleaned", () => {
  beforeEach(() => {
    setTableStatus.mockReset();
    setTableStatus.mockResolvedValue({ table: "T-2", status: "available" });
  });

  it("names the table it is asking about", () => {
    expect(dialog().text()).toContain("2");
  });

  it("frees the table and tells the screen to redraw", async () => {
    const view = dialog();

    await view.findAll("button")[1].trigger("click");
    await flushPromises();

    expect(setTableStatus).toHaveBeenCalledWith("T-2", "available");
    expect(view.emitted("done")).toHaveLength(1);
  });

  it("shows the server's refusal rather than a guess of its own", async () => {
    setTableStatus.mockRejectedValue(new Error("Table T-2 still has an open order."));
    const view = dialog();

    await view.findAll("button")[1].trigger("click");
    await flushPromises();

    expect(view.text()).toContain("still has an open order");
    expect(view.emitted("done")).toBeUndefined();
  });

  it("stays shut with no table to ask about", () => {
    expect(dialog(null).find("[role=dialog]").exists()).toBe(false);
  });
});
