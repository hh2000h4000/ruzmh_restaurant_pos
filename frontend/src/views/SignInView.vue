<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import DigitPad from "@/components/DigitPad.vue";
import LocaleToggle from "@/components/LocaleToggle.vue";
import { sinceWhen, t } from "@/i18n";
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
const build = __RPOS_BUILD__;

/** Boxes drawn from the server's own length, so the two cannot disagree. */
const boxes = computed(() => Array.from({ length: auth.pinLength }, (_, index) => index));

const clockedInAt = computed(() => {
  const since = auth.attendance?.since;
  return since ? sinceWhen(since) : null;
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

  // **Reload the terminal session for the new person** (`D-096`).
  //
  // It carries permissions, and permissions belong to whoever is signed in.
  // Without this the cashier taking over inherits the last one's: a senior's
  // void button on a junior's screen, or the reverse. The backend re-checks
  // everything, so this is not a hole — but a button that refuses when pressed
  // is a screen lying to the person reading it.
  if (session.isLoaded && posProfile.value) await session.load(posProfile.value);

  // **Everybody sees the second pane now** (`D-184`). It used to be skipped for
  // a login with no `Employee` behind it, on the reasoning that somebody who
  // cannot clock in has nothing to choose between — and the cost of that was
  // the user signing in as the owner, finding no attendance button anywhere,
  // and having no way to learn why. The screen says why instead. It costs an
  // administrator one extra tap per sign-in, which is the trade this makes.
});

async function enterTill(): Promise<void> {
  await router.push({ name: session.isLoaded ? "home" : "setup" });
}

/**
 * Record the punch, and then **go where it means** (`FR-8.4` step 3, `D-179`).
 *
 * This screen used to record it and stay, and the requirement has said since
 * Phase 4 that clocking in "drops the cashier straight into the till screen".
 * It was never wired, and what stood in its place was worse than a missing
 * convenience: the moment the punch landed, `punchOnOffer` flipped and **the
 * opposite action was drawn under the finger that had just tapped**. The user
 * clocked in and clocked straight back out in two taps, without ever opening a
 * shift — "نقرت عليها وظهر شاشة تسجيل انصراف ونقرت عليها".
 *
 * So arriving leads to the till, which is what the person came for, and
 * leaving leads out of the app, which is what *they* came for. Toast ends a
 * clock-out on its passcode screen for the same reason. Neither one leaves a
 * live button where the last one was.
 *
 * The direction is read **before** the punch: afterwards it is already the
 * other one.
 */
async function punch(): Promise<void> {
  const arriving = auth.punchOnOffer === "in";

  await auth.punch(posProfile.value);
  // Nothing happened, and the screen already says so — staying is right.
  if (auth.error) return;

  if (arriving) await enterTill();
  else await auth.signOut();
}
</script>

<template>
  <main class="grid min-h-dvh place-items-center bg-background p-6">
    <!-- One card on the warm ground, the same shape the rest of the app uses.
         It is the first thing a cashier touches every shift and the only screen
         they meet before the house style has told them anything, so it says it
         here. -->
    <div class="w-full max-w-sm rounded-rpos-lg border border-line bg-surface px-8 py-9 shadow-card">
      <div class="mb-8 text-center">
        <h1 class="text-3xl font-semibold tracking-tight text-content">
          RPOS
        </h1>
        <p
          v-if="session.branch"
          class="mt-1.5 text-sm text-muted"
        >
          {{ session.branch }}
        </p>
        <!--
          Which build this terminal is actually running (D-100). A till holds
          the whole app in a cache, so an old bundle behaves like a bug in the
          new one — and this is the only place the answer is visible without
          opening devtools.
        -->
        <p class="rpos-numeric mt-2 text-xs text-muted/70">
          {{ build }}
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

        <!-- `border-border` was not a colour — the config's token is `line`, so
             the class generated nothing and every box fell back to Tailwind's
             default grey. The boxes also say **where the next digit lands**: a
             fixed-length secret with no cursor gives a cashier who mistyped no
             way to see how far along they are. -->
        <div
          class="flex justify-center gap-2.5"
          dir="ltr"
        >
          <span
            v-for="box in boxes"
            :key="box"
            class="h-12 w-10 rounded-rpos border transition duration-200 ease-rpos"
            :class="
              box < pin.length
                ? 'border-primary bg-primary'
                : box === pin.length
                  ? 'border-primary bg-background'
                  : 'border-line bg-background'
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

        <!-- Arrive, open the drawer, work, close the drawer, go home (`D-177`).
             The button follows that order rather than only the clock: offering
             a clock-out over an open drawer is a count nobody made against
             somebody who has left. -->
        <!-- **Drawn disabled rather than hidden when this login is on no
             payroll** (`D-184`). The refusal is one the reader can lift, so the
             control stays and the line beneath it says how — the same shape
             `FR-2.1b` uses for order types that cannot be converted. -->
        <button
          v-if="auth.punchOnOffer || auth.notOnPayroll"
          type="button"
          class="h-14 w-full rounded-rpos border border-line-strong bg-background text-base font-medium text-content transition duration-200 ease-rpos hover:border-primary disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="auth.busy || auth.notOnPayroll"
          @click="punch"
        >
          {{ auth.punchOnOffer === "out" ? t("auth.clockOut") : t("auth.clockIn") }}
        </button>

        <!-- And whenever there is nothing to offer, it says why. Somebody who
             came to clock in and finds the button gone has no way to tell a
             rule from a broken screen (`D-074`). -->
        <p
          v-if="auth.notOnPayroll"
          class="rounded-rpos bg-background px-4 py-3 text-center text-sm text-muted"
        >
          {{ t("auth.noEmployeeRecord") }}
        </p>
        <p
          v-else-if="auth.heldByTill"
          class="rounded-rpos bg-background px-4 py-3 text-center text-sm text-muted"
        >
          {{ t("auth.closeTillFirst") }}
        </p>

        <!-- `text-on-primary` was not a colour either: the contrast token is
             `primary-contrast`, so the label on the one filled button in the
             app was inheriting whatever it found. -->
        <button
          type="button"
          class="h-14 w-full rounded-rpos bg-primary text-base font-medium text-primary-contrast shadow-primary transition duration-200 ease-rpos hover:brightness-110 disabled:opacity-50 disabled:shadow-none"
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

      <div class="mt-8 flex justify-center border-t border-line pt-6">
        <LocaleToggle />
      </div>
    </div>
  </main>
</template>
