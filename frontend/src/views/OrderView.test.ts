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
import type { DisplayState } from "@/composables/useCustomerDisplay";
import { useSessionStore } from "@/stores/session";
import type { CatalogItem, OrderType, PosSession } from "@/types/session";
import OrderView from "@/views/OrderView.vue";

const ORDER = "RO-2026-09-00001";
const DISH = "RPOS-BURGER";
const TAKEAWAY = "سفري";

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: {}, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/api/activity", () => ({ recordView: vi.fn(), listActivity: vi.fn() }));

/** Whatever the till pushed to the customer's screen, newest last (`D-202`). */
const published: DisplayState[] = [];

// `BroadcastChannel` is absent in jsdom, so the real publisher would swallow
// everything and prove nothing about what the till decided to send.
vi.mock("@/composables/useCustomerDisplay", async (importActual) => ({
  ...(await importActual<typeof import("@/composables/useCustomerDisplay")>()),
  useCustomerDisplayPublisher: () => ({
    publish: (state: DisplayState) => published.push(state),
  }),
}));

// The calls that reach the server are stubbed; everything else in the module
// stays real. `reductionsOn` is pure arithmetic on a payload (`D-163`) and a
// stub of it would be this file asserting against its own copy of the rule.
vi.mock("@/api/order", async (importActual) => ({
  ...(await importActual<typeof import("@/api/order")>()),
  listOrders: vi.fn(),
  createOrder: vi.fn(),
  getOrder: vi.fn(),
  addItem: vi.fn(),
}));

const totals = {
  status: "active",
  subtotal: 0,
  discount_amount: 0,
  promotion_amount: 0,
  promotion_title: "",
  promotion_title_ar: "",
  tax_amount: 0,
  total_amount: 0,
};

function orderType(extra: Partial<OrderType> = {}): OrderType {
  return {
    name: "OT-TAKEAWAY",
    title: "Takeaway",
    title_ar: TAKEAWAY,
    icon: null,
    counterparty: "walk_in",
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

/** Two kinds of order, which is what makes the till ask which (`D-353`). */
const TWO_TYPES = [orderType(), orderType({ name: "OT-DELIVERY", title: "Delivery", title_ar: "توصيل" })];

/** A till with a drawer open, a restaurant's order types and one dish on the menu. */
function till(items: CatalogItem[] = [dish()], types: OrderType[] = TWO_TYPES): void {
  useSessionStore().data = {
    can_sell: true,
    order_types: types,
    items,
    item_groups: [{ name: GROUP, item_group_name: "برجر" }],
    screen_layout: null,
    pos_profile: { name: "T1" },
    permissions: {},
  } as unknown as PosSession;
}

async function open() {
  const wrapper = mount(OrderView, { global: { stubs: { RouterLink: true, teleport: true } } });
  await flushPromises();
  return wrapper;
}

type Wrapper = Awaited<ReturnType<typeof open>>;

/** A nav or type button, matched on the label a cashier reads. */
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
    ...totals,
    order_name: ORDER,
    order_type: "OT-TAKEAWAY",
    status: "draft",
    items: [],
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

    await itemButton(wrapper, TAKEAWAY).trigger("click");
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
    await itemButton(wrapper, TAKEAWAY).trigger("click");
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
    await itemButton(wrapper, TAKEAWAY).trigger("click");
    await flushPromises();

    expect(orderApi.createOrder).toHaveBeenCalledOnce();
    expect(orderApi.addItem).not.toHaveBeenCalled();
  });
});

/**
 * `D-353` — a supermarket's till has one kind of order, so "which kind?" has
 * one answer and is not asked: the first thing rung or scanned opens the bill.
 */
