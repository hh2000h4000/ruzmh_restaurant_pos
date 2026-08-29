# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Finding and creating a customer at the till (FR-2.1 step 4, D-050).

**Most orders have no customer, on purpose.** A walk-in buying coffee is not
somebody to file, and ``call_name`` already covers the "Hamza, table four" case
without creating a record (``FR-2.11``). A customer is attached when there is a
reason: a delivery that needs an address, an account that will be billed, or a
regular the shop wants a history for.

**The key is the mobile number, not the name.** "محمد" repeats a hundred times
in any restaurant's database; a phone does not. Every till in the Gulf
identifies a customer by their number, and so does this one.

**One call, not four.** ERPNext keeps the number two documents away from the
customer — ``Customer.mobile_no`` is fetched from ``customer_primary_contact``,
and ``Contact.mobile_no`` from its ``phone_nos`` rows — so creating a customer
by phone means a Customer, a Contact, a phone row and a link. Orchestrating
that from the screen would leave a customer with no number one dropped request
away: unfindable, and created again tomorrow.

Refs: FR-2.1, FR-2.11, D-050
"""

import re

import frappe
from frappe import _

#: What a Saudi mobile is once the country code and any leading zero are gone.
#: Matching on the tail is what makes 0501234567, +966501234567 and 966501234567
#: the same person — which they are, and a search that says otherwise creates a
#: second record for somebody who is already there.
LOCAL_DIGITS = 9


def normalise_phone(phone: str | None) -> str:
	"""The digits a number is recognised by, whatever way it was typed."""
	digits = re.sub(r"\D", "", phone or "")
	return digits[-LOCAL_DIGITS:] if len(digits) > LOCAL_DIGITS else digits


def search(phone: str | None = None, name: str | None = None, limit: int = 10) -> list[dict]:
	"""Who this could be (FR-2.1 step 4).

	Phone first and by preference; the name is there for the till that has a
	regular's name and not their number, and it is a worse key on purpose.
	"""
	tail = normalise_phone(phone)
	found: dict[str, dict] = {}

	if tail:
		# The customer's own copy, when a primary contact set it.
		for row in _fetch({"mobile_no": ("like", f"%{tail}")}, limit):
			found[row["name"]] = row

		# And through the contact, for customers made outside this app.
		contacts = frappe.get_all(
			"Contact Phone",
			filters={"phone": ("like", f"%{tail}"), "parenttype": "Contact"},
			fields=["parent"],
			limit=limit * 2,
		)
		for customer in _customers_of([row.parent for row in contacts]):
			if customer not in found:
				for row in _fetch({"name": customer}, 1):
					found[row["name"]] = row

	elif name and name.strip():
		for row in _fetch({"customer_name": ("like", f"%{name.strip()}%")}, limit):
			found[row["name"]] = row

	return list(found.values())[:limit]


def _fetch(filters: dict, limit: int) -> list[dict]:
	return frappe.get_all(
		"Customer",
		filters={**filters, "disabled": 0},
		fields=["name", "customer_name", "mobile_no", "tax_id", "customer_type"],
		limit=limit,
	)


def _customers_of(contacts: list[str]) -> list[str]:
	if not contacts:
		return []

	return [
		row.link_name
		for row in frappe.get_all(
			"Dynamic Link",
			filters={
				"parent": ("in", contacts),
				"parenttype": "Contact",
				"link_doctype": "Customer",
			},
			fields=["link_name"],
		)
	]


def details(customer: str) -> dict:
	"""Everything the till shows about one customer, addresses included."""
	row = frappe.db.get_value(
		"Customer",
		customer,
		["name", "customer_name", "mobile_no", "tax_id", "customer_type"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Customer {0} does not exist.").format(customer))

	row["addresses"] = addresses_of(customer)
	return row


def addresses_of(customer: str) -> list[dict]:
	"""A customer's addresses — several, because a person has a home and a work.

	Modelled ERPNext's way: an ``Address`` joined by a ``Dynamic Link``, so the
	address outlives any one order and the next delivery picks from the list
	rather than being typed again.
	"""
	links = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Address"},
		pluck="parent",
	)
	if not links:
		return []

	return frappe.get_all(
		"Address",
		filters={"name": ("in", links), "disabled": 0},
		fields=["name", "address_title", "address_line1", "address_line2", "city", "phone"],
		order_by="is_primary_address desc, modified desc",
	)


def create(
	*,
	phone: str,
	customer_name: str,
	tax_id: str | None = None,
	is_company: bool = False,
	address: dict | None = None,
) -> dict:
	"""Make a customer, with the number attached where ERPNext keeps it.

	Refuses a duplicate rather than making a second record for somebody already
	there: two customers on one number is how a loyalty balance splits in half
	and a delivery history stops being a history.
	"""
	if not normalise_phone(phone):
		frappe.throw(_("A mobile number is required."))

	if not (customer_name or "").strip():
		frappe.throw(_("A name is required."))

	existing = search(phone=phone, limit=1)
	if existing:
		frappe.throw(
			_("{0} already uses this number.").format(existing[0]["customer_name"]),
			frappe.DuplicateEntryError,
		)

	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": customer_name.strip(),
			"customer_type": "Company" if is_company else "Individual",
			"customer_group": _default("Customer Group"),
			"territory": _default("Territory"),
			# ZATCA wants the buyer's VAT number on a standard invoice, which is
			# what a company gets. Asked once, here, rather than chased later.
			"tax_id": (tax_id or "").strip() or None,
		}
	)
	customer.insert(ignore_permissions=True)

	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": customer_name.strip(),
			"phone_nos": [{"phone": phone.strip(), "is_primary_mobile_no": 1, "is_primary_phone": 1}],
			"links": [{"link_doctype": "Customer", "link_name": customer.name}],
		}
	)
	contact.insert(ignore_permissions=True)

	# Setting this is what makes `Customer.mobile_no` fetch, and so what makes
	# the customer findable by phone at all.
	customer.db_set("customer_primary_contact", contact.name, update_modified=False)
	customer.db_set("mobile_no", contact.mobile_no or phone.strip(), update_modified=False)

	if address:
		add_address(customer.name, address)

	return details(customer.name)


def add_address(customer: str, address: dict) -> str:
	"""Attach an address to a customer (FR-2.1 step 4).

	The first one becomes the primary, so a delivery order has something to
	print without anybody choosing.
	"""
	line = (address.get("address_line1") or "").strip()
	if not line:
		frappe.throw(_("An address line is required."))

	first = not addresses_of(customer)

	doc = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": (address.get("address_title") or "").strip()
			or frappe.db.get_value("Customer", customer, "customer_name"),
			"address_type": "Shipping",
			"address_line1": line,
			"address_line2": (address.get("address_line2") or "").strip() or None,
			"city": (address.get("city") or "").strip() or _("Unknown"),
			# ERPNext insists on one, and it is the restaurant's — asking a
			# cashier which country a delivery is in is a question about the
			# software, not about the customer at the counter.
			"country": (address.get("country") or "").strip() or _default_country(),
			"phone": (address.get("phone") or "").strip() or None,
			"is_primary_address": 1 if first else 0,
			"is_shipping_address": 1,
			"links": [{"link_doctype": "Customer", "link_name": customer}],
		}
	)
	doc.insert(ignore_permissions=True)

	if first:
		frappe.db.set_value("Customer", customer, "customer_primary_address", doc.name, update_modified=False)

	return doc.name


def _default_country() -> str:
	"""The company's country, because that is where the restaurant delivers."""
	country = frappe.db.get_value("Company", {}, "country")
	if country:
		return country

	fallback = frappe.db.get_value("Country", {}, "name")
	if not fallback:
		frappe.throw(_("This site has no Country."))
	return fallback


def _default(doctype: str) -> str:
	"""A leaf group or territory, because ERPNext demands one and nobody cares.

	Asking a cashier which Territory a takeaway belongs to is a question about
	ERPNext, not about the customer in front of them.
	"""
	value = frappe.db.get_value(doctype, {"is_group": 0}, "name")
	if not value:
		frappe.throw(_("This site has no {0}.").format(_(doctype)))
	return value
