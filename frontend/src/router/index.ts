import { createRouter, createWebHistory } from "vue-router";

import { useSessionStore } from "@/stores/session";

/**
 * Routes follow the screen map in 06_UI_UX_Flow.md.
 *
 * Views are lazy so the first paint does not carry the order screen. Screens
 * that do not exist yet are absent rather than stubbed — a route to an empty
 * page hides what is missing.
 */
const router = createRouter({
  history: createWebHistory("/restaurant-pos/"),
  routes: [
    {
      path: "/setup",
      name: "setup",
      component: () => import("@/views/SelectProfileView.vue"),
      meta: { requiresSession: false },
    },
    /**
     * The till, with no bill in hand yet (D-055).
     *
     * It was a screen of its own — order types on the left, open orders on the
     * right — and both of those are panes of the order screen, so it was a
     * second way to do what this one already does. `name: "home"` is kept: it
     * is still where "back to the floor" means.
     */
    {
      path: "/",
      name: "home",
      component: () => import("@/views/OrderView.vue"),
    },
    {
      path: "/tables/:orderType",
      name: "tables",
      component: () => import("@/views/TablesView.vue"),
    },
    {
      path: "/order/new/:orderType",
      name: "new-order",
      component: () => import("@/views/OrderView.vue"),
    },
    {
      path: "/order/:orderName",
      name: "order",
      component: () => import("@/views/OrderView.vue"),
    },
    {
      path: "/payment/:orderName",
      name: "payment",
      component: () => import("@/views/PaymentView.vue"),
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: { name: "home" },
    },
  ],
});

router.beforeEach((to) => {
  if (to.meta.requiresSession === false) return true;

  // Every screen but setup needs the terminal configuration; without it there
  // is no branch, no menu and no permissions to render against.
  const session = useSessionStore();
  return session.isLoaded ? true : { name: "setup" };
});

export default router;
