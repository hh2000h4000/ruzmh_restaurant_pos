/**
 * Which of the server's messages the cashier reads (`D-270`).
 *
 * A refund refused because a gift card paid the bill came back as «Payment
 * methods refreshed» — ERPNext's own note, printed before our refusal and
 * picked because it was first.
 */
import { describe, expect, it } from "vitest";

import { readError } from "@/api/client";

function messages(...rows: Record<string, unknown>[]): { _server_messages: string } {
  return { _server_messages: JSON.stringify(rows.map((row) => JSON.stringify(row))) };
}

describe("reading a refusal", () => {
  it("reads the refusal, not a note printed before it", () => {
    const error = readError(
      messages(
        { message: "Payment methods refreshed. Please review before proceeding.", alert: 1 },
        { message: "The gift card paid 53.00 of this bill.", raise_exception: 1 },
      ),
      417,
    );

    expect(error.message).toBe("The gift card paid 53.00 of this bill.");
  });

  it("reads the last message that is not an alert when none is marked", () => {
    const error = readError(messages({ message: "note", alert: 1 }, { message: "the reason" }), 417);

    expect(error.message).toBe("the reason");
  });

  it("still reads a single message", () => {
    expect(readError(messages({ message: "only one" }), 417).message).toBe("only one");
  });
});
