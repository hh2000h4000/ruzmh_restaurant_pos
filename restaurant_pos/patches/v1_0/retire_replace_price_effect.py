"""Turn any surviving `replace` modifier option into the `add` it always was (`D-241`).

`replace` promised to become the item's price and was coded as an addition, in
the server and in the offline port alike (`D-076` called it out and kept it, so
that the device and the invoice would not disagree). The option is gone now, and
a row still holding the value would be a Select outside its own options: the
form refuses to save it and the till has no branch for it.

`add` is not a guess at what the manager meant — it is exactly what the row has
been charging all along, so no bill changes amount because of this patch.
"""

import frappe


def execute():
	rows = frappe.get_all("POS Modifier Option", filters={"price_effect": "replace"}, pluck="name")
	if not rows:
		return

	for name in rows:
		frappe.db.set_value("POS Modifier Option", name, "price_effect", "add", update_modified=False)

	frappe.db.commit()
