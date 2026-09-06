// @vitest-environment jsdom

/**
 * The prompt a manager types into (`D-147`).
 *
 * Two defects met here. The payment screen's copy of this sheet asked for
 * **four** digits while the server has enforced **five** since `D-094`: the box
 * stopped at four characters and the Authorize button required exactly four, so
 * a manager could not type their own PIN and the one button that would have
 * unlocked the action never enabled. And the return screen had no sheet at all,
 * so `BR-055` refused the cashier with nowhere to answer.
 *
 * Both are invisible to the backend suite — the endpoint is perfect either way
 * (`D-130`). So the length is asserted against the store the server fills, not
 * against a number written here.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ManagerPinDialog from "@/components/ManagerPinDialog.vue";
import { useAuthStore } from "@/stores/auth";
import type { Identity } from "@/api/auth";

const PIN_LENGTH = 5;

function open(verify = vi.fn().mockResolvedValue("token-123")) {
  useAuthStore().identity = {
    user: "manager@example.com",
    full_name: "Manager",
    pin_length: PIN_LENGTH,
    attendance: { employee: null, clocked_in: false },
  } as unknown as Identity;

  const wrapper = mount(ManagerPinDialog, {
    props: { open: true, explain: "من مناوبة سابقة", verify },
    global: { stubs: { teleport: true } },
  });

  return { wrapper, verify };
}

/** The button that sends the PIN, and the two fields it waits on. */
function authorize(wrapper: ReturnType<typeof open>["wrapper"]) {
  return wrapper.findAll("button").at(-1)!;
}

async function fill(wrapper: ReturnType<typeof open>["wrapper"], pin: string, reason = "استرداد") {
  await wrapper.find("#manager-pin").setValue(pin);
  await wrapper.find("#manager-reason").setValue(reason);
}

beforeEach(() => setActivePinia(createPinia()));

describe("asking a manager to approve", () => {
  it("takes a PIN as long as the server's", async () => {
    const { wrapper } = open();

    expect(wrapper.find("#manager-pin").attributes("maxlength")).toBe(String(PIN_LENGTH));
  });

  it("does not authorize on a short PIN", async () => {
    const { wrapper } = open();
    await fill(wrapper, "1234");

    expect(authorize(wrapper).attributes("disabled")).toBeDefined();
  });

  it("authorizes on a full one", async () => {
    const { wrapper } = open();
    await fill(wrapper, "12345");

    expect(authorize(wrapper).attributes("disabled")).toBeUndefined();
  });

  it("will not send without a reason", async () => {
    const { wrapper } = open();
    await fill(wrapper, "12345", "   ");

    expect(authorize(wrapper).attributes("disabled")).toBeDefined();
  });

  it("hands the token to whoever asked", async () => {
    const { wrapper, verify } = open();
    await fill(wrapper, "12345", "استرداد");
    await authorize(wrapper).trigger("click");
    await flush();

    expect(verify).toHaveBeenCalledWith("12345", "استرداد");
    expect(wrapper.emitted("approved")).toEqual([["token-123"]]);
  });

  it("says why a refusal was refused, and keeps no PIN", async () => {
    const verify = vi.fn().mockRejectedValue(new Error("Manager authorisation is invalid."));
    const { wrapper } = open(verify);
    await fill(wrapper, "12345");
    await authorize(wrapper).trigger("click");
    await flush();

    expect(wrapper.find('[role="alert"]').text()).toContain("invalid");
    expect(wrapper.emitted("approved")).toBeUndefined();
    // A wrong PIN is retyped, never corrected in place — and never left on screen.
    expect((wrapper.find("#manager-pin").element as HTMLInputElement).value).toBe("");
  });
});

/** Let the promise chain inside the component settle. */
async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}
