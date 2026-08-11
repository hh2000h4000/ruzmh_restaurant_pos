<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "@/api/client";
import LocaleToggle from "@/components/LocaleToggle.vue";
import { t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * Terminal setup (09 §2 workflow): the cashier signs in through Frappe's own
 * login page, then picks which POS Profile this device is. The choice is kept
 * so the device goes straight to the home screen next time.
 *
 * Authentication is Frappe's (04 §7). This app never handles credentials.
 */
const REMEMBERED = "rpos.pos_profile";

const session = useSessionStore();
const router = useRouter();

const posProfile = ref("");
const message = ref<string | null>(null);
const busy = ref(false);

onMounted(() => {
  const remembered = localStorage.getItem(REMEMBERED);
  if (remembered) {
    posProfile.value = remembered;
    void start();
  }
});

async function start(): Promise<void> {
  if (!posProfile.value.trim() || busy.value) return;

  busy.value = true;
  message.value = null;

  try {
    await session.load(posProfile.value.trim());
    localStorage.setItem(REMEMBERED, posProfile.value.trim());
    await router.push({ name: "home" });
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 403) {
      message.value = t("setup.signInFirst");
    } else {
      message.value = cause instanceof Error ? cause.message : String(cause);
    }
    localStorage.removeItem(REMEMBERED);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center p-4">
    <div class="w-full max-w-sm rounded-rpos bg-surface p-6 shadow-sm">
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

      <form @submit.prevent="start">
        <label
          for="pos-profile"
          class="mb-1.5 block text-sm font-medium"
        >
          {{ t("setup.profile") }}
        </label>
        <input
          id="pos-profile"
          v-model="posProfile"
          type="text"
          autocomplete="off"
          class="mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3 text-base focus:outline-none focus:ring-2 focus:ring-primary"
          :aria-describedby="message ? 'pos-profile-error' : undefined"
        >

        <button
          type="submit"
          class="min-h-tap w-full rounded-rpos bg-primary px-4 font-medium text-primary-contrast disabled:opacity-60"
          :disabled="busy || !posProfile.trim()"
        >
          {{ busy ? t("common.loading") : t("setup.start") }}
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
        id="pos-profile-error"
        role="alert"
        class="mt-4 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
      >
        {{ message }}
      </p>
    </div>
  </main>
</template>
