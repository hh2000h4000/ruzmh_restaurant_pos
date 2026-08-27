<script setup lang="ts">
import AppIcon, { type IconName } from "@/components/AppIcon.vue";
import { pick, t } from "@/i18n";
import type { OrderType } from "@/types/session";

/**
 * The one-tap column: every way this terminal can open an order.
 *
 * 320px wide, cards 94px tall with a 64px round icon — the sizes in the layout
 * specification, and big enough to hit without looking on a touch screen.
 *
 * The list is data: it comes from `load_pos_session`, already filtered by role,
 * terminal and branch (FR-1.3). Nothing here is hardcoded.
 */
defineProps<{ orderTypes: OrderType[]; active: string | null }>();
const emit = defineEmits<{ open: [orderType: OrderType] }>();

/**
 * An order type's icon is configured, not guessed.
 *
 * A manager types an icon name — `plane`, `truck`, `users` — into the order
 * type, and it draws as a real icon. Anything else is rendered as written, so
 * an emoji still works, and an empty field falls back to something sensible
 * for what the type does.
 */
const NAMES = new Set<string>([
  "plane",
  "mobile",
  "card",
  "users",
  "hanger",
  "truck",
  "home",
  "bag",
  "receipt",
  "document",
]);

interface TypeVisual {
  icon: IconName | null;
  glyph: string | null;
}

function visual(orderType: OrderType): TypeVisual {
  const configured = (orderType.icon ?? "").trim();

  if (NAMES.has(configured)) return { icon: configured as IconName, glyph: null };
  if (configured) return { icon: null, glyph: configured };

  if (orderType.requires_table) return { icon: "home", glyph: null };
  if (orderType.customer_mode === "required") return { icon: "users", glyph: null };
  return { icon: "bag", glyph: null };
}

/** The second line: what this type does, in a few words. */
function subtitle(orderType: OrderType): string {
  if (orderType.requires_table) return t("type.hintTable");
  if (orderType.customer_mode === "required") return t("type.hintCustomer");
  return t("type.hintQuick");
}
</script>

<template>
  <aside class="flex w-[320px] shrink-0 flex-col gap-4 overflow-y-auto p-5 xl:w-[300px] 2xl:w-[320px]">
    <h2 class="text-center text-lg font-semibold">
      {{ t("home.newOrder") }}
    </h2>

    <div class="flex flex-col gap-2.5">
      <button
        v-for="orderType in orderTypes"
        :key="orderType.name"
        type="button"
        class="flex h-[94px] items-center gap-4 rounded-rpos border px-4 text-start transition duration-200 ease-rpos"
        :class="
          active === orderType.name
            ? 'border-transparent bg-gradient-to-l from-primary to-primary/80 text-primary-contrast shadow-lift'
            : 'border-line bg-surface hover:-translate-y-px hover:shadow-card'
        "
        @click="emit('open', orderType)"
      >
        <!-- The type's own colour, tinted, inside a circle: it marks the row
             without fighting the label for contrast. -->
        <span class="relative grid h-16 w-16 shrink-0 place-items-center overflow-hidden rounded-full">
          <span
            class="absolute inset-0"
            :class="active === orderType.name ? 'bg-white/20' : 'opacity-10'"
            :style="
              active === orderType.name ? undefined : { backgroundColor: orderType.color ?? undefined }
            "
            aria-hidden="true"
          />
          <span
            class="relative"
            :style="active === orderType.name ? undefined : { color: orderType.color ?? undefined }"
          >
            <AppIcon
              v-if="visual(orderType).icon"
              :name="visual(orderType).icon!"
              :size="28"
            />
            <span
              v-else
              class="text-2xl leading-none"
              aria-hidden="true"
            >{{ visual(orderType).glyph }}</span>
          </span>
        </span>

        <span class="min-w-0 flex-1">
          <span class="block truncate text-lg font-bold leading-snug">
            {{ pick(orderType.title_ar, orderType.title) }}
          </span>
          <span
            class="block truncate text-sm"
            :class="active === orderType.name ? 'opacity-90' : 'text-muted'"
          >{{ subtitle(orderType) }}</span>
        </span>
      </button>
    </div>

    <p
      v-if="!orderTypes.length"
      class="text-sm text-muted"
    >
      {{ t("home.noOrderTypes") }}
    </p>
  </aside>
</template>
