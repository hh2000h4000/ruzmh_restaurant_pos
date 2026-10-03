import { defineStore } from "pinia";
import { ref } from "vue";

import { getPrintAlerts } from "@/api/kitchen";
import { useConnectionStore } from "@/stores/connection";
import { useSessionStore } from "@/stores/session";

/**
 * The bell's badge (`D-298`): kitchen tickets in this branch that never reached
 * paper and nobody has answered for.
 *
 * A store, not the pane's own state, because three places move it: the till
 * asking now and then, the order screen once a send has settled, and the pane
 * after the cashier answers an alert.
 */
export const useAlertsStore = defineStore("alerts", () => {
  const open = ref(0);

  async function refresh(): Promise<void> {
    const profile = useSessionStore().profile?.name;
    if (!profile || !useConnectionStore().isOnline) return;

    try {
      open.value = (await getPrintAlerts(profile)).open;
    } catch {
      // The next check asks again; a badge one minute stale is not worth a
      // message over the items.
    }
  }

  return { open, refresh };
});
