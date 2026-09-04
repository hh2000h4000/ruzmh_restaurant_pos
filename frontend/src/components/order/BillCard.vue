<script setup lang="ts">
/**
 * One bill as a column: what is on it, and what it comes to.
 *
 * Shared by the split screen and the join screen, which show two and three of
 * these side by side. The point of showing them together is that the cashier is
 * building both bills while the guests stand there — a screen that shows one at
 * a time asks them to remember the other.
 *
 * It renders figures and never computes one: the amounts come from the server
 * (`CLAUDE.md` §5.1), including the running totals of a split that has not
 * happened yet.
 */
import { money, t } from "@/i18n";

export interface BillCardLine {
  /** The line's `idx` on its order — what the server moves things by. */
  key: number;
  name: string;
  qty: number;
  amount: number | null;
  /** A line already cooking. It still moves; the kitchen is simply not told. */
  sent?: boolean;
}

defineProps<{
  title: string;
  subtitle?: string;
  lines: BillCardLine[];
  /** `null` while the server has not answered yet — never a guess. */
  total?: number | null;
  tax?: number | null;
  /** What to say when the column is empty, rather than showing a blank box. */
  empty?: string;
  /** Tappable lines. Read-only columns leave it off. */
  interactive?: boolean;
}>();

const emit = defineEmits<{ pick: [key: number] }>();
</script>

<template>
  <section class="flex min-h-0 min-w-0 flex-col rounded-rpos border border-line bg-background">
    <header class="border-b border-line px-3 py-2">
      <p class="rpos-numeric font-bold">
        {{ title }}
      </p>
      <p
        v-if="subtitle"
        class="text-xs text-muted"
      >
        {{ subtitle }}
      </p>
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <p
        v-if="!lines.length"
        class="p-3 text-sm text-muted"
      >
        {{ empty ?? t("split.nothingHere") }}
      </p>

      <component
        :is="interactive ? 'button' : 'div'"
        v-for="line in lines"
        :key="line.key"
        :type="interactive ? 'button' : undefined"
        class="flex w-full min-h-tap items-baseline gap-2 border-b border-line px-3 py-2 text-start last:border-b-0"
        :class="interactive ? 'hover:bg-surface' : ''"
        @click="interactive && emit('pick', line.key)"
      >
        <span class="rpos-numeric shrink-0 font-bold">{{ line.qty }}×</span>
        <span class="min-w-0 flex-1">
          {{ line.name }}
          <span
            v-if="line.sent"
            class="ms-1 text-xs text-muted"
          >{{ t("split.inKitchen") }}</span>
        </span>
        <span class="rpos-numeric shrink-0">{{ line.amount === null ? "—" : money(line.amount) }}</span>
      </component>
    </div>

    <footer class="border-t border-line px-3 py-2">
      <div
        v-if="tax !== null && tax !== undefined"
        class="flex justify-between text-xs text-muted"
      >
        <span>{{ t("pay.tax") }}</span>
        <span class="rpos-numeric">{{ money(tax) }}</span>
      </div>
      <div class="flex justify-between font-bold">
        <span>{{ t("pay.total") }}</span>
        <span class="rpos-numeric">{{ total === null || total === undefined ? "—" : money(total) }}</span>
      </div>
    </footer>
  </section>
</template>
