/**
 * The bill's arithmetic, on the device (D-071).
 *
 * **This is not a second opinion about money.** `CLAUDE.md` §5.1 stands: the
 * backend computes, and its figure is the one the invoice carries. This exists
 * for the minutes when there is no backend to ask — a customer standing at the
 * counter while the line is down, and a payment that needs an amount (`09` §5).
 *
 * Three things make it safe to have at all:
 *
 * 1. **The inputs are the server's**, shipped in the session payload: the tax
 *    rate from the POS Profile's template, the cash-rounding step from the
 *    ERPNext `Currency`, and the rounding method from System Settings. Nothing
 *    here is guessed and nothing is hardcoded — a zero-rated outlet is a
 *    setting, not a branch in this file.
 * 2. **The algorithm is a port, not a rewrite.** Every function below mirrors
 *    the Frappe helper it is named after, including the parts that look strange:
 *    the epsilon in banker's rounding is there because IEEE-754 cannot represent
 *    a trailing 5 exactly, and dropping it would break ties the other way from
 *    the server on exactly the amounts a cashier notices.
 * 3. **Both sides are held to one checked-in contract.**
 *    `shared/totals_contract.json` carries the server's own answers, and a test
 *    on each side asserts against it. Two implementations that agree today drift
 *    apart the first time one is edited alone; the contract is what makes that a
 *    failing test instead of a customer being quoted the wrong number.
 *
 * When the queue drains, the server recomputes and **reports any difference**
 * rather than swallowing it. The point is not to be right without the server —
 * it is to be checkable against it.
 */

/** The settings the arithmetic needs, all of them the server's (`pricing`). */
export interface Pricing {
  currency: string;
  precision: number;
  /** Percent on the net total, from the POS Profile's tax template. */
  tax_rate: number;
  /**
   * D-091 — whether the menu price already contains the tax
   * (ERPNext's `included_in_print_rate`). Saudi menus normally do.
   */
  tax_inclusive: 0 | 1;
  /** BR-024 — the cash-rounding step, from the ERPNext `Currency`. */
  rounding_step: number;
  rounding_method: string;
}

export interface Totals {
  subtotal: number;
  discount_amount: number;
  tax_amount: number;
  total_amount: number;
}

export type DiscountType = "percentage" | "amount" | null;

/**
 * Frappe's `_bankers_rounding`, including its epsilon.
 *
 * Half-to-even, and the epsilon decides ties that floating point renders
 * *almost* exactly a half. Without it, 8.715 and its neighbours round the other
 * way from the server — small, and precisely the size a customer disputes.
 */
function bankersRounding(num: number, precision: number): number {
  if (num === 0) return 0;

  const sign = num < 0 ? -1 : 1;
  const multiplier = 10 ** precision;
  const scaled = round(Math.abs(num) * multiplier, 12);

  if (scaled === 0) return 0;

  const floorNum = Math.floor(scaled);
  const decimal = scaled - floorNum;
  const epsilon = 2 ** (Math.log2(scaled) - 52);

  const rounded =
    Math.abs(decimal - 0.5) < epsilon
      ? floorNum % 2 === 0
        ? floorNum
        : floorNum + 1
      : Math.round(scaled);

  return (sign * rounded) / multiplier;
}

/** Frappe's `_bankers_rounding_legacy` — the default on an untouched site. */
function bankersRoundingLegacy(num: number, precision: number): number {
  const multiplier = 10 ** precision;
  const scaled = round(precision ? num * multiplier : num, 8);

  const floorNum = Math.floor(scaled);
  const decimal = scaled - floorNum;

  let result: number;
  if (!precision && decimal === 0.5) {
    result = floorNum % 2 === 0 ? floorNum : floorNum + 1;
  } else if (decimal === 0.5) {
    result = floorNum + 1;
  } else {
    result = Math.round(scaled);
  }

  return precision ? result / multiplier : result;
}

/** Frappe's `_round_away_from_zero`, epsilon and all. */
function roundAwayFromZero(num: number, precision: number): number {
  if (num === 0) return 0;

  const epsilon = 2 ** (Math.log2(Math.abs(num)) - 52);
  return round(num + Math.sign(num) * epsilon, precision);
}

/**
 * Plain decimal rounding, used inside the helpers above the way Python's
 * `round` is — half away from zero at the digit, not JavaScript's half-up.
 */
