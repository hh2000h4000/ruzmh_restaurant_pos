<script setup lang="ts">
import { computed, ref } from "vue";

import type { OrderLine } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import { nextOffset, OPEN_AT, outcomeFor, swipeSign } from "@/components/order/swipe";
import { formatNumber, pick, t } from "@/i18n";

/**
 * One line on the bill, with the swipe a phone taught everybody (06 Screen 3).
 *
 * **Why a swipe.** The reference system removes a line by dragging it aside,
 * and a cashier already knows the gesture from their phone. It is faster than
 * finding a small button, and it cannot be hit by accident the way a button
 * under a moving thumb can.
 *
 * **The swipe does not delete.** It uncovers the action; BR-013 still demands a
 * reason, so confirming opens the same dialog the button opens. A line that
 * vanished off the screen with no reason recorded is exactly the hole the rule
 * exists to close.
 *
 * **Direction follows the writing direction.** In Arabic the row moves right,
 * in English left — the "trailing" edge is where a hand expects the drawer.
 */
const props = defineProps<{
  line: OrderLine;
  busy?: boolean;
  /**
   * What to call the offer that reached this line (`D-166`).
   *
   * Passed in rather than read here: the promotion belongs to the **bill**, and
   * a row that fetched the bill's name for itself would be every row asking the
   * same question separately.
   */
  promotionLabel?: string;
}>();

const emit = defineEmits<{
  void: [];
  repeat: [];
  inspect: [];
}>();

const offset = ref(0);
const dragging = ref(false);
let startX = 0;
let startOffset = 0;
let pointerId: number | null = null;

/**
 * A release that ended a real drag must not also read as a tap.
 *
 * The overlay button fires its click after the pointer comes up, so without
 * this a swipe would open the line's detail dialog on top of the void dialog it
 * just asked for.
 */
let swiped = false;

/**
 * Fixed for the length of one drag, and read fresh at the start of each.
 *
 * Caching it would leave the row sliding the wrong way after a mid-shift
 * language switch; re-reading it mid-drag would flip the row under the finger.
 */
let sign: 1 | -1 = -1;

/** Always positive: how far the drawer is open, whichever way it opened. */
const revealed = computed(() => Math.abs(offset.value));

function onPointerDown(event: PointerEvent): void {
  // A mouse still has the buttons; the swipe is for the finger, and hijacking
  // a click would break the "tap the line to inspect it" path.
  if (event.pointerType === "mouse" || props.busy) return;

  pointerId = event.pointerId;
  dragging.value = true;
  swiped = false;
  sign = swipeSign(document.documentElement.dir);
  startX = event.clientX;
  startOffset = offset.value;

  // Without capture the row stops following a finger that leaves it, and the
  // release never arrives — the row would stay stuck half open.
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent): void {
  if (!dragging.value || event.pointerId !== pointerId) return;

  const next = nextOffset(startOffset, event.clientX - startX, sign);
  if (Math.abs(next - startOffset) > 4) swiped = true;
  offset.value = next;
}

function onPointerUp(event: PointerEvent): void {
  if (!dragging.value || event.pointerId !== pointerId) return;

  dragging.value = false;
  pointerId = null;

  const outcome = outcomeFor(revealed.value);
  if (outcome === "remove") {
    close();
    emit("void");
  } else if (outcome === "open") {
    offset.value = OPEN_AT * sign;
  } else {
    close();
  }
}

function close(): void {
  offset.value = 0;
}

/** A tap opens the line — unless it was the end of a swipe, or the drawer is out. */
function onTap(): void {
  if (swiped) {
    swiped = false;
    return;
  }

  if (revealed.value) close();
  else emit("inspect");
}

function voidFromDrawer(): void {
  close();
  emit("void");
}

/** A line already with the kitchen cannot be quietly re-tapped away (BR-013). */
const isSent = computed(() => props.line.status === "sent");

/** A combo reads as its header with its items under it, one to a line (D-285). */
const isCombo = computed(() =>
  (props.line.modifiers ?? []).some((modifier) => modifier.item_effect === "combo"),
);

