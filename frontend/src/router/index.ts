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
    {
      path: "/",
      name: "home",
      component: () => import("@/views/HomeView.vue"),
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
