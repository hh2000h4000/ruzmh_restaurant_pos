import { defineStore } from "pinia";
import { ref } from "vue";

import type { OrderType, OrderTypeField } from "@/types/session";

/**
 * The order type's own questions, asked before an order is opened under it or
 * turned into it (FR-1.2, `D-409`).
 *
 * A delivery platform ships with "App Order No", required when the order opens.
 * The till never asked for it, so every order under a shipped platform was
 * refused by the server for a field nobody had been offered — on opening, and
 * on turning a bill into that platform (`D-408`).
 *
 * **Asked here, in the store, because four paths reach it**: *New*, a table, the
 * customer box and the conversion dialog all end in `create` or `changeType`. A
 * question each view had to remember is a question one of them would forget
 * (`CLAUDE.md` §5.5); the one dialog that answers it is mounted once, in `App`.
 */
export const useTypeFieldsStore = defineStore("typeFields", () => {
  /** The type being asked about, and what has been typed so far. */
  const asking = ref<{ type: OrderType; fields: OrderTypeField[] } | null>(null);
  let settle: ((values: Record<string, string> | null) => void) | null = null;

  /**
   * The answers keyed by each field's label, the shape the server reads — `{}`
   * at once for a type with nothing to ask, `null` if the cashier backs out.
   */
  function ask(type: OrderType): Promise<Record<string, string> | null> {
    const fields = (type.additional_fields ?? []).filter((field) => field.show_at !== "on_close");
    if (!fields.length) return Promise.resolve({});

    settle?.(null);
    asking.value = { type, fields };
    return new Promise((resolve) => {
      settle = resolve;
    });
  }

  function answer(values: Record<string, string> | null): void {
    asking.value = null;
    const done = settle;
    settle = null;
    done?.(values);
  }

  return { asking, ask, answer };
});
