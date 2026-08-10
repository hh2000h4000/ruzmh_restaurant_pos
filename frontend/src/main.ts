import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import router from "./router";
import "./styles/main.css";

/**
 * Arabic RTL is the default, not a mode (03_frontend_vue_rules.md).
 *
 * Set before mount so the first paint is already correct — flipping direction
 * after render is visible as a jump.
 */
document.documentElement.setAttribute("dir", "rtl");
document.documentElement.setAttribute("lang", "ar");

createApp(App).use(createPinia()).use(router).mount("#app");
