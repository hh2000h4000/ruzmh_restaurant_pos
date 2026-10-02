<script lang="ts">
/**
 * The dialogs open now, innermost last (D-292). A combo's item opens its
 * add-ons over the combo, and Escape pressed there closed both: every open
 * dialog answered the key. Only the innermost does now.
 */
const opened: object[] = [];
</script>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";

/**
 * One modal for the whole app.
 *
 * Focus is trapped and Escape closes, because a cashier works at speed and a
 * dialog that swallows the keyboard is worse than no dialog. Destructive
 * confirmations use this too (06 §Design Principles 4).
 */
const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    /**
     * Escape and the backdrop do not close a dialog that must be answered.
     *
     * **Defaulted explicitly, and that is the whole point** (`D-138`). Vue casts
     * an absent Boolean prop to `false`, so every dialog that did not pass this
     * was silently sealed: no Escape, no backdrop, and for some of them no way
     * out but the one button somebody remembered to draw. Seven of them were
     * like that, including the tender sheet a cashier meets on every sale.
     *
     * Nothing in the app ever passed `false`, so the case this was invented for
     * has never existed — it is kept because a destructive confirmation is a
     * real thing to want, and now it costs a deliberate word to get.
     */
    dismissible?: boolean;
    /**
     * Room for columns. The default is a form's width; splitting a bill puts two
     * bills side by side and joining one puts three, and a cashier comparing them
     * cannot do it through a letterbox.
     */
    wide?: boolean;
  }>(),
  { dismissible: true, wide: false },
);

const emit = defineEmits<{ close: [] }>();

const panel = ref<HTMLElement | null>(null);
let lastFocused: HTMLElement | null = null;
const token = {};

function leaveStack(): void {
  const at = opened.indexOf(token);
  if (at >= 0) opened.splice(at, 1);
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) opened.push(token);
    else leaveStack();
  },
  { immediate: true },
);

function requestClose(): void {
  if (props.dismissible !== false) emit("close");
}

function onKeydown(event: KeyboardEvent): void {
  if (!props.open || opened[opened.length - 1] !== token) return;

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
onUnmounted(() => {
  document.removeEventListener("keydown", onKeydown);
  leaveStack();
});
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
        :class="['max-h-[90vh] w-full overflow-y-auto rounded-rpos bg-surface p-5 shadow-xl', wide ? 'max-w-5xl' : 'max-w-lg']"
      >
        <h2 class="mb-4 text-lg font-semibold">
          {{ title }}
        </h2>
        <slot />
        <!-- What answers the dialog stays in reach however long the body is:
             a sell sheet with two keypads ran past the screen and hid its own
             button below the fold. `-bottom-5`, not `bottom-0`: sticky is
             measured inside the panel's padding, so `bottom-0` lifts it p-5
             over the body's last row. -->
        <div
          v-if="$slots.footer"
          data-dialog-footer
          class="sticky -bottom-5 -mx-5 -mb-5 mt-4 border-t border-line bg-surface px-5 pb-5 pt-3"
        >
          <slot name="footer" />
        </div>
      </div>
    </div>
  </Teleport>
</template>
