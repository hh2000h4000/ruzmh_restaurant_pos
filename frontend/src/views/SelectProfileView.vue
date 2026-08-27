<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, query } from "@/api/client";
import LocaleToggle from "@/components/LocaleToggle.vue";
import { pick, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * Terminal setup — seen **once**, when the app is installed on a till.
 *
 * The device belongs to one POS Profile. It is not a question the cashier
 * answers at the start of a shift: a till in Dammam must not be able to start
 * selling on the Riyadh branch because somebody tapped the wrong row (D-035).
 * Once chosen, the choice is remembered and this screen never appears again.
 *
 * It used to ask the cashier to type the profile's name from memory, which is
 * why nobody could get past it.
 *
 * Authentication is Frappe's (04 §7). This app never handles credentials.
 */
const REMEMBERED = "rpos.pos_profile";

interface ProfileOption {
  name: string;
  company: string | null;
  branch: string | null;
  section_title: string | null;
  section_title_ar: string | null;
}

const session = useSessionStore();
const router = useRouter();

const options = ref<ProfileOption[]>([]);
const message = ref<string | null>(null);
const busy = ref(false);
const listing = ref(true);

onMounted(async () => {
  const remembered = localStorage.getItem(REMEMBERED);
  if (remembered) {
    await start(remembered);
    if (session.isLoaded) return;
  }

  await loadOptions();
});

async function loadOptions(): Promise<void> {
  listing.value = true;
  try {
    options.value = await query<ProfileOption[]>("session.list_pos_profiles");
    message.value = null;
  } catch (cause) {
    message.value =
      cause instanceof ApiError && cause.isPermissionDenied
        ? t("setup.signInFirst")
        : cause instanceof Error
          ? cause.message
          : String(cause);
  } finally {
    listing.value = false;
  }
}

async function start(posProfile: string): Promise<void> {
  if (busy.value) return;

  busy.value = true;
  message.value = null;

  try {
    await session.load(posProfile);
    localStorage.setItem(REMEMBERED, posProfile);
    await router.push({ name: "home" });
  } catch (cause) {
    if (cause instanceof ApiError && cause.isPermissionDenied) {
      message.value = t("setup.signInFirst");
    } else {
      message.value = cause instanceof Error ? cause.message : String(cause);
    }
    // The remembered terminal no longer works — a deleted profile, a revoked
    // permission. Forget it so this screen can offer the others.
    localStorage.removeItem(REMEMBERED);
  } finally {
    busy.value = false;
  }
}

function subtitle(option: ProfileOption): string {
  const section = pick(option.section_title_ar, option.section_title);
  return [option.branch, section].filter(Boolean).join(" · ");
}
</script>

<template>
  <main class="flex min-h-0 flex-1 items-center justify-center overflow-y-auto p-4">
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
        v-if="listing || busy"
        class="py-6 text-center text-muted"
      >
        {{ t("common.loading") }}
      </p>

      <div
        v-else-if="options.length"
        class="flex flex-col gap-2"
      >
        <button
          v-for="option in options"
          :key="option.name"
          type="button"
          class="min-h-tap rounded-rpos border border-line px-4 py-3 text-start transition hover:border-primary hover:bg-background focus:outline-none focus:ring-2 focus:ring-primary"
          @click="start(option.name)"
        >
          <span class="block font-medium">{{ option.name }}</span>
          <span
            v-if="subtitle(option)"
            class="block text-sm text-muted"
          >{{ subtitle(option) }}</span>
        </button>
      </div>

      <p
        v-else
        class="rounded-rpos bg-background p-4 text-center text-sm text-muted"
      >
        {{ t("setup.empty") }}
      </p>

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
