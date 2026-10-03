// @vitest-environment jsdom

/**
 * The bell's list (`D-298`): twenty at a time, newest first, and each ticket
 * still waiting can be printed again or answered for by hand.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as kitchenApi from "@/api/kitchen";
import type { PrintAlert, PrintAlerts } from "@/api/kitchen";
import AlertsPane from "@/components/order/AlertsPane.vue";
import { t } from "@/i18n";
import { useAlertsStore } from "@/stores/alerts";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

vi.mock("@/api/kitchen", () => ({
  getPrintAlerts: vi.fn(),
  markKitchenTold: vi.fn(),
  reprintKot: vi.fn(),
}));

vi.mock("@/stores/connection", () => ({ useConnectionStore: () => ({ isOnline: true }) }));

function alert(over: Partial<PrintAlert> = {}): PrintAlert {
  return {
    kot_name: "KOT-2026-10-00001",
    restaurant_order: "RO-2026-10-00001",
    daily_number: 7,
    call_name: null,
    table_number: null,
    station: "Grill",
    station_ar: "المشاوي",
    failed_at: "2026-10-03 13:00:00",
    state: "failed",
    ...over,
  };
}

function answer(alerts: PrintAlert[], over: Partial<PrintAlerts> = {}): PrintAlerts {
  return { open: alerts.filter((row) => row.state === "failed").length, alerts, more: false, page: 20, ...over };
}

async function pane(mayReprint = true) {
  const wrapper = mount(AlertsPane, { props: { mayReprint } });
  await flushPromises();
  return wrapper;
}

function button(wrapper: Awaited<ReturnType<typeof pane>>, label: string) {
  const found = wrapper.findAll("button").find((node) => node.text() === label);
  if (!found) throw new Error(`no button "${label}"`);
  return found;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  useSessionStore().data = { pos_profile: { name: "RPOS Till" } } as unknown as PosSession;
});

describe("the bell's list", () => {
  it("names the station and sets the badge from the server's count", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert()]));

    const wrapper = await pane();

    expect(wrapper.text()).toContain(t("alerts.ticket", { station: "المشاوي" }));
    expect(wrapper.text()).toContain(t("alerts.state.failed"));
    expect(useAlertsStore().open).toBe(1);
  });

  it("answers for a ticket by hand, then reads the list again", async () => {
    vi.mocked(kitchenApi.getPrintAlerts)
      .mockResolvedValueOnce(answer([alert()]))
      .mockResolvedValueOnce(answer([alert({ state: "told" })]));
    vi.mocked(kitchenApi.markKitchenTold).mockResolvedValue({ kot_name: "KOT-2026-10-00001", state: "told" });
    const wrapper = await pane();

    await button(wrapper, t("alerts.told")).trigger("click");
    await flushPromises();

    expect(kitchenApi.markKitchenTold).toHaveBeenCalledWith("KOT-2026-10-00001");
    expect(wrapper.text()).toContain(t("alerts.state.told"));
    expect(useAlertsStore().open).toBe(0);
  });

  it("offers no reprint to a cashier who may not, and still lets them answer", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert()]));

    const labels = (await pane(false)).findAll("button").map((node) => node.text());

    expect(labels).not.toContain(t("order.reprintTicket"));
    expect(labels).toContain(t("alerts.told"));
  });

  it("asks for the older twenty only when told to, and can come back", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert()], { more: true }));
    const wrapper = await pane();

    await button(wrapper, t("alerts.older")).trigger("click");
    await flushPromises();
    expect(kitchenApi.getPrintAlerts).toHaveBeenLastCalledWith("RPOS Till", 20);

    await button(wrapper, t("alerts.newer")).trigger("click");
    await flushPromises();
    expect(kitchenApi.getPrintAlerts).toHaveBeenLastCalledWith("RPOS Till", 0);
  });

  it("says so when there is nothing to show", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([]));

    expect((await pane()).text()).toContain(t("alerts.none"));
  });
});
