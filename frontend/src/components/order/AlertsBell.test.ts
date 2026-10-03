// @vitest-environment jsdom

/**
 * The bell (`D-299`), to the user's design: a small button with an unread
 * count, a panel over the screen, twenty at a time, and a chime when a new
 * alert arrives — as the terminal is set (`D-301`).
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as kitchenApi from "@/api/kitchen";
import type { PrintAlert, PrintAlerts } from "@/api/kitchen";
import AlertsBell from "@/components/order/AlertsBell.vue";
import { t } from "@/i18n";
import { playTone } from "@/sound";
import { useAlertsStore } from "@/stores/alerts";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

vi.mock("@/api/kitchen", () => ({
  getPrintAlerts: vi.fn(),
  markKitchenTold: vi.fn(),
  reprintKot: vi.fn(),
}));

vi.mock("@/stores/connection", () => ({ useConnectionStore: () => ({ isOnline: true }) }));

vi.mock("@/sound", () => ({ playTone: vi.fn(), unlockSound: vi.fn() }));

const NOW = "2099-01-01 12:00:00";

function alert(over: Partial<PrintAlert> = {}): PrintAlert {
  return {
    kot_name: "KOT-1",
    restaurant_order: "RO-1",
    daily_number: 4,
    call_name: null,
    table_number: null,
    station: "Grill",
    station_ar: "المشاوي",
    failed_at: NOW,
    state: "failed",
    ...over,
  };
}

function answer(alerts: PrintAlert[], over: Partial<PrintAlerts> = {}): PrintAlerts {
  return { alerts, more: false, page: 20, ...over };
}

async function bell(mayReprint = true) {
  const wrapper = mount(AlertsBell, { props: { mayReprint }, attachTo: document.body });
  await useAlertsStore().refresh();
  await flushPromises();
  return wrapper;
}

async function opened(mayReprint = true) {
  const wrapper = await bell(mayReprint);
  await wrapper.get(`[aria-label="${t("alerts.title")}"]`).trigger("click");
  await flushPromises();
  return wrapper;
}

function button(wrapper: Awaited<ReturnType<typeof bell>>, label: string) {
  const found = wrapper.findAll("button").find((node) => node.text() === label);
  if (!found) throw new Error(`no button "${label}"`);
  return found;
}

beforeEach(() => {
  window.localStorage.clear();
  setActivePinia(createPinia());
  vi.clearAllMocks();
  useSessionStore().data = { pos_profile: { name: "RPOS Till" } } as unknown as PosSession;
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("the bell", () => {
  it("is quiet with nothing unread, and counts what is", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([]));
    expect((await bell()).text()).toBe("");

    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert(), alert({ kot_name: "KOT-2" })]));
    setActivePinia(createPinia());
    useSessionStore().data = { pos_profile: { name: "RPOS Till" } } as unknown as PosSession;
    expect((await bell()).text()).toBe("2");
  });

  it("opens over the screen with the station, the bill and what to do", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert()]));

    const text = (await opened()).text();

    expect(text).toContain(t("alerts.ticket", { station: "المشاوي" }));
    expect(text).toContain(t("alerts.order", { number: "4" }));
    expect(text).toContain(t("alerts.told"));
    expect(text).toContain(t("order.reprintTicket"));
  });

  it("tells the kitchen, and the alert is read after", async () => {
    vi.mocked(kitchenApi.getPrintAlerts)
      .mockResolvedValueOnce(answer([alert()])) // the till's own check
      .mockResolvedValueOnce(answer([alert()])) // opening the bell asks again
      .mockResolvedValue(answer([alert({ state: "told" })]));
    vi.mocked(kitchenApi.markKitchenTold).mockResolvedValue({ kot_name: "KOT-1", state: "told" });
    const wrapper = await opened();

    await button(wrapper, t("alerts.told")).trigger("click");
    await flushPromises();

    expect(kitchenApi.markKitchenTold).toHaveBeenCalledWith("KOT-1");
    expect(useAlertsStore().unread).toBe(0);
    // Read now, so it leaves the unread tab the bell opens on, and stays under "All".
    expect(wrapper.text()).not.toContain(t("alerts.state.told"));
    await button(wrapper, t("alerts.tabAll")).trigger("click");
    expect(wrapper.text()).toContain(t("alerts.state.told"));
  });

  it("marks everything read, and remembers it on this till", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert()]));
    const wrapper = await opened();

    await button(wrapper, t("alerts.markAllRead")).trigger("click");

    expect(useAlertsStore().unread).toBe(0);
    setActivePinia(createPinia());
    useSessionStore().data = { pos_profile: { name: "RPOS Till" } } as unknown as PosSession;
    await useAlertsStore().refresh();
    expect(useAlertsStore().unread).toBe(0);
  });

  it("strikes off only an alert that needs nothing more", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(
      answer([alert(), alert({ kot_name: "KOT-2", state: "printed" })]),
    );
    const wrapper = await opened();

    const strikes = wrapper.findAll(`[aria-label="${t("alerts.hide")}"]`);
    expect(strikes).toHaveLength(1);

    await strikes[0].trigger("click");
    expect(useAlertsStore().rows.map((row) => row.kot_name)).toEqual(["KOT-1"]);
  });

  it("offers no reprint to a cashier who may not", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert()]));

    expect((await opened(false)).text()).not.toContain(t("order.reprintTicket"));
  });

  it("opens on the unread", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(
      answer([alert(), alert({ kot_name: "KOT-2", failed_at: "2000-01-01 00:00:00", state: "told" })]),
    );

    const wrapper = await opened();

    expect(wrapper.findAll("li")).toHaveLength(1);
    await button(wrapper, t("alerts.tabAll")).trigger("click");
    expect(wrapper.findAll("li")).toHaveLength(2);
  });

  it("asks for the older twenty only when told to", async () => {
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert()], { more: true }));
    const wrapper = await opened();

    await button(wrapper, t("alerts.older")).trigger("click");
    await flushPromises();

    expect(kitchenApi.getPrintAlerts).toHaveBeenLastCalledWith("RPOS Till", 20);
  });

  it("chimes for an alert that arrives, not for what was there already", async () => {
    useSessionStore().data = {
      pos_profile: { name: "RPOS Till", rpos_alert_sound: 1, rpos_alert_tone: "bell", rpos_alert_volume: 90 },
    } as unknown as PosSession;
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert()]));
    const alerts = useAlertsStore();
    await alerts.refresh();
    await alerts.refresh();
    expect(playTone).not.toHaveBeenCalled();

    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert({ kot_name: "KOT-2" }), alert()]));
    await alerts.refresh();

    expect(playTone).toHaveBeenCalledOnce();
    expect(playTone).toHaveBeenCalledWith("bell", 90);
  });

  it("stays silent on a terminal set to no sound", async () => {
    useSessionStore().data = {
      pos_profile: { name: "RPOS Till", rpos_alert_sound: 0 },
    } as unknown as PosSession;
    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([]));
    const alerts = useAlertsStore();
    await alerts.refresh();

    vi.mocked(kitchenApi.getPrintAlerts).mockResolvedValue(answer([alert()]));
    await alerts.refresh();

    expect(playTone).not.toHaveBeenCalled();
  });

  it("asks once more when asked while asking, and never twice at once", async () => {
    let answerNow: (value: PrintAlerts) => void = () => undefined;
    vi.mocked(kitchenApi.getPrintAlerts)
      .mockImplementationOnce(() => new Promise((resolve) => (answerNow = resolve)))
      .mockResolvedValue(answer([alert({ state: "told" })]));
    const alerts = useAlertsStore();

    const first = alerts.refresh();
    void alerts.refresh();
    void alerts.refresh();
    expect(kitchenApi.getPrintAlerts).toHaveBeenCalledTimes(1);

    answerNow(answer([alert()]));
    await first;
    await flushPromises();

    expect(kitchenApi.getPrintAlerts).toHaveBeenCalledTimes(2);
    expect(alerts.rows[0].state).toBe("told");
  });
});
