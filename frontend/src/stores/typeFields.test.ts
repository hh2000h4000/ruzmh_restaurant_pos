/**
 * `D-409` — an order type's own questions are asked before the server is.
 *
 * A shipped delivery platform requires "App Order No" when an order opens, and
 * the till never asked: every order under it was refused for a field nobody had
 * been offered, on opening and on converting.
 */
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OrderDetail } from "@/api/order";
import * as orderApi from "@/api/order";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";
import { useTypeFieldsStore } from "@/stores/typeFields";
import type { OrderType, OrderTypeField, PosSession } from "@/types/session";

vi.mock("@/api/order", () => ({
  createOrder: vi.fn(),
  changeOrderType: vi.fn(),
  getOrder: vi.fn(),
}));

vi.mock("@/stores/alerts", () => {
  const refresh = vi.fn();
  return { useAlertsStore: () => ({ refresh }) };
});

const NUMBER: OrderTypeField = {
  label: "App Order No",
  label_ar: "رقم الطلب في التطبيق",
  type: "text",
  options: [],
  is_required: 1,
  show_at: "on_open",
  placeholder: "HS-29541",
};

function type(name: string, fields: OrderType["additional_fields"] = []): OrderType {
  return { name, title: name, title_ar: name, additional_fields: fields } as unknown as OrderType;
}

const HUNGER = type("OT-HUNGER", [NUMBER]);
const TAKEAWAY = type("OT-TAKEAWAY");

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  useSessionStore().data = {
    order_types: [HUNGER, TAKEAWAY],
    profile: { name: "Terminal 1" },
  } as unknown as PosSession;
  vi.mocked(orderApi.getOrder).mockResolvedValue({ order_name: "RO-1", items: [] } as unknown as OrderDetail);
});

describe("asking", () => {
  it("answers at once for a type with nothing to ask", async () => {
    await expect(useTypeFieldsStore().ask(TAKEAWAY)).resolves.toEqual({});
    expect(useTypeFieldsStore().asking).toBeNull();
  });

  it("waits for the cashier, and leaves the closing questions for the closing", async () => {
    const closing: OrderTypeField = { ...NUMBER, label: "Driver", show_at: "on_close" };
    const fields = useTypeFieldsStore();

    const answer = fields.ask(type("OT-X", [NUMBER, closing]));

    expect(fields.asking?.fields.map((field) => field.label)).toEqual(["App Order No"]);
    fields.answer({ "App Order No": "29541" });
    await expect(answer).resolves.toEqual({ "App Order No": "29541" });
    expect(fields.asking).toBeNull();
  });
});

describe("opening a bill under a type that asks", () => {
  it("sends what was typed with the order", async () => {
    vi.mocked(orderApi.createOrder).mockResolvedValue({ order_name: "RO-1" } as never);
    const opened = useOrderStore().create({ order_type: HUNGER.name, pos_profile: "Terminal 1" });

    useTypeFieldsStore().answer({ "App Order No": "29541" });

    await expect(opened).resolves.toBe("RO-1");
    expect(orderApi.createOrder).toHaveBeenCalledWith(
      expect.objectContaining({ order_type: HUNGER.name, order_type_data: { "App Order No": "29541" } }),
    );
  });

  it("opens nothing when the cashier backs out", async () => {
    const opened = useOrderStore().create({ order_type: HUNGER.name, pos_profile: "Terminal 1" });

    useTypeFieldsStore().answer(null);

    await expect(opened).resolves.toBeNull();
    expect(orderApi.createOrder).not.toHaveBeenCalled();
    expect(useOrderStore().error).toBeNull();
  });

  it("asks nothing of a type with nothing to ask", async () => {
    vi.mocked(orderApi.createOrder).mockResolvedValue({ order_name: "RO-1" } as never);

    await useOrderStore().create({ order_type: TAKEAWAY.name, pos_profile: "Terminal 1" });

    expect(useTypeFieldsStore().asking).toBeNull();
    expect(orderApi.createOrder).toHaveBeenCalledWith(expect.objectContaining({ order_type_data: {} }));
  });
});

describe("turning a bill into a type that asks", () => {
  it("sends what was typed with the change (`D-408`)", async () => {
    vi.mocked(orderApi.changeOrderType).mockResolvedValue({ order_type: HUNGER.name, changed: true } as never);
    const orders = useOrderStore();
    orders.order = { order_name: "RO-1", order_type: TAKEAWAY.name, items: [] } as unknown as OrderDetail;

    const changed = orders.changeType(HUNGER.name);
    useTypeFieldsStore().answer({ "App Order No": "29541" });

    await expect(changed).resolves.toBe(true);
    expect(orderApi.changeOrderType).toHaveBeenCalledWith(
      expect.objectContaining({ order_type: HUNGER.name, order_type_data: { "App Order No": "29541" } }),
    );
  });

  it("changes nothing when the cashier backs out", async () => {
    const orders = useOrderStore();
    orders.order = { order_name: "RO-1", order_type: TAKEAWAY.name, items: [] } as unknown as OrderDetail;

    const changed = orders.changeType(HUNGER.name);
    useTypeFieldsStore().answer(null);

    await expect(changed).resolves.toBe(false);
    expect(orderApi.changeOrderType).not.toHaveBeenCalled();
  });
});
