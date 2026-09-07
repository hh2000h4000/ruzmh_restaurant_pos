// @vitest-environment jsdom

/**
 * Joining tables, from the till (`BR-063`, `D-160`).
 *
 * **A restaurant says "merge" for two different things**, and the danger is a
 * cashier reaching for the wrong one: joining *tables* leaves both bills alone
 * and gives one bill a second seat; merging *bills* empties one into the other
 * and closes it. A table that already carries a bill therefore has to be
 * visibly refused **here** and named as the other dialog's job — hiding it
 * teaches nothing, and a cashier who cannot find table 6 will look for it until
 * somebody tells them.
 *
 * The server refuses it too, and is the authority (`CLAUDE.md` §5.4). What
 * these hold is that the screen does not offer what the server will refuse.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as orderApi from "@/api/order";
import type { OrderDetail } from "@/api/order";
import * as tableApi from "@/api/table";
import type { FloorTable } from "@/api/table";
import JoinTablesDialog from "@/components/order/JoinTablesDialog.vue";
import { t } from "@/i18n";

vi.mock("@/api/table", () => ({ getFloorPlan: vi.fn() }));
vi.mock("@/api/order", () => ({ mergeTables: vi.fn() }));

function table(extra: Partial<FloorTable> = {}): FloorTable {
  return {
    name: "TBL-5",
    table_number: "5",
    status: "available",
    capacity: 4,
    shape: null,
    current_order: null,
    orders: [],
    ...extra,
  } as FloorTable;
}

const SEATED: Partial<OrderDetail> = {
  order_name: "RO-2026-09-00001",
  table: "TBL-4",
  tables: ["TBL-4"],
  section: "SEC-01",
};

async function open(tables: FloorTable[], order: Partial<OrderDetail> = SEATED) {
  vi.mocked(tableApi.getFloorPlan).mockResolvedValue({ tables } as never);

  const wrapper = mount(JoinTablesDialog, {
    props: { open: false, order: order as OrderDetail },
    global: { stubs: { teleport: true } },
  });
  await wrapper.setProps({ open: true });
  await flushPromises();

  return wrapper;
}

type Wrapper = Awaited<ReturnType<typeof open>>;

/** A table's button, found by the number a cashier reads on the floor. */
const seat = (wrapper: Wrapper, number: string) =>
  wrapper.findAll("button").find((button) => button.text().startsWith(number))!;

/** The button that commits; the one before it goes back. */
const join = (wrapper: Wrapper) => wrapper.findAll("button").at(-1)!;

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("choosing tables to join", () => {
  it("offers the free ones and joins what was chosen", async () => {
    const wrapper = await open([table(), table({ name: "TBL-6", table_number: "6" })]);

    await seat(wrapper, "5").trigger("click");
    await seat(wrapper, "6").trigger("click");
    await join(wrapper).trigger("click");
    await flushPromises();

    expect(orderApi.mergeTables).toHaveBeenCalledWith({
      order_name: "RO-2026-09-00001",
      tables: ["TBL-5", "TBL-6"],
    });
  });

  it("does not offer the table the bill is already on", async () => {
    const wrapper = await open([table({ name: "TBL-4", table_number: "4" }), table()]);

    expect(seat(wrapper, "4")).toBeUndefined();
    expect(seat(wrapper, "5")).toBeDefined();
  });

  /**
   * Shown and refused, not hidden. The cashier came looking for this table, and
   * the sentence on it is the one that sends them to the right action.
   */
  it("shows a table that has a bill, disabled and saying so", async () => {
    const wrapper = await open([
      table({ status: "occupied", orders: [{ name: "RO-2026-09-00002" }] as never }),
    ]);

    const taken = seat(wrapper, "5");
    expect(taken.attributes("disabled")).toBeDefined();
    expect(taken.text()).toContain(t("tables.joinHasBill"));
  });

  it("will not commit with nothing chosen", async () => {
    const wrapper = await open([table()]);

    expect(join(wrapper).attributes("disabled")).toBeDefined();
  });

  it("says so when the hall has nothing free to join", async () => {
    const wrapper = await open([table({ name: "TBL-4", table_number: "4" })]);

    expect(wrapper.text()).toContain(t("tables.joinEmpty"));
  });

  /**
   * `CLAUDE.md` §5.4 — the server is the authority on every rule here, so its
   * sentence is what the cashier reads. A screen that invented its own would
   * eventually disagree with the refusal.
   */
  it("shows the server's refusal rather than one of its own", async () => {
    const wrapper = await open([table()]);
    vi.mocked(orderApi.mergeTables).mockRejectedValue(
      new Error("Table TBL-5 already has a bill on it. Merge the bills instead."),
    );

    await seat(wrapper, "5").trigger("click");
    await join(wrapper).trigger("click");
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain("Merge the bills instead");
  });
});
