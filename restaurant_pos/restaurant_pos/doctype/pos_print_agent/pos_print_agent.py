# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import secrets

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, get_url, now_datetime

#: How long a pairing code works (`D-212`). Long enough to walk from the desk to
#: the restaurant's computer and run the installer; short enough that a code on
#: a photographed screen is dead by the time anybody could use it.
PAIRING_MINUTES = 10

#: Eight digits: a hundred million codes, against five wrong guesses per device
#: every five minutes, inside a ten-minute window.
PAIRING_DIGITS = 8

#: The role the agent's user carries, and the only one it carries.
#:
#: Frappe creates a Role named in a DocType's permissions during migrate, so
#: this is defined by `pos_print_job.json` rather than by a fixture.
AGENT_ROLE = "Restaurant Print Agent"

#: Reserved by RFC 2606 — it can never resolve, so the agent's user can never
#: be mailed by accident.
AGENT_EMAIL_DOMAIN = "print-agent.invalid"


class POSPrintAgent(Document):
	def after_insert(self):
		self.create_user()

	def create_user(self) -> None:
		"""Give the agent a Frappe user to sign in as.

		The agent authenticates with Frappe's own API key and secret rather than
		a scheme of our own: a token header we wrote would be a second way to
		prove identity, with its own comparison to get wrong. Frappe already has
		one that the whole framework honours.

		A System User, because a Website User cannot hold DocType roles — which
		is the entire mechanism keeping this account away from everything except
		its own print jobs.
		"""
		email = f"{self.name.lower()}@{AGENT_EMAIL_DOMAIN}"
		if frappe.db.exists("User", email):
			self.db_set("user", email, update_modified=False)
			return

		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": self.title,
				"user_type": "System User",
				"send_welcome_email": 0,
				# No password is ever set: this account exists to hold API keys,
				# and a login form it can pass is a login form somebody else can.
				"roles": [{"role": AGENT_ROLE}],
			}
		)
		user.insert(ignore_permissions=True)
		self.db_set("user", user.name, update_modified=False)

	def on_trash(self):
		"""Take the user with it.

		An agent removed but whose credentials still work is a key to the print
		queue that nothing in the interface admits exists.
		"""
		if self.user and frappe.db.exists("User", self.user):
			frappe.delete_doc("User", self.user, ignore_permissions=True, force=True)

	def seen(self, *, version: str | None = None, host: str | None = None) -> None:
		"""Record that the agent asked for work.

		Written with ``db_set`` and no modification stamp: this happens every two
		seconds per agent, and a version row for each would bury the document's
		real history under a heartbeat.
		"""
		self.db_set(
			{
				"last_seen": now_datetime(),
				"agent_version": version or self.agent_version,
				"host_name": host or self.host_name,
			},
			update_modified=False,
		)


@frappe.whitelist()
def generate_keys(agent: str) -> str:
	"""Issue the agent's API secret, and return it exactly once.

	Frappe stores the secret encrypted and has no interface to read it back, so
	the value returned here is the only copy. That is the intended property, not
	a limitation to work around: an administrator who loses it generates a new
	one, which also revokes the old.
	"""
	doc = frappe.get_doc("POS Print Agent", agent)
	doc.check_permission("write")

	api_key, api_secret = _issue_keys(doc)
	return f"{api_key}:{api_secret}"


def _issue_keys(doc) -> tuple[str, str]:
	"""A new secret for the agent's user — the one place keys are made.

	Both doors come through here: an administrator pressing Generate Keys, and a
	machine exchanging a pairing code (`D-212`). A new secret revokes the old,
	so an agent still holding it stops printing.
	"""
	if not doc.user:
		frappe.throw(_("This agent has no user yet. Save it first."))

	user = frappe.get_doc("User", doc.user)
	api_secret = frappe.generate_hash(length=15)
	if not user.api_key:
		user.api_key = frappe.generate_hash(length=15)
	user.api_secret = api_secret
	user.save(ignore_permissions=True)

	return user.api_key, api_secret