describe("a terminal that sells one kind of order", () => {
  it("opens the bill on the first dish, without asking which kind", async () => {
    till([dish()], [orderType()]);
    const wrapper = await open();

    await tapDish(wrapper, "برجر", "برغر");

    expect(orderApi.createOrder).toHaveBeenCalledOnce();
    expect(orderApi.createOrder).toHaveBeenCalledWith(expect.objectContaining({ order_type: "OT-TAKEAWAY" }));
    expect(orderApi.addItem).toHaveBeenCalledWith(
      expect.objectContaining({ order_name: ORDER, item: DISH, qty: 1 }),
    );
  });

  it("opens one from New as well", async () => {
    till([dish()], [orderType()]);
    const wrapper = await open();

    await button(wrapper, "جديد").trigger("click");
    await flushPromises();

    expect(orderApi.createOrder).toHaveBeenCalledOnce();
  });

  it("still asks what its one kind needs — a customer, here", async () => {
    till([dish()], [orderType({ customer_mode: "required" } as Partial<OrderType>)]);
    const wrapper = await open();

    await tapDish(wrapper, "برجر", "برغر");

    // The picker is up and nothing was created behind it.
    expect(orderApi.createOrder).not.toHaveBeenCalled();
  });
});

/**
 * `D-202` — the screen facing the room loads no session of its own, so whatever
 * it shows the till has to send. This is the seam where that happens.
 */
describe("what the till tells the customer's screen", () => {
  it("sends the logo and the message it was given with the menu", async () => {
    till();
    const session = useSessionStore();
    session.data = {
      ...session.data,
      branch: { branch: "فرع الزيتون" },
      theme: { brand_logo: "/files/logo.png" },
      customer_display: {
        message: "وجبة الغداء ٤٩ ريالاً",
        banners: ["/files/offer-1.png"],
        seconds: 12,
      },
    } as never;
    published.length = 0;

    await open();

    expect(published.at(-1)).toMatchObject({
      mode: "idle",
      house: "فرع الزيتون",
      logo: "/files/logo.png",
      message: "وجبة الغداء ٤٩ ريالاً",
      banners: ["/files/offer-1.png"],
      seconds: 12,
    });
  });

  it("sends nothing where the restaurant set nothing", async () => {
    till();
    published.length = 0;

    await open();

    expect(published.at(-1)).toMatchObject({ logo: null, message: "", banners: [] });
  });
});

/**
 * `D-193` — below a landscape tablet the bill folds into a bar and opens as a
 * sheet. Measured on a portrait iPad Mini, the stacked bill took 486px and left
 * the menu 387. jsdom lays nothing out, so these ask what the markup promises:
 * the sheet is shut until the bar opens it, and it shuts like every popover.
 */
describe("the bill on a narrow screen", () => {
  function sheet(wrapper: Wrapper) {
    return wrapper.find("[data-bill-sheet]");
  }

  it("folds into a bar whose Pay waits for something to pay", async () => {
    till();
    const wrapper = await open();

    expect(sheet(wrapper).classes()).toContain("max-lg:hidden");
    expect((wrapper.find("[data-bill-pay]").element as HTMLButtonElement).disabled).toBe(true);
  });

  it("opens as a sheet from the bar, and a tap outside folds it again", async () => {
    till();
    const wrapper = await open();

    await wrapper.find("[data-bill-toggle]").trigger("click");
    expect(sheet(wrapper).classes()).not.toContain("max-lg:hidden");
    expect(wrapper.find("[data-bill-toggle]").attributes("aria-expanded")).toBe("true");

    await wrapper.find("[data-bill-backdrop]").trigger("click");
    expect(sheet(wrapper).classes()).toContain("max-lg:hidden");
  });

  it("folds on Escape, like every popover (`D-176`)", async () => {
    till();
    // `useDismiss` listens on `document`, so the key reaches it with the screen
    // mounted anywhere.
    const wrapper = await open();

    await wrapper.find("[data-bill-toggle]").trigger("click");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await flushPromises();

    expect(sheet(wrapper).classes()).toContain("max-lg:hidden");
  });
});
