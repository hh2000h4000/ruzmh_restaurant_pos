// @vitest-environment jsdom

/**
 * What "not signed in" means depends on whether this machine is a till yet
 * (`D-226`).
 *
 * A lost session takes the cashier to the PIN pad (`D-101`) — but a machine
 * that has never been paired is unauthenticated *by definition*, and the pad
 * belongs to a terminal it does not know. This watcher pushed it there anyway,
 * on every connection probe, straight over the pairing screen the guard had
 * just chosen. The user could not reach the code box at all, in a fresh browser
 * with nothing cached, and the screen gave no hint why.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App.vue";
import { useConnectionStore } from "@/stores/connection";

const push = vi.fn();
const currentRoute = { value: { name: "home" } as { name: string } };

vi.mock("vue-router", () => ({
  useRouter: () => ({ push, currentRoute }),
  RouterView: { template: "<div />" },
}));

function app() {
  return mount(App, { global: { stubs: { RouterView: true } } });
}

describe("a session the server will not accept", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    push.mockReset();
    currentRoute.value = { name: "home" };
  });

  it("sends an unpaired machine to pairing, not to the PIN pad", async () => {
    const connection = useConnectionStore();
    vi.spyOn(connection, "start").mockResolvedValue(undefined);
    app();

    connection.state = "unauthenticated";
    await flushPromises();

    expect(push).toHaveBeenCalledWith({ name: "setup" });
  });

  it("leaves the pairing screen alone once it is there", async () => {
    const connection = useConnectionStore();
    vi.spyOn(connection, "start").mockResolvedValue(undefined);
    currentRoute.value = { name: "setup" };
    app();

    connection.state = "unauthenticated";
    await flushPromises();

    expect(push).not.toHaveBeenCalled();
  });

  it("sends a paired till to the PIN pad, as before", async () => {
    localStorage.setItem("rpos.pos_profile", "T1");
    localStorage.setItem("rpos.device_token", "tok");
    const connection = useConnectionStore();
    vi.spyOn(connection, "start").mockResolvedValue(undefined);
    app();

    connection.state = "unauthenticated";
    await flushPromises();

    expect(push).toHaveBeenCalledWith({ name: "sign-in" });
  });
});