@frappe.whitelist()
def issue_pairing_code(agent: str) -> dict:
	"""A short code to type into the agent installer, instead of a key and a secret (`D-212`).

	The technician at the restaurant's computer should not be copying two
	fifteen-character strings between screens. Issuing a new code replaces any
	code outstanding. Only its keyed digest is stored — the code is on the
	screen that asked for it and nowhere else.
	"""
	doc = frappe.get_doc("POS Print Agent", agent)
	doc.check_permission("write")

	if not doc.user:
		frappe.throw(_("This agent has no user yet. Save it first."))

	code = f"{secrets.randbelow(10**PAIRING_DIGITS):0{PAIRING_DIGITS}d}"
	doc.db_set(
		{
			"pairing_code_hash": _digest(code),
			"pairing_expires_at": add_to_date(now_datetime(), minutes=PAIRING_MINUTES),
		},
		update_modified=False,
	)

	return {"code": f"{code[:4]}-{code[4:]}", "minutes": PAIRING_MINUTES, "url": get_url()}


@frappe.whitelist(allow_guest=True)
def pair(code: str, host: str | None = None) -> dict:
	"""Exchange a pairing code for this agent's key and secret — once (`D-212`).

	`allow_guest` because the machine asking has nothing to sign in with yet:
	that is the whole point of the code. So guessing is held to the same
	per-device lockout the till's PIN pad uses (`D-204`), counted apart from it,
	and the code dies on first use or after ten minutes, whichever is sooner.
	"""
	from restaurant_pos.utils.manager_pin import LOCK_SECONDS, attempts_from

	ip = frappe.local.request_ip
	tracker = attempts_from(ip, scope="pair") if ip else None
	if tracker and not tracker.is_user_allowed():
		frappe.throw(
			_("Too many wrong pairing codes from this device. Try again in {0} minutes.").format(
				LOCK_SECONDS // 60
			),
			frappe.RateLimitExceededError,
		)

	# Typed with or without its hyphen, and with whatever a paste carried along.
	digits = "".join(character for character in (code or "") if character.isdigit())
	name = (
		frappe.db.get_value(
			"POS Print Agent",
			{
				"pairing_code_hash": _digest(digits),
				"pairing_expires_at": (">", now_datetime()),
				"is_active": 1,
			},
		)
		if len(digits) == PAIRING_DIGITS
		else None
	)
	if not name:
		if tracker:
			tracker.add_failure_attempt()
		frappe.throw(
			_("That pairing code is not valid, or it has expired. Ask for a new one."),
			frappe.AuthenticationError,
		)

	doc = frappe.get_doc("POS Print Agent", name)
	# Spent before anything else happens, so a second request racing this one
	# finds nothing to match.
	doc.db_set({"pairing_code_hash": None, "pairing_expires_at": None}, update_modified=False)

	# The request has no session, and saving a User — or leaving a comment on the
	# agent — is not Guest's to do. The code is the authorisation; these rights
	# are borrowed for the two writes it authorises and handed straight back.
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		api_key, api_secret = _issue_keys(doc)
		doc.add_comment("Info", _("Paired from {0}.").format(host or ip or _("an unknown machine")))
	finally:
		frappe.set_user(user)

	return {"agent": doc.name, "title": doc.title, "api_key": api_key, "api_secret": api_secret}


def _digest(code: str) -> str:
	"""A keyed digest, so a stolen database alone does not hand over a live code.

	The same construction as the PIN lookup (`manager_pin.lookup_of`), for the
	same reason.
	"""
	from restaurant_pos.utils.manager_pin import lookup_of

	return lookup_of(code)


def for_session() -> str:
	"""The agent the current request is signed in as.

	Every agent endpoint starts here. A print job carries ESC/POS bytes for a
	named printer in a named branch, so "which agent is asking" is not a detail
	of the response — it is the whole authorisation.
	"""
	name = frappe.db.get_value("POS Print Agent", {"user": frappe.session.user, "is_active": 1})
	if not name:
		frappe.throw(_("This user is not an active print agent."), frappe.PermissionError)

	return name
