<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import DigitPad from "@/components/DigitPad.vue";
import LocaleToggle from "@/components/LocaleToggle.vue";
import { dateOnly, t, timeOnly } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import { useSessionStore } from "@/stores/session";

/**
 * Signing in at the till, and clocking in (`FR-8.4`, `D-094`).
 *
 * **One view, two panes**, because it is one errand: the person says who they
 * are, then says what they came to do. The same reason the order screen is one
 * screen with a bill panel rather than two (`D-055`).
 *
 * A cashier never sees the ERPNext login form. It asks for an email address and
 * a password, and a till in kiosk mode raises no keyboard to type them with.
 */
const router = useRouter();
const auth = useAuthStore();
const session = useSessionStore();

const pin = ref("");
const posProfile = computed(() => session.profile?.name ?? null);

/** Boxes drawn from the server's own length, so the two cannot disagree. */
const boxes = computed(() => Array.from({ length: auth.pinLength }, (_, index) => index));

const clockedInAt = computed(() => {
  const since = auth.attendance?.since;
  return since ? `${dateOnly(since)} ${timeOnly(since)}` : null;
});

onMounted(() => {
  if (!auth.known) void auth.probe(posProfile.value);
});

// Submitted by length rather than by an OK button: the pad has no room for one
// and a fixed-length secret has nothing to confirm. The watcher fires the
// moment the last digit lands.
watch(pin, async (value) => {
  if (value.length !== auth.pinLength || auth.busy) return;

  const ok = await auth.signIn(value, posProfile.value);
  pin.value = "";
  if (!ok) return;

  // Somebody who cannot clock in has nothing to choose between, so the second
  // pane would be a screen with one button on it.
  if (!auth.isEmployee) void enterTill();
});

async function enterTill(): Promise<void> {
  await router.push({ name: session.isLoaded ? "home" : "setup" });
}

async function punch(): Promise<void> {
  await auth.punch(posProfile.value);
}
</script>

<template>
  <main class="grid min-h-dvh place-items-center bg-background p-6">
    <div class="w-full max-w-sm">
      <div class="mb-8 text-center">
        <h1 class="text-3xl font-bold tracking-tight text-content">
          RPOS
        </h1>
        <p
          v-if="session.branch"
          class="mt-1 text-sm text-muted"
        >
          {{ session.branch }}
        </p>
      </div>

      <!-- Pane 1 — who are you -->
      <section
        v-if="!auth.signedIn"
        class="space-y-6"
      >
        <p class="text-center text-muted">
          {{ t("auth.enterPin") }}
        </p>

        <div
          class="flex justify-center gap-2"
          dir="ltr"
        >
          <span
            v-for="box in boxes"
            :key="box"
            class="h-11 w-9 rounded-rpos border transition duration-200 ease-rpos"
            :class="
              box < pin.length
                ? 'border-primary bg-primary/10'
                : 'border-border bg-surface'
            "
          />
        </div>

        <p
          v-if="auth.error"
          class="text-center text-sm text-danger"
          role="alert"
        >
          {{ t("auth.pinRefused") }}
        </p>

        <DigitPad
          :value="pin"
          :max-length="auth.pinLength"
          @update="pin = $event"
        />
      </section>

      <!-- Pane 2 — what did you come to do -->
      <section
        v-else
        class="space-y-4"
      >
        <div class="text-center">
          <p class="text-lg font-bold text-content">
            {{ t("auth.welcome", { name: auth.fullName }) }}
          </p>
          <p
            v-if="clockedInAt"
            class="mt-1 text-sm text-muted"
          >
            {{ t("auth.clockedInAt", { at: clockedInAt }) }}
          </p>
        </div>

        <button
          v-if="auth.isEmployee"
          type="button"
          class="h-14 w-full rounded-rpos bg-surface text-base font-bold text-content transition duration-200 ease-rpos hover:bg-primary/10 disabled:opacity-50"
          :disabled="auth.busy"
          @click="punch"
        >
          {{ auth.clockedIn ? t("auth.clockOut") : t("auth.clockIn") }}
        </button>

        <button
          type="button"
          class="h-14 w-full rounded-rpos bg-primary text-base font-bold text-on-primary transition duration-200 ease-rpos hover:opacity-90 disabled:opacity-50"
          :disabled="auth.busy"
          @click="enterTill"
        >
          {{ t("auth.enterTill") }}
        </button>

        <p
          v-if="auth.error"
          class="text-center text-sm text-danger"
          role="alert"
        >
          {{ auth.error }}
        </p>

        <button
          type="button"
          class="h-12 w-full rounded-rpos text-sm font-bold text-muted transition duration-200 ease-rpos hover:bg-surface"
          :disabled="auth.busy"
          @click="auth.signOut()"
        >
          {{ t("auth.exit") }}
        </button>
      </section>

      <div class="mt-8 flex justify-center">
        <LocaleToggle />
      </div>
    </div>
  </main>
</template>
