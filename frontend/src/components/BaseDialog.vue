<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";

/**
 * One modal for the whole app.
 *
 * Focus is trapped and Escape closes, because a cashier works at speed and a
 * dialog that swallows the keyboard is worse than no dialog. Destructive
 * confirmations use this too (06 §Design Principles 4).
 */
const props = defineProps<{
  open: boolean;
  title: string;
  /** Escape and the backdrop do not close a dialog that must be answered. */
  dismissible?: boolean;
}>();

const emit = defineEmits<{ close: [] }>();

const panel = ref<HTMLElement | null>(null);
let lastFocused: HTMLElement | null = null;

function requestClose(): void {
  if (props.dismissible !== false) emit("close");
}

function onKeydown(event: KeyboardEvent): void {
  if (!props.open) return;

  if (event.key === "Escape") {
    requestClose();
    return;
  }

  if (event.key !== "Tab" || !panel.value) return;

  const focusable = panel.value.querySelectorAll<HTMLElement>(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
  );
  if (!focusable.length) return;

  const first = focusable[0];
  const last = focusable[focusable.length - 1];

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

watch(
  () => props.open,
  async (isOpen) => {
    if (isOpen) {
      lastFocused = document.activeElement as HTMLElement | null;
      await new Promise((resolve) => requestAnimationFrame(resolve));
      panel.value?.querySelector<HTMLElement>("input, button")?.focus();
    } else {
      lastFocused?.focus();
    }
  },
);

onMounted(() => document.addEventListener("keydown", onKeydown));
onUnmounted(() => document.removeEventListener("keydown", onKeydown));
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      @click.self="requestClose"
    >
      <div
        ref="panel"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        class="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-rpos bg-surface p-5 shadow-xl"
      >
        <h2 class="mb-4 text-lg font-semibold">
          {{ title }}
        </h2>
        <slot />
      </div>
    </div>
  </Teleport>
</template>
