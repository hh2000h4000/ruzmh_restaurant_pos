// @vitest-environment jsdom

/**
 * Which entries the till menu offers, and the one it stopped offering.
 *
 * **Going home only** (`D-185`). The user asked for the clock-*in* to come out:
 * *"شيل تسجيل الحضور من هذه القائمة، ليس له داعي"*. They are right, and the
 * reason is worth keeping — clocking in belongs to the welcome screen, which
 * everyone now passes through (`D-184`) and which drops them at the till the
 * moment they tap it (`D-179`). An entry offering to clock in *from inside the
 * till* is a second door into a room they are standing in (§5.5).
 *
 * And the clock-out stays where `FR-8.4` step 4 put it: beside the drawer it
 * waits for.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type { Identity } from "@/api/auth";
import ShiftMenu from "@/components/shift/ShiftMenu.vue";
import { t } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import { useSessionStore } from "@/stores/session";
import { useShiftStore } from "@/stores/shift";
import type { PosSession } from "@/types/session";

function identity(over: { clocked_in?: boolean; holding_till?: boolean; employee?: string | null }) {
  return {
    user: "cashier@example.com",
    full_name: "سعيد الغامدي",
    pos_profile: "T1",
    attendance: {
      employee: over.employee === undefined ? "HR-EMP-0001" : over.employee,
      clocked_in: over.clocked_in ?? false,
      since: over.clocked_in ? "2026-09-10 07:00:00" : null,
    },
    holding_till: over.holding_till ?? false,
    pin_length: 5,
  } as Identity;
}

/** The menu as a cashier meets it: the day open, and a drawer of their own. */
function menu(over: Parameters<typeof identity>[0], tillOpen = true) {
  useSessionStore().data = {
    pos_profile: { name: "كاشير 1", company: "مطعم الرزمة", branch: "Riyadh" },
    branch: { name: "Riyadh", branch: "فرع الصحافة" },
    permissions: {},
  } as unknown as PosSession;

  useShiftStore().state = {
    branch: "Riyadh",
    shift_type: "single",
    settlement_required: false,
    day: { open: true, shift: "SHF-1" },
    till: { open: tillOpen, entry: "OPE-1", is_mine: true },
  } as never;

  useAuthStore().identity = identity(over);

  return mount(ShiftMenu, { props: { open: true } });
}

beforeEach(() => setActivePinia(createPinia()));

describe("the till menu's attendance entry", () => {
  it("offers a clock-out once the drawer is counted", () => {
    expect(menu({ clocked_in: true, holding_till: false }, false).text()).toContain(
      t("auth.clockOut"),
    );
  });

  it("never offers a clock-in — that belongs to the welcome screen", () => {
    // Somebody who reached the till without clocking in: the entry used to
    // appear here, and now does not.
    const text = menu({ clocked_in: false }, false).text();

    expect(text).not.toContain(t("auth.clockIn"));
    // **And no attendance row at all.** Asserting only the absence of the
    // clock-in wording proved nothing: the label is fixed to "clock out", so
    // restoring the old condition put a row reading *تسجيل انصراف* in front of
    // somebody who had never arrived — and the test stayed green. A mutation
    // run caught that, which is exactly what one is for.
    expect(text).not.toContain(t("auth.clockOut"));
  });

  it("withholds the clock-out while the drawer is still open", () => {
    // `D-177` — going home over an open drawer leaves a count nobody made. And
    // this entry sits directly above "close the till".
    expect(menu({ clocked_in: true, holding_till: true }).text()).not.toContain(t("auth.clockOut"));
  });

  it("offers nothing to a login with no employee behind it", () => {
    // A disabled row among live ones reads as a fault; the welcome screen says
    // why instead (`D-184`).
    const text = menu({ employee: null, clocked_in: false }, false).text();

    expect(text).not.toContain(t("auth.clockOut"));
    expect(text).not.toContain(t("auth.clockIn"));
  });

  it("still offers the drawer and the day", () => {
    // The obvious other half: removing one entry must not remove the menu.
    const text = menu({ clocked_in: true, holding_till: true }).text();

    expect(text).toContain(t("shift.closeTill"));
    expect(text).toContain(t("shift.closeDay"));
  });
});

/**
 * `D-191` — the bookings moved here from the bar. The user saw a sixth entry
 * break the bar onto two lines and asked for it in this menu.
 */
describe("the day's bookings", () => {
  it("are one tap behind More while the day is open", () => {
    expect(menu({ clocked_in: true, holding_till: true }).text()).toContain(t("nav.reservations"));
  });

  it("are offered with the day closed too — tomorrow's booking comes by phone", () => {
    useSessionStore().data = { pos_profile: { name: "T1" }, permissions: {} } as unknown as PosSession;
    useShiftStore().state = {
      branch: "Riyadh",
      shift_type: "single",
      settlement_required: false,
      day: { open: false, shift: null },
      till: { open: false, entry: null, is_mine: false },
    } as never;
    useAuthStore().identity = identity({ clocked_in: false });

    const wrapper = mount(ShiftMenu, { props: { open: true } });

    expect(wrapper.text()).toContain(t("nav.reservations"));
    expect(wrapper.text()).toContain(t("shift.openTill"));
  });

  it("hands the till the pane to open", async () => {
    const wrapper = menu({ clocked_in: true, holding_till: true });
    const entry = wrapper.findAll("button").find((button) => button.text().includes(t("nav.reservations")));
    if (!entry) throw new Error("no bookings entry in the menu");

    await entry.trigger("click");

    expect(wrapper.emitted("select")).toEqual([["reservations"]]);
  });
});

describe("which till this is", () => {
  it("names the restaurant, the branch and the terminal (D-240)", () => {
    // The user asked where the branch is shown: nothing on the selling screen
    // said it, and a device paired to the wrong terminal was found out by the
    // first sale landing in another branch's day.
    const text = menu({ clocked_in: true }).text();

    expect(text).toContain("مطعم الرزمة");
    expect(text).toContain("فرع الصحافة");
    expect(text).toContain("كاشير 1");
  });
});
