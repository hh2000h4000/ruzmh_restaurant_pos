# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A device prints its customers' receipts on its own computer (`D-402`).

A receipt printer joined by cable is reached only by the print agent on that
computer. Printers named alike on every computer — the owner names them the
same at every customer — made a receipt printer of one till, served by another
till's agent, print **at the other counter**: the job succeeded, nothing rang,
and the guest's receipt came out of the wrong printer.

So the device names its agent, and a cable printer it prints receipts on must
be one of that agent's. A network printer belongs to no computer and stays
free; kitchen tickets are not receipts and stay shared. One agent may still
serve two devices on purpose — a tablet beside the computer that holds its
printer — because the device says so; what is refused is the mismatch.

Refs: D-212, D-363, D-402
"""

import frappe
from frappe import _

#: Joined to one computer by a cable: only that computer's agent reaches it.
CABLED = ("windows", "usb")


def check_receipt_printer(doc, method=None) -> None:
	"""``POS Profile.validate`` — a cable receipt printer is on this device's own agent."""
	printer = doc.get("default_printer")
	if not printer:
		return

	kind, agent = frappe.get_cached_value("POS Printer", printer, ["connection_type", "print_agent"])
	if kind not in CABLED:
		return

	title = frappe.get_cached_value("POS Printer", printer, "title") or printer
	own = doc.get("rpos_print_agent")
	if not own:
		frappe.throw(
			_(
				"{0} is joined by cable to one computer. Choose this device's print agent — the one "
				"installed on its computer — before choosing it."
			).format(title)
		)
	if agent != own:
		frappe.throw(
			_(
				"{0} is on the computer of {1}, not on this device's ({2}). Receipts would come out at "
				"another counter. Choose a printer on this device's computer."
			).format(title, _agent_title(agent), _agent_title(own))
		)


def prepare(pos_profile: str, windows_printer_name: str, paper_width: str = "80mm") -> dict:
	"""This device's agent and receipt printer, made and joined in one step.

	Three records by hand — the agent, the printer, and both named on the
	device — is where a printer ended up on the wrong agent. Reuses what the
	device already has, so pressing it twice makes nothing twice.
	"""
	from restaurant_pos.utils.terminal_branch import branch_of

	name = (windows_printer_name or "").strip()
	if not name:
		frappe.throw(_("Enter the printer's name exactly as Windows lists it."))

	profile = frappe.get_doc("POS Profile", pos_profile)
	branch = branch_of(pos_profile)
	if not branch:
		frappe.throw(_("Choose the branch this device sells in."))

	agent = profile.get("rpos_print_agent") or (
		frappe.get_doc(
			{"doctype": "POS Print Agent", "title": profile.name, "branch": branch, "is_active": 1}
		)
		.insert()
		.name
	)

	printer = _own_printer(profile, agent) or (
		frappe.get_doc(
			{
				"doctype": "POS Printer",
				"title": _("{0} receipts").format(profile.name),
				"branch": branch,
				"is_active": 1,
				"print_agent": agent,
				"connection_type": "windows",
				"windows_printer_name": name,
				"printer_model": "generic",
				"paper_width": paper_width,
				"print_mode": "image",
				"cut_after_print": 1,
			}
		)
		.insert()
		.name
	)

	profile.rpos_print_agent = agent
	profile.default_printer = printer
	profile.save()
	return {"agent": agent, "printer": printer}


def _own_printer(profile, agent: str) -> str | None:
	"""The device's receipt printer, if it is already one on its own agent."""
	printer = profile.get("default_printer")
	if printer and frappe.get_cached_value("POS Printer", printer, "print_agent") == agent:
		return printer
	return None


def _agent_title(agent: str | None) -> str:
	if not agent:
		return _("no agent")
	return frappe.get_cached_value("POS Print Agent", agent, "title") or agent