/** Bare figures: the currency is stated once, on the total. */
function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <li class="relative overflow-hidden">
    <!--
      The drawer sits under the row at the trailing edge, so the row slides off
      it rather than pushing it along.
    -->
    <div
      class="absolute inset-y-0 end-0 flex w-[88px] items-center justify-center bg-danger text-white"
      :aria-hidden="revealed === 0"
    >
      <button
        type="button"
        class="grid h-full w-full place-items-center"
        :tabindex="revealed ? 0 : -1"
        :aria-label="t('action.cancel')"
        @click="voidFromDrawer"
      >
        <AppIcon
          name="trash"
          :size="24"
        />
      </button>
    </div>

    <div
      class="relative touch-pan-y bg-surface px-4 py-2.5"
      :style="{
        transform: `translateX(${offset}px)`,
        transition: dragging ? 'none' : 'transform 200ms cubic-bezier(0.2, 0, 0, 1)',
      }"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
    >
      <!-- The whole line opens its details; the buttons below stay for the
           fast path a busy cashier already knows. -->
      <button
        type="button"
        class="absolute inset-0"
        :aria-label="line.item_name"
        @click="onTap"
      />

      <!-- Name and price on one line, what qualifies the dish under it, and the
           count with its two keys at the foot — the way the reference reads a
           line (`D-371`). The count used to sit before the name as "1 ×" and
           the keys floated at the far end, so a line read as three things. -->
      <div class="pointer-events-none">
        <div class="flex min-w-0 items-start gap-3">
          <div class="min-w-0 flex-1">
            <div class="flex items-start justify-between gap-3">
              <p class="min-w-0 font-semibold leading-snug">
                {{ line.item_name }}
              </p>
              <p class="rpos-numeric shrink-0 font-semibold">
                {{ money(line.amount) }}
              </p>
            </div>

            <template v-if="isCombo">
              <p
                v-for="(part, index) in line.modifiers"
                :key="index"
                class="truncate text-sm text-muted"
                data-combo-part
              >
                – {{ pick(part.option_ar, part.option) }}
                <template v-if="part.modifiers?.length">
                  ({{
                    part.modifiers
                      .map((extra) => pick(extra.option_ar, extra.option))
                      .join(t("common.listSeparator"))
                  }})
                </template>
              </p>
            </template>
            <p
              v-else-if="line.modifiers?.length"
              class="truncate text-sm text-muted"
            >
              {{
                line.modifiers
                  .map((modifier) => pick(modifier.option_ar, modifier.option))
                  .join(t("common.listSeparator"))
              }}
            </p>
            <p
              v-if="line.notes"
              class="flex items-center gap-1.5 truncate text-sm text-muted"
            >
              <AppIcon
                name="note"
                :size="14"
              />
              {{ line.notes }}
            </p>

            <!-- **The offer, on the dish it came off** (`D-166`).

                 The totals block names the promotion and gives its figure, and
                 on a bill where the offer covers three items out of seven that
                 still does not say *which* — which is the question the guest
                 asks while pointing at one of them. Toast puts the discount as a
                 line beneath the item it discounted and Foodics writes the
                 offer's name under the dish; this is that line.

                 It rides with the modifiers and the note rather than beside the
                 price: those are the three things that qualify what this line
                 *is*, and the price column answers what it costs.

                 **An amount with no name draws nothing** — the same rule the
                 totals row holds. A green figure the cashier cannot explain is
                 worse than no mark at all. -->
            <p
              v-if="line.promotion_amount && promotionLabel"
              class="flex items-center gap-1.5 truncate text-sm text-status-available"
            >
              <AppIcon
                name="tag"
                :size="14"
              />
              <span class="truncate">{{ promotionLabel }}</span>
              <span class="rpos-numeric shrink-0">−{{ money(line.promotion_amount) }}</span>
            </p>

            <!-- Status is never colour alone (06 §Accessibility). -->
            <p
              v-if="isSent"
              class="mt-1.5 inline-block rounded-full bg-order-in_kitchen/10 px-2.5 py-0.5 text-xs font-medium text-order-in_kitchen"
            >
              {{ t("panel.inKitchen") }}
            </p>
          </div>
        </div>

        <div class="pointer-events-auto relative mt-2 flex items-center gap-1">
          <button
            type="button"
            class="grid h-9 w-9 place-items-center rounded-lg bg-background text-danger transition duration-200 ease-rpos hover:bg-danger/10 disabled:opacity-40"
            :disabled="busy"
            :aria-label="t('action.remove')"
            :title="t('action.remove')"
            @click="emit('void')"
          >
            <AppIcon
              name="trash"
              :size="16"
            />
          </button>
          <span
            data-qty
            class="rpos-numeric min-w-[2.25rem] text-center font-semibold"
          >{{ formatNumber(line.qty) }}</span>
          <button
            type="button"
            class="grid h-9 w-9 place-items-center rounded-lg bg-background text-content transition duration-200 ease-rpos hover:bg-primary/10 disabled:opacity-40"
            :disabled="busy"
            :aria-label="t('panel.addSame')"
            :title="t('panel.addSame')"
            @click="emit('repeat')"
          >
            <AppIcon
              name="plus"
              :size="16"
            />
          </button>
        </div>
      </div>
    </div>
  </li>
</template>
