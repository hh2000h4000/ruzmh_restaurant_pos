# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The print agent, installed from the till in one step (`D-424`, `docs/11` §4).

Setting a till up to print direct was six steps in three places: pair the till,
find the agent's file, make a POS Print Agent in the desk, issue its code, type
the address and the code into the agent, and come back to the desk to point the
terminal at it. Two of them went wrong on the user's own laptop in one
afternoon.

The till already knows everything those steps ask for: the site's address (its
own page), which terminal it is, and that it is trusted. So one request makes
the agent or takes the terminal's own, issues its code, sets the terminal to
print direct, and hands back the agent's file **named with the address and the
code** — the agent reads its own name and pairs without a window. Odoo's IoT
box does the same with a ready command carrying its token.

**The address is the till's page** (the request's `Origin`), so the agent takes
paper from exactly the page that installed it: the refusal of `D-421`, a till
at one address and its agent paired at another, cannot happen.
"""

from urllib.parse import urlsplit

import frappe
from frappe import _

from restaurant_pos.utils import terminal_branch
from restaurant_pos.utils.audit import log_audit
from restaurant_pos.utils.permissions import assert_permission, validate_branch_access

#: How long the till has to start the download after asking for it.
TICKET_SECONDS = 300

_TICKET_PREFIX = "rpos:agent-file:"

#: The name the agent reads itself paired from (`print_agent/rpos_print_agent_app.py`).
FILE_PREFIX = "RPOS-Print-Agent"


def prepare(pos_profile: str, origin: str | None, move: bool = False) -> dict:
	"""Everything but the file: the agent, its code, the terminal, and a ticket for the download.

	``{"needs_move": host}`` instead when the terminal's agent is on a computer
	already — re-pairing it here stops that one printing, which is the cashier
	printer's computer as often as not. The till asks, and calls again with
	``move``.
	"""
	branch = terminal_branch.required(pos_profile)
	validate_branch_access(branch)
	assert_permission("can_set_up_devices")

	file_url = frappe.db.get_single_value("Restaurant POS Settings", "print_agent_file")
	if not file_url:
		frappe.throw(_("Upload the print agent's program in Restaurant POS Settings first."))
	address = _address(origin)

	agent, host = _agent_for(pos_profile, branch)
	if host and not move:
		return {"needs_move": host}

	from restaurant_pos.restaurant_pos.doctype.pos_print_agent.pos_print_agent import new_code

	code = new_code(frappe.get_doc("POS Print Agent", agent))
	# `D-425` — the page that installed it, whatever address the agent itself
	# reaches the server at: paper from this till is taken.
	frappe.db.set_value("POS Print Agent", agent, "till_origin", page_origin(address), update_modified=False)
	frappe.db.set_value("POS Profile", pos_profile, {"rpos_print_route": "direct", "rpos_print_agent": agent})
	frappe.clear_document_cache("POS Profile", pos_profile)

	filename = file_name(address, code)
	ticket = frappe.generate_hash(length=32)
	frappe.cache().set_value(
		_TICKET_PREFIX + ticket,
		{"file_url": file_url, "filename": filename, "user": frappe.session.user},
		expires_in_sec=TICKET_SECONDS,
	)

	log_audit(
		"print_agent_installed",
		branch=branch,
		pos_profile=pos_profile,
		details={"agent": agent, "moved_from": host},
	)
	return {"ticket": ticket, "filename": filename, "agent": agent}


def _agent_for(pos_profile: str, branch: str) -> tuple[str, str | None]:
	"""The terminal's own agent and the computer it is on — or a new agent, on none.

	**Never another terminal's.** An agent two terminals share is the agent of a
	computer serving both; re-pairing it here would take it from the other. Such
	a terminal gets an agent of its own.
	"""
	current = frappe.db.get_value("POS Profile", pos_profile, "rpos_print_agent")
	if current and frappe.db.get_value("POS Print Agent", current, "is_active"):
		if not other_terminals_on(current, pos_profile):
			return current, frappe.db.get_value("POS Print Agent", current, "host_name")

	agent = frappe.get_doc(
		{
			"doctype": "POS Print Agent",
			"title": _("Print agent of {0}").format(pos_profile),
			"branch": branch,
			"is_active": 1,
		}
	)
	# Made by a manager at the till, who has no desk rights on the form: the
	# permission set authorised it above (`D-424`), as it does every till action.
	agent.insert(ignore_permissions=True)
	return agent.name, None


def other_terminals_on(agent: str, pos_profile: str) -> list[str]:
	"""The other terminals printing through this agent."""
	return frappe.get_all(
		"POS Profile", filters={"rpos_print_agent": agent, "name": ("!=", pos_profile)}, pluck="name"
	)


def _address(origin: str | None) -> tuple[str, str, int]:
	"""The till's own page — scheme, host and port — or refused."""
	parts = urlsplit(origin or "")
	if parts.scheme not in ("http", "https") or not parts.hostname:
		frappe.throw(_("Open the till from the site's address to install the print agent."))
	return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


def page_origin(address: tuple[str, str, int]) -> str:
	"""The till's page as a browser names it in `Origin`: no port when it is the scheme's own."""
	scheme, host, port = address
	return f"{scheme}://{host}" if port == (443 if scheme == "https" else 80) else f"{scheme}://{host}:{port}"


def file_name(address: tuple[str, str, int], code: str) -> str:
	"""`RPOS-Print-Agent_https_pos.example.com_443_48217735.exe` — read back by the agent.

	**A `.localhost` name becomes `127.0.0.1`** (`D-425`). Chrome resolves every
	such name to this computer, as RFC 6761 says; Windows does not, and the
	agent reaching for `rpos.localhost` was told no such host. The agent still
	takes the page's own paper: `till_origin` keeps the name the till uses.
	"""
	scheme, host, port = address
	if host == "localhost" or host.endswith(".localhost"):
		host = "127.0.0.1"
	return f"{FILE_PREFIX}_{scheme}_{host}_{port}_{code}.exe"


def download(ticket: str) -> None:
	"""Put the agent's file in this response, once, for whoever asked for the ticket."""
	key = _TICKET_PREFIX + (ticket or "")
	payload = frappe.cache().get_value(key)
	frappe.cache().delete_value(key)
	if not payload or payload.get("user") != frappe.session.user:
		frappe.throw(_("This download has expired. Ask for it again from the till."), frappe.PermissionError)

	# The bytes as stored: `File.get_content` hands back text for anything that
	# decodes, and a program that happens to is still a program.
	path = frappe.get_doc("File", {"file_url": payload["file_url"]}).get_full_path()
	with open(path, "rb") as program:
		frappe.local.response.filecontent = program.read()
	frappe.local.response.filename = payload["filename"]
	frappe.local.response.type = "download"
