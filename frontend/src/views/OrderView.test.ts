// @vitest-environment jsdom

/**
 * The tap that happens before there is a bill to put it on (`D-127`).
 *
 * A cashier with nothing in hand taps a dish. The screen has to ask which kind
 * of order this is — a table, a customer and a price list all hang off the
 * answer (`D-056`) — and the tap used to be thrown away while it asked, so the
 * same dish had to be found and tapped a second time.
 *
 * The fix half-worked at first: an item with modifier groups arrived and a
 * plain one vanished, because the replay reached the store while `create` was
 * still in flight and was dropped (`D-128`). **That is what this file is for.**
 * The user found the half that was broken; the gate could not.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as orderApi from "@/api/order";
import { useSessionStore } from "@/stores/session";
import type { CatalogItem, OrderType, SessionData } from "@/types/session";
import OrderView from "@/views/OrderView.vue";

const ORDER = "RO-2026-09-00001";
const DISH = "RPOS-BURGER";
const TAKEAWAY = "Takeaway";

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: {}, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/api/activity", () => ({ recordView: vi.fn(), listActivity: vi.fn() }));

vi.mock("@/api/order", () => ({
  listOrders: vi.fn(),
  createOrder: vi.fn(),
  getOrder: vi.fn(),
  addItem: vi.fn(),
}));

const totals = {
  status: "active",
  subtotal: 0,
  discount_amount: 0,
  tax_amount: 0,
  total_amount: 0,
};

function orderType(extra: Partial<OrderType> = {}): OrderType {
  return {
    name: TAKEAWAY,
    title: TAKEAWAY,
    requires_table: 0,
    requires_cover_count: 0,
    customer_mode: "optional",
    hidden_item_groups: [],
    ...extra,
  } as unknown as OrderType;
}

const GROUP = "burgers";

function dish(extra: Partial<CatalogItem> = {}): CatalogItem {
  return {
    item_code: DISH,
    item_name: "برغر",
    display_name: "برغر",
    item_group: GROUP,
    rate: 25,
    rates: {},
    modifier_groups: [],
    ...extra,
  } as unknown as CatalogItem;
}

/** A till with a drawer open, one order type and one dish on the menu. */
function till(items: CatalogItem[] = [dish()]): void {
  useSessionStore().data = {
    can_sell: true,
    order_types: [orderType()],
    items,
    item_groups: [{ name: GROUP, item_group_name: "برجر" }],
    screen_layout: null,
    pos_profile: { name: "T1" },
    permissions: {},
  } as unknown as SessionData;
}

async function open() {
  const wrapper = mount(OrderView, { global: { stubs: { RouterLink: true, teleport: true } } });
  await flushPromises();
  return wrapper;
}

type Wrapper = Awaited<ReturnType<typeof open>>;

function button(wrapper: Wrapper, label: string) {
  const found = wrapper.findAll("button").find((b) => b.text().trim() === label);
  if (found) return found;

  throw new Error(`no "${label}" on the screen`);
}

/** An item's button carries its price too, so it is matched by its name. */
function itemButton(wrapper: Wrapper, name: string) {
  const found = wrapper.findAll("button").find((b) => b.text().includes(name));
  if (found) return found;

  throw new Error(`no item called "${name}" on the screen`);
}

/** The menu opens on its groups; the dish is one drill-in below (`06` Screen 3). */
async function tapDish(wrapper: Wrapper, group: string, name: string) {
  await button(wrapper, group).trigger("click");
  await itemButton(wrapper, name).trigger("click");
  await flushPromises();
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();

  vi.mocked(orderApi.listOrders).mockResolvedValue([]);
  vi.mocked(orderApi.createOrder).mockResolvedValue({ order_name: ORDER } as never);
  vi.mocked(orderApi.getOrder).mockResolvedValue({
    order_name: ORDER,
    order_type: TAKEAWAY,
    status: "draft",
    items: [],
    ...totals,
  } as never);
  vi.mocked(orderApi.addItem).mockResolvedValue(totals as never);
});

describe("a dish tapped before there is a bill", () => {
  it("lands on the bill the question opened", async () => {
    till();
    const wrapper = await open();

    await tapDish(wrapper, "برجر", "برغر");

    // The screen asked which kind of order this is, and nothing was ordered yet.
    expect(orderApi.createOrder).not.toHaveBeenCalled();

    await button(wrapper, TAKEAWAY).trigger("click");
    await flushPromises();

    expect(orderApi.createOrder).toHaveBeenCalledOnce();
    expect(orderApi.addItem).toHaveBeenCalledWith(
      expect.objectContaining({ order_name: ORDER, item: DISH, qty: 1 }),
    );
  });

  /**
   * The half that was broken and shipped: a dish with options opened its popup
   * because the popup waits for the cashier, and by then the store was idle. A
   * plain dish went straight to the store, landed in the window `create` was
   * still holding, and was dropped without a word.
   */
  it("lands even when it is a plain dish with no options to ask about", async () => {
    till([dish({ modifier_groups: [] } as Partial<CatalogItem>)]);
    const wrapper = await open();

    await tapDish(wrapper, "برجر", "برغر");
    await button(wrapper, TAKEAWAY).trigger("click");
    await flushPromises();

    expect(orderApi.addItem).toHaveBeenCalledOnce();
  });

  it("forgets the dish when the cashier walks away from the question", async () => {
    till();
    const wrapper = await open();

    await tapDish(wrapper, "برجر", "برغر");

    // Off to the floor instead of answering: they changed their mind, and a
    // dish appearing on whatever bill they open next is worse than no dish.
    await button(wrapper, "الطاولات").trigger("click");
    await button(wrapper, "جديد").trigger("click");
    await button(wrapper, TAKEAWAY).trigger("click");
    await flushPromises();

    expect(orderApi.createOrder).toHaveBeenCalledOnce();
    expect(orderApi.addItem).not.toHaveBeenCalled();
  });
});
