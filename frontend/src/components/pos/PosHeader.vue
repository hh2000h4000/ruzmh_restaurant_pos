<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import LocaleToggle from "@/components/LocaleToggle.vue";
import { clockTime, t } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";
import { useSessionStore } from "@/stores/session";

/**
 * The bar across the top of every till screen: who is on it, what it is, and
 * the one search box that finds an order among fifty at a lunch rush.
 *
 * 90px tall, per the layout specification.
 */
defineProps<{ subtitle: string }>();

const search = defineModel<string>("search", { default: "" });

const session = useSessionStore();
const connection = useConnectionStore();

const cashierName = computed(() => session.data?.user_name || session.data?.user || "");

/** The POS role, which is what the line under the name means to staff. */
const cashierRole = computed(() => {
  const roles = session.data?.permissions?.roles;
  return Array.isArray(roles) ? (roles[0] ?? "") : "";
});

const cashierInitial = computed(() => cashierName.value.trim().charAt(0) || "?");

// Staff read the time off this screen all shift. Minutes, not seconds — a
// second hand is motion nobody asked for.
const now = ref(clockTime());
let clock: number | undefined;

onMounted(() => {
  clock = window.setInterval(() => (now.value = clockTime()), 15_000);
});

onUnmounted(() => window.clearInterval(clock));
</script>

<template>
  <header
    class="flex h-[90px] shrink-0 items-center gap-4 overflow-hidden border-b border-line bg-surface px-6 xl:gap-6"
  >
    <div class="flex min-w-0 shrink items-center gap-3">
      <span
        class="grid h-[46px] w-[46px] shrink-0 place-items-center rounded-rpos bg-primary text-primary-contrast"
        aria-hidden="true"
      >
        <AppIcon
          name="receipt"
          :size="24"
        />
      </span>
      <div class="min-w-0">
        <p class="truncate text-lg font-bold leading-tight">
          {{ t("home.appName") }}
        </p>
        <p class="truncate text-sm text-muted">
          {{ subtitle }}
        </p>
      </div>
    </div>

    <div class="relative w-[300px] min-w-0 shrink">
      <span
        class="pointer-events-none absolute inset-y-0 start-4 grid place-items-center text-muted"
      >
        <AppIcon
          name="search"
          :size="22"
        />
      </span>
      <input
        v-model="search"
        type="search"
        :placeholder="t('home.search')"
        :aria-label="t('home.search')"
        class="h-[52px] w-full rounded-full bg-background ps-12 pe-4 text-base outline-none transition duration-200 ease-rpos focus:bg-surface focus:ring-2 focus:ring-primary/30"
      >
    </div>

    <div class="ms-auto flex shrink-0 items-center gap-3">
      <span class="rpos-numeric hidden items-center gap-1.5 text-sm font-medium text-muted xl:flex">
        <AppIcon
          name="clock"
          :size="18"
        />
        {{ now }}
      </span>

      <span
        class="hidden rounded-full px-3 py-1.5 text-sm font-medium lg:block"
        :class="
          session.canSell
            ? 'bg-status-available/10 text-status-available'
            : 'bg-status-reserved/10 text-status-reserved'
        "
      >
        {{ session.canSell ? t("home.shiftOpen") : t("home.shiftClosed") }}
      </span>

      <LocaleToggle />

      <!-- Not a notification bell: the only thing a till genuinely has to raise
           is work still waiting to reach the server, so it appears only when
           there is some. -->
      <div
        v-if="connection.hasBacklog"
        class="relative grid h-11 w-11 place-items-center rounded-full bg-secondary/10 text-secondary"
        :title="t('conn.syncing')"
      >
        <AppIcon
          name="bell"
          :size="24"
        />
        <span
          class="rpos-numeric absolute -top-1 end-0 grid h-5 min-w-[1.25rem] place-items-center rounded-full bg-secondary px-1 text-xs font-semibold text-secondary-contrast"
        >{{ connection.pending + connection.failed }}</span>
      </div>

      <div class="flex items-center gap-2.5">
        <div class="hidden text-end md:block">
          <p class="text-sm font-semibold leading-tight">
            {{ cashierName }}
          </p>
          <p class="text-xs text-muted">
            {{ cashierRole }}
          </p>
        </div>
        <span
          class="grid h-[46px] w-[46px] shrink-0 place-items-center rounded-full bg-primary/10 text-base font-semibold uppercase text-primary"
          aria-hidden="true"
        >{{ cashierInitial }}</span>
      </div>
    </div>
  </header>
</template>
