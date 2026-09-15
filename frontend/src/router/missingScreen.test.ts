// @vitest-environment jsdom

/**
 * A till left open across an update (`D-221`).
 *
 * The build renames every file, so the open page asked for the payment screen
 * under its old name: Pay did nothing, and the cashier read "Failed to fetch
 * dynamically imported module" with a URL in it. Online, the page now loads
 * afresh at that screen — once, so a real failure cannot reload for ever.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { arrived, isMissingScreen, shouldReload } from "@/router/missingScreen";

beforeEach(() => sessionStorage.clear());

describe("telling a missing screen from any other failure", () => {
  it.each([
    "Failed to fetch dynamically imported module: http://site/assets/PaymentView-old.js",
    "Importing a module script failed.",
    "Loading chunk 42 failed.",
  ])("knows %s", (message) => {
    expect(isMissingScreen(new TypeError(message))).toBe(true);
  });

  it("leaves every other error to whoever raised it", () => {
    expect(isMissingScreen(new Error("Navigation cancelled"))).toBe(false);
  });
});

describe("reloading for an update", () => {
  it("reloads once online, then gives the message", () => {
    expect(shouldReload("/order/RO-1/pay", true)).toBe(true);
    expect(shouldReload("/order/RO-1/pay", true)).toBe(false);
  });

  it("reloads again after a screen has come up", () => {
    shouldReload("/order/RO-1/pay", true);
    arrived();

    expect(shouldReload("/order/RO-1/pay", true)).toBe(true);
  });

  it("does not reload offline, where a fresh page could not come", () => {
    expect(shouldReload("/order/RO-1/pay", false)).toBe(false);
  });
});