function round(num: number, precision: number): number {
  const multiplier = 10 ** precision;
  const scaled = num * multiplier;
  // `Math.round` takes .5 upward even for negatives; Python takes it away from
  // zero. The sign is split out so the two agree.
  const sign = scaled < 0 ? -1 : 1;
  return (sign * Math.round(Math.abs(scaled))) / multiplier;
}

/** Frappe's `rounded`, dispatching on the site's configured method. */
function rounded(num: number, precision: number, method: string): number {
  if (method === "Banker's Rounding") return bankersRounding(num, precision);
  if (method === "Commercial Rounding") return roundAwayFromZero(num, precision);
  // "Banker's Rounding (legacy)" is Frappe's own fallback for an unset setting,
  // so an unknown method lands here rather than throwing at a till.
  return bankersRoundingLegacy(num, precision);
}

/** Frappe's `flt` with a precision — the site's rounding method applies. */
export function flt(value: number, precision: number, method: string): number {
  return rounded(value, precision, method);
}

/** Two decimals, the currency's precision. */
function money(value: number, pricing: Pricing): number {
  return flt(value, pricing.precision, pricing.rounding_method);
}

/**
 * Frappe's `round_based_on_smallest_currency_fraction` (BR-024).
 *
 * With no step configured it falls back to whole units, exactly as Frappe does
 * — which is the trap `utils/totals.py` documents: SAR ships with the field at
 * zero, and a shop that never set it rounds every bill to the riyal.
 */
export function roundToStep(value: number, pricing: Pricing): number {
  const step = pricing.rounding_step;
  const method = pricing.rounding_method;

  if (!step) return flt(rounded(value, 0, method), pricing.precision, method);

  const rest = remainder(value, step, pricing.precision, method);
  const settled = rest > step / 2 ? value + step - rest : value - rest;

  return flt(settled, pricing.precision, method);
}

/** Frappe's `remainder`. */
function remainder(numerator: number, denominator: number, precision: number, method: string): number {
  const multiplier = 10 ** precision;
  const value = precision
    ? ((numerator * multiplier) % (denominator * multiplier)) / multiplier
    : numerator % denominator;

  return flt(value, precision, method);
}

/** `utils/totals.discount_amount` — a percentage or a flat sum, never past the bill. */
export function discountAmount(
  subtotal: number,
  type: DiscountType,
  value: number,
  pricing: Pricing,
): number {
  if (!type || !value) return 0;

  if (type === "percentage") {
    // The server throws outside 0..100; a device with no server to ask clamps
    // rather than quoting a negative bill, and the replay will refuse it.
    const percent = Math.min(Math.max(value, 0), 100);
    return money((subtotal * percent) / 100, pricing);
  }

  return money(Math.min(value, subtotal), pricing);
}

/**
 * `utils/totals.compute` — the whole bill.
 *
 * FR-10.4: with tax added on top, the discount comes off the pre-tax subtotal
 * and VAT is recomputed on what is left; taking it off after tax would
 * under-collect.
 *
 * D-091: with tax included in the menu price, the figure the customer was
 * quoted *is* the total, and the tax is extracted from it rather than added to
 * it. `subtotal` stays the sum of the menu prices either way — it is what the
 * cashier and the customer are both looking at.
 */
export function computeTotals(
  lineAmounts: number[],
  discountType: DiscountType,
  discountValue: number,
  pricing: Pricing,
): Totals {
  const subtotal = money(
    lineAmounts.reduce((sum, amount) => sum + amount, 0),
    pricing,
  );
  const discount = discountAmount(subtotal, discountType, discountValue, pricing);
  const afterDiscount = money(subtotal - discount, pricing);

  let net: number;
  let tax: number;
  let total: number;

  if (pricing.tax_inclusive) {
    net = pricing.tax_rate
      ? money(afterDiscount / (1 + pricing.tax_rate / 100), pricing)
      : afterDiscount;
    tax = money(afterDiscount - net, pricing);
    total = afterDiscount;
  } else {
    net = afterDiscount;
    tax = money((net * pricing.tax_rate) / 100, pricing);
    total = money(net + tax, pricing);
  }

  return {
    subtotal,
    discount_amount: discount,
    tax_amount: tax,
    total_amount: roundToStep(total, pricing),
  };
}
