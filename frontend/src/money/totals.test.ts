import { describe, expect, it } from "vitest";

import { computeTotals, type DiscountType, type Pricing } from "./totals";

import contract from "../../../shared/totals_contract.json";

/**
 * The device's arithmetic, held to the server's own answers (D-071).
 *
 * `shared/totals_contract.json` is generated from `utils/totals.py` by
 * `scripts/wsl-write-totals-contract.sh`. A Python test asserts the same file,
 * so the two implementations are pinned to one set of figures rather than to
 * each other.
 *
 * **This is the test that makes offline selling defensible at all.** Two
 * implementations of money agree on the day they are written and drift the
 * first time one is edited alone; without this the drift would surface as a
 * customer being quoted one number and charged another, days later, with
 * nothing to point at.
 *
 * When it fails, the question is which side is wrong — never "regenerate the
 * contract until it passes".
 */
interface Case {
  name: string;
  lines: number[];
  discount_type: DiscountType;
  discount_value: number;
  expect: {
    subtotal: number;
    discount_amount: number;
    tax_amount: number;
    total_amount: number;
  };
}

interface Profile {
  pricing: Pricing;
  cases: Case[];
}

const profiles = contract.profiles as unknown as Profile[];

describe("the device computes what the server computes", () => {
  it("has a contract to be held to", () => {
    expect(profiles.length).toBeGreaterThan(1);
    expect(profiles.some((profile) => profile.pricing.tax_rate > 0)).toBe(true);
  });

  for (const profile of profiles) {
    describe(`at ${profile.pricing.tax_rate}% tax`, () => {
      for (const scenario of profile.cases) {
        it(scenario.name, () => {
          const totals = computeTotals(
            scenario.lines,
            scenario.discount_type,
            scenario.discount_value,
            profile.pricing,
          );

          expect(totals).toEqual(scenario.expect);
        });
      }
    });
  }
});
