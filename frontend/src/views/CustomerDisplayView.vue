<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";

import DisplayBanner from "@/components/display/DisplayBanner.vue";
import { useCustomerDisplayReceiver } from "@/composables/useCustomerDisplay";
import { formatNumber, t, timeOnly } from "@/i18n";

/**
 * The screen turned around to face the guest (`FR-13`).
 *
 * A second window on the second monitor, fed by the till beside it
 * (`useCustomerDisplay`, `D-162`). What the research on customer displays says
 * it earns its place by: the guest watches the bill being built, line by line
 * and option by option, so a wrong item is caught while it is still cheap to
 * fix and the total is never a surprise at the end.
 *
 * **It shows nothing but the bill.** No cashier, no document number, no
 * terminal — the room can read this screen, and what is never sent here cannot
 * leak from it (`useCustomerDisplay.DisplayLine`).
 *
 * **And it never shows a sign-in form.** The route asks for no session: if the
 * cashier signs out, the guest sees the restaurant's name, not a password box.
 *
 * Type is large on purpose. This one is read standing, at arm's length, by
 * somebody who is not looking for it — the opposite of the till, where the
 * caption rule of `D-159` applies.
 */
const { state, linked } = useCustomerDisplayReceiver();

const clock = ref(timeOnly(new Date().toISOString()));
let ticking: number | undefined;

onMounted(() => {
  ticking = window.setInterval(() => {
    clock.value = timeOnly(new Date().toISOString());
  }, 1000);
});

onUnmounted(() => window.clearInterval(ticking));

/**
 * The restaurant's name, as the till sent it.
 *
 * **Not read from a store here.** This window loads no session — it asks the
 * server for nothing, by design — so its own stores are empty and the header
 * came out blank on the first real screen. The name travels with the bill.
 *
 * `FR-13.1` also asks for a logo and a message, and both now have somewhere to
 * come from: the logo is the theme's (`RPOS Theme.brand_logo`), the message is
 * the one line a manager writes on the settings page (`D-202`). Like the name,
 * they are **sent** — this window asks the server for nothing — so they survive
 * an outage exactly as the bill does.
 */
const house = computed(() => state.value.house);

const lines = computed(() => state.value.lines);
const money = (value: number) => formatNumber(value, 2);
</script>

