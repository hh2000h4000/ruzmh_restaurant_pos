# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""What the printing side of a site holds, in one line each.

A printer that prints nothing has several possible causes — no agent, a silent
agent, no template, a queue nobody is draining — and they look identical from
the till. This says which one it is.
"""

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds


def report() -> None:
	print("=== agents ===")
	agents = frappe.get_all(
		"POS Print Agent",
		fields=["name", "title", "branch", "is_active", "last_seen", "agent_version"],
		order_by="branch asc",
	)
	if not agents:
		print("  (none — nothing can print until an agent exists)")
	for agent in agents:
		if agent.last_seen:
			silent = int(time_diff_in_seconds(now_datetime(), agent.last_seen))
			seen = f"{silent}s ago" if silent < 3600 else f"{silent // 3600}h ago"
		else:
			seen = "never"
		state = "on" if agent.is_active else "OFF"
		print(f"  {agent.name}  {agent.title}  {agent.branch}  {state}  seen={seen}")

	print("\n=== printers ===")
	for printer in frappe.get_all(
		"POS Printer",
		fields=["name", "title", "branch", "print_agent", "connection_type", "ip_address", "is_active"],
		order_by="branch asc",
	):
		where = printer.ip_address or printer.connection_type
		owner = printer.print_agent or "NO AGENT"
		state = "on" if printer.is_active else "OFF"
		print(f"  {printer.title}  {printer.branch}  {where}  agent={owner}  {state}")

	print("\n=== templates ===")
	for template in frappe.get_all(
		"POS Print Template",
		fields=["name", "template_type", "paper_width", "branch", "is_default"],
		order_by="template_type asc",
	):
		scope = template.branch or "all branches"
		default = " default" if template.is_default else ""
		print(f"  {template.template_type}  {template.paper_width}  {scope}{default}  {template.name}")

	print("\n=== queue ===")
	counts = frappe.get_all(
		"POS Print Job",
		fields=["status", "count(name) as n"],
		group_by="status",
	)
	if not counts:
		print("  (empty)")
	for row in counts:
		print(f"  {row.status}: {row.n}")

	stuck = frappe.get_all(
		"POS Print Job",
		filters={"status": "failed"},
		fields=["name", "printer", "job_type", "error"],
		order_by="creation desc",
		limit=5,
	)
	for job in stuck:
		print(f"  FAILED {job.name} {job.job_type} on {job.printer}: {job.error}")

	print("\n=== zatca phase 1 ===")
	# The QR is only as present as the VAT number, and its absence is silent:
	# the receipt prints, looks finished, and is not a valid simplified invoice.
	for company in frappe.get_all("Company", fields=["name", "tax_id"]):
		if company.tax_id:
			print(f"  {company.name}: VAT {company.tax_id} — QR will print")
		else:
			print(f"  {company.name}: NO VAT NUMBER — receipts print without a ZATCA QR")

	print("\n=== role ===")
	exists = frappe.db.exists("Role", "Restaurant Print Agent")
	print(f"  Restaurant Print Agent: {'present' if exists else 'MISSING'}")
