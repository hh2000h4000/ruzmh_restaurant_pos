<script setup lang="ts">
import { locale, setLocale, t } from "@/i18n";

/**
 * The label is the language you get by pressing it, written in that language —
 * "English" on an Arabic screen. A flag would be wrong (Arabic is not a
 * country) and a globe icon says nothing about which way the switch goes.
 */
function toggle(): void {
  setLocale(locale.value === "ar" ? "en" : "ar");
}
</script>

<template>
  <button
    type="button"
    class="min-h-tap rounded-rpos border border-muted/30 px-3 py-1.5 text-sm font-medium transition hover:bg-surface focus:outline-none focus:ring-2 focus:ring-primary"
    :lang="locale === 'ar' ? 'en' : 'ar'"
    @click="toggle"
  >
    {{ t("lang.other") }}
  </button>
</template>
