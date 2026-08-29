/**
 * Customers, found by their number (FR-2.1 step 4, D-050).
 *
 * Nothing here searches locally. A till that filtered a cached list would miss
 * the customer a *different* till created an hour ago and make a second record
 * for them — which is how one person's delivery history becomes two.
 */
import { mutate, query } from "./client";

/** A row in the search results — enough to recognise a person, nothing more. */
export interface CustomerSummary {
  name: string;
  customer_name: string;
  mobile_no: string | null;
  tax_id: string | null;
  customer_type: string;
}

export interface CustomerAddress {
  name: string;
  address_title: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  phone: string | null;
}

export interface CustomerDetail extends CustomerSummary {
  /** Several, because a person has a home and a work (D-050). */
  addresses: CustomerAddress[];
}

/**
 * Who this could be.
 *
 * `phone` is the key and `name` is the fallback — deliberately the weaker of
 * the two, because "محمد" repeats a hundred times in any restaurant's database
 * and a number does not.
 */
export function searchCustomers(params: {
  phone?: string;
  name?: string;
}): Promise<CustomerSummary[]> {
  return query<CustomerSummary[]>("customer.search", params);
}

export function getCustomer(customer: string): Promise<CustomerDetail> {
  return query<CustomerDetail>("customer.get", { customer });
}

/**
 * Not deferrable. The order needs the customer's name the server assigns, and
 * a device that invented one would file the next order against a customer that
 * does not exist.
 */
export function createCustomer(payload: {
  phone: string;
  customer_name: string;
  tax_id?: string | null;
  is_company?: 0 | 1;
  address?: Partial<CustomerAddress> | null;
}): Promise<CustomerDetail> {
  return mutate<CustomerDetail>("customer.create", payload);
}

/** Not deferrable, for the same reason as `createCustomer`. */
export function addCustomerAddress(payload: {
  customer: string;
  address: Partial<CustomerAddress>;
}): Promise<{ address: string; addresses: CustomerAddress[] }> {
  return mutate("customer.add_address", payload);
}
