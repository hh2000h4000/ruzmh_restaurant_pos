import { createRouter, createWebHistory } from "vue-router";

import { useSessionStore } from "@/stores/session";

/**
 * Routes follow the screen map in 06_UI_UX_Flow.md.
 *
 * Views are lazy so the first paint does not carry the payment screen. The
 * routes for screens not yet built are deliberately absent rather than stubbed
 * — a route to an empty page is worse than a 404 during development.
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
    {
      path: "/",
      name: "home",
      component: () => import("@/views/HomeView.vue"),
    },
    {
      path: "/order/new/:orderType",
      name: "new-order",
      component: () => import("@/views/HomeView.vue"),
    },
    {
      path: "/shift/open",
      name: "open-shift",
      component: () => import("@/views/HomeView.vue"),
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
