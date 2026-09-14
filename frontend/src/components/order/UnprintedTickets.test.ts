// @vitest-environment jsdom

/**
 * A kitchen ticket that did not print is said on the order (`D-211`).
 *
 * The one question these ask is the one `06` asks of every screen: is a control
 * the cashier can reach a control the server will accept. So the reprint button
 * is present only with `can_reprint_receipt`, and held while the till is busy.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import UnprintedTickets from "@/components/order/UnprintedTickets.vue";
import { t } from "@/i18n";

const TICKET = { kot_name: "KOT-2026-09-00001", station: "Grill", station_ar: "الشواية" };

function warning(props: { mayReprint: boolean; busy?: boolean }) {
  return mount(UnprintedTickets, {
    props: { tickets: [TICKET], busy: false, ...props },
  });
}

describe("UnprintedTickets", () => {
  it("names the station whose ticket did not print", () => {
    const screen = warning({ mayReprint: true });

    expect(screen.get('[role="alert"]').text()).toMatch(/Grill|الشواية/);
  });

  it("prints that ticket again when asked", async () => {
    const screen = warning({ mayReprint: true });

    await screen.get("button").trigger("click");

    expect(screen.emitted("reprint")).toEqual([[TICKET.kot_name]]);
  });

  it("offers no button the server would refuse, and says who can", () => {
    const screen = warning({ mayReprint: false });

    expect(screen.find("button").exists()).toBe(false);
    expect(screen.text()).toContain(t("order.askForReprint"));
  });

  it("holds the button while the till is still busy", () => {
    const screen = warning({ mayReprint: true, busy: true });

    expect(screen.get("button").attributes("disabled")).toBeDefined();
  });
});