<template>
  <main class="grid min-h-screen grid-rows-[minmax(0,1fr)] bg-background text-content">
    <!-- Waiting. The room is looking at this screen far more often than a
         guest is ordering at it, so it is quiet on purpose. -->
    <section
      v-if="state.mode === 'idle'"
      class="grid min-h-0 grid-rows-[minmax(0,1fr)_auto]"
    >
      <!-- What a restaurant's marketing actually looks like: a designed banner,
           and usually more than one (`D-203`). When there are none, the quiet
           block below is the whole screen. -->
      <DisplayBanner
        v-if="state.banners.length"
        :banners="state.banners"
        :seconds="state.seconds"
      />

      <div
        v-else
        class="grid place-items-center p-10 text-center"
      >
        <!-- The restaurant's own logo, when it has set one. `alt` is the name,
             so a picture that fails to load leaves the name rather than a
             broken icon in front of the room. -->
        <img
          v-if="state.logo"
          :src="state.logo"
          :alt="house"
          class="mx-auto mb-8 max-h-[180px] max-w-[70%] object-contain"
        >
        <p class="text-[42px] font-medium text-primary">
          {{ house }}
        </p>
        <p class="rpos-numeric mt-4 text-[64px] font-medium tracking-tight text-content">
          {{ clock }}
        </p>
        <p class="mt-6 text-[20px] text-subtle">
          {{ t("display.welcome") }}
        </p>

        <!-- Nothing has ever arrived from the till, which on this screen looks
             identical to waiting for the next guest. It is not: the two windows
             are in different browsers or on different hostnames, and the channel
             does not cross either. Said quietly, because the room can read it. -->
        <p
          v-if="!linked"
          data-display-unlinked
          class="mt-8 text-[15px] text-muted"
        >
          {{ t("display.waiting") }}
        </p>

        <!-- What the manager wrote, in their own words. Kept below the fold of
             the name and the clock, and drawn only when there is one: an empty
             rule across the screen says the restaurant forgot something. -->
        <p
          v-if="state.message"
          data-display-message
          class="mx-auto mt-10 max-w-[26ch] whitespace-pre-line border-t border-line pt-8 text-[26px] leading-relaxed text-content"
        >
          {{ state.message }}
        </p>
      </div>

      <!-- With banners filling the screen, the name, the sentence and the clock
           step out of their way onto a strip rather than competing with them. -->
      <div
        v-if="state.banners.length"
        class="flex items-baseline justify-between gap-8 border-t border-line px-10 py-6"
      >
        <p class="shrink-0 text-[28px] font-medium text-primary">
          {{ house }}
        </p>
        <p
          v-if="state.message"
          data-display-message
          class="truncate text-[22px] text-subtle"
        >
          {{ state.message }}
        </p>
        <p class="rpos-numeric shrink-0 text-[28px] text-subtle">
          {{ clock }}
        </p>
      </div>
    </section>

    <!-- Paid. The research and `FR-2.10` agree on what a guest wants next: the
         number that will be called, big enough to read from a seat. -->
    <section
      v-else-if="state.mode === 'thanks'"
      class="grid place-items-center p-10 text-center"
    >
      <div>
        <p class="text-[38px] font-medium text-primary">
          {{ t("display.thanks") }}
        </p>
        <template v-if="state.number">
          <p class="mt-8 text-[22px] text-subtle">
            {{ t("display.yourNumber") }}
          </p>
          <p class="rpos-numeric text-[140px] font-medium leading-none text-primary">
            {{ formatNumber(state.number) }}
          </p>
        </template>
        <p class="rpos-numeric mt-8 text-[28px] text-subtle">
          {{ money(state.total) }} {{ t("currency.sar") }}
        </p>
      </div>
    </section>

    <!-- The bill being built, and the banner beside it (`D-203`).
         **The banner comes first so the direction places it**: in Arabic the
         start is the right, which puts the two-thirds there and the bill on the
         left, as asked. In English it mirrors, which is the same intent.
         **And on a screen too small for both, the bill has it alone** — the
         guest's own money outranks the marketing. -->
    <section
      v-else
      class="grid min-h-0 lg:grid-cols-[2fr_minmax(0,1fr)]"
    >
      <DisplayBanner
        v-if="state.banners.length"
        data-banner-pane
        class="border-e border-line max-lg:hidden"
        :banners="state.banners"
        :seconds="state.seconds"
      />

      <div class="grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-6 p-8">
        <header class="flex items-baseline justify-between">
          <p class="text-[28px] font-medium text-primary">
            {{ house }}
          </p>
          <p class="rpos-numeric text-[22px] text-subtle">
            {{ clock }}
          </p>
        </header>

        <!-- `D-074` — a bill with nothing on it yet says so rather than showing a
           blank panel the guest reads as a broken screen. -->
        <p
          v-if="!lines.length"
          class="grid place-items-center text-[24px] text-subtle"
        >
          {{ t("display.empty") }}
        </p>

        <ul
          v-else
          class="min-h-0 space-y-3 overflow-y-auto"
        >
          <li
            v-for="(line, index) in lines"
            :key="index"
            class="flex items-start justify-between gap-6 border-b border-line pb-3"
          >
            <div class="flex min-w-0 items-baseline gap-4">
              <span class="rpos-numeric shrink-0 text-[26px] font-medium text-primary">
                {{ formatNumber(line.qty) }}×
              </span>
              <div class="min-w-0">
                <p class="text-[26px]">
                  {{ line.name }}
                </p>
                <!-- Option by option: the research is explicit that this is where
                   a guest catches "I said no onion". -->
                <p
                  v-if="line.options.length"
                  class="mt-1 text-[18px] text-subtle"
                >
                  {{ line.options.join(t("common.listSeparator")) }}
                </p>
              </div>
            </div>

            <span class="rpos-numeric shrink-0 text-[26px]">{{ money(line.amount) }}</span>
          </li>
        </ul>

        <!-- **Three figures that add up.** The till's own panel shows the
           inclusive subtotal, which is right for somebody who knows the system;
           a guest reading `60.00 + 7.83 = 60.00` reads a mistake. The amount
           before tax is derived instead, so the column sums on the screen
           whichever way the branch charges tax (`D-091`, `D-162`). -->
        <footer class="space-y-2 border-t-2 border-primary/30 pt-4 text-[22px]">
          <!-- The offer is named. A guest who came in for it is looking for it
             here, and "discount" does not tell them it was honoured (`D-163`). -->
          <div
            v-if="state.promotion"
            class="flex justify-between gap-4 text-status-available"
          >
            <span class="truncate">{{ state.promotion.title }}</span>
            <span class="rpos-numeric shrink-0">−{{ money(state.promotion.amount) }}</span>
          </div>
          <!-- Their own points, named as theirs — the one line on this screen
             the guest paid for with something other than money (`D-189`). -->
          <div
            v-if="state.loyalty"
            class="flex justify-between gap-4 text-status-available"
          >
            <span>{{ t("totals.loyalty") }}</span>
            <span class="rpos-numeric shrink-0">−{{ money(state.loyalty.amount) }}</span>
          </div>
          <div
            v-if="state.discount"
            class="flex justify-between text-subtle"
          >
            <span>{{ t("totals.discount") }}</span>
            <span class="rpos-numeric">−{{ money(state.discount) }}</span>
          </div>
          <div class="flex justify-between text-subtle">
            <span>{{ t("display.beforeTax") }}</span>
            <span class="rpos-numeric">{{ money(state.beforeTax) }}</span>
          </div>
          <div class="flex justify-between text-subtle">
            <span>{{ t("totals.tax") }}</span>
            <span class="rpos-numeric">{{ money(state.tax) }}</span>
          </div>
          <div class="flex justify-between pt-2 text-[38px] font-medium text-primary">
            <span>{{ t("totals.total") }}</span>
            <span class="rpos-numeric">{{ money(state.total) }}</span>
          </div>
        </footer>
      </div>
    </section>
  </main>
</template>
