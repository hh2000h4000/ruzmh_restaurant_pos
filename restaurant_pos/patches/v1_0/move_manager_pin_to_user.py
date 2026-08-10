# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Drop role-scoped manager PINs left behind by the move to per-user PINs.

``manager_pin`` was removed from ``POS Permission Set`` (DECISIONS.md D-016).
Removing a field from the DocType JSON does not remove its stored credential:
the value lives in ``__Auth``, keyed by doctype/name/fieldname, and would sit
there indefinitely.

The PINs are not migrated to users. A role PIN was shared by everyone holding
that role, so there is no correct person to attach it to — carrying it over
would recreate the accountability gap the move exists to close. Managers set a
fresh personal PIN.

Idempotent: deleting rows that are already gone is a no-op.
"""

import frappe


def execute():
	auth = frappe.qb.Table("__Auth")
	frappe.qb.from_(auth).delete().where(
		(auth.doctype == "POS Permission Set") & (auth.fieldname == "manager_pin")
	).run()
