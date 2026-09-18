<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, query } from "@/api/client";
import LocaleToggle from "@/components/LocaleToggle.vue";
import { forgetDevice, pairedDevice, rememberDevice } from "@/device";
import { t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * Pairing — seen **once**, when the app is installed on a till (`D-226`).
 *
 * This screen used to list every terminal the cashier could reach and remember
 * the tap. One tap was all that stood between a till in Dammam and the Riyadh
 * branch (`D-035`), and nothing stopped a second machine taking a terminal that
 * was already somebody's: two tills on one drawer, receipts in the wrong room.
 *
 * So the manager issues a code on the terminal in the office and the machine
 * types it here, once. What comes back is a device token, kept on this machine
 * and sent with every session load.
 *
 * Authentication is Frappe's (04 §7). This app never handles credentials.
 */
const session = useSessionStore();
const router = useRouter();

const code = ref("");
const deviceName = ref("");
const message = ref<string | null>(null);
const busy = ref(false);
const starting = ref(true);

onMounted(async () => {
  const paired = pairedDevice();
  if (paired) {
    await start(paired.posProfile, paired.token);
    if (session.isLoaded) return;
  }
  starting.value = false;
});

async function pair(): Promise<void> {
  if (busy.value) return;

  busy.value = true;
  message.value = null;

  try {
    const paired = await query<{ pos_profile: string; device_token: string }>("session.pair_device", {
      code: code.value,
      device_name: deviceName.value,
    });

    rememberDevice({ posProfile: paired.pos_profile, token: paired.device_token });
    code.value = "";
    await start(paired.pos_profile, paired.device_token);
  } catch (cause) {
    message.value = explain(cause);
  } finally {
    busy.value = false;
  }
}

async function start(posProfile: string, token: string): Promise<void> {
  busy.value = true;
  message.value = null;

  try {
    await session.load(posProfile, token);
    await router.push(nextScreen());
  } catch (cause) {
    message.value = explain(cause);

    // The pairing no longer works — a manager freed the terminal, or gave it to
    // another machine. Forget it so this screen can ask for a new code, rather
    // than retrying a token the server has stopped accepting.
    if (cause instanceof ApiError && cause.isPermissionDenied) forgetDevice();
  } finally {
    busy.value = false;
  }
}

function explain(cause: unknown): string {
  if (cause instanceof ApiError && cause.isPermissionDenied) return t("setup.signInFirst");
  return cause instanceof Error ? cause.message : String(cause);
}

/**
 * Where the till was going before it stopped here to load the terminal (`D-221`).
 *
 * Every full page load passes through this screen — a refresh, and the reload
 * after an update — and it used to end on home whatever was asked for: a cashier
 * who refreshed on a bill, or pressed Pay on a till left open across an update,
 * lost the screen they were on. Only a path inside the app is followed, never
 * another site.
 */
function nextScreen(): string | { name: string } {
  const next = router.currentRoute.value.query.next;
  return typeof next === "string" && next.startsWith("/") && !next.startsWith("//")
    ? next
    : { name: "home" };
}
</script>

<template>
  <main class="flex min-h-0 items-center justify-center overflow-y-auto p-4">
    <div class="w-full max-w-md rounded-rpos bg-surface p-6 shadow-sm">
      <div class="mb-1 flex items-start justify-between gap-3">
        <h1 class="text-lg font-semibold">
          {{ t("setup.title") }}
        </h1>
        <!-- The language is chosen before anything else: this is the first
             screen a newly installed terminal shows. -->
        <LocaleToggle />
      </div>
      <p class="mb-5 text-sm text-muted">
        {{ t("setup.hint") }}
      </p>

      <p
        v-if="starting"
        class="py-6 text-center text-muted"
      >
        {{ t("common.loading") }}
      </p>

      <form
        v-else
        class="flex flex-col gap-3"
        @submit.prevent="pair"
      >
        <label class="flex flex-col gap-1">
          <span class="text-sm text-muted">{{ t("setup.code") }}</span>
          <input
            v-model="code"
            inputmode="numeric"
            autocomplete="off"
            autofocus
            class="min-h-tap rounded-rpos border border-line bg-background px-4 py-3 text-center text-2xl tracking-widest"
            :placeholder="t('setup.codeExample')"
          >
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-sm text-muted">{{ t("setup.deviceName") }}</span>
          <input
            v-model="deviceName"
            autocomplete="off"
            class="min-h-tap rounded-rpos border border-line bg-background px-4 py-3"
            :placeholder="t('setup.deviceNameExample')"
          >
        </label>

        <button
          type="submit"
          class="min-h-tap rounded-rpos bg-primary px-4 py-3 font-medium text-on-primary disabled:opacity-60"
          :disabled="busy || !code"
        >
          {{ busy ? t("common.loading") : t("setup.pair") }}
        </button>
      </form>

      <p
        v-if="session.cachedAt"
        role="status"
        class="mt-4 rounded-rpos bg-status-cleaning/10 p-3 text-sm text-status-cleaning"
      >
        {{ t("conn.staleConfig", { when: session.cachedAt }) }}
      </p>

      <p
        v-if="message"
        role="alert"
        class="mt-4 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
      >
        {{ message }}
      </p>
    </div>
  </main>
</template>
