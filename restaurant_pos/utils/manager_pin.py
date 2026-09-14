# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A person's PIN — how they approve an override, and how they sign in.

The PIN belongs to a **person**, not a role (`DECISIONS.md` D-016). A role-scoped
PIN is a secret shared by everyone holding the role, so
``POS Audit Log.approved_by`` could never name who actually approved — which is
the entire purpose of recording an override (08_Security.md §5).

**It is now an identity as well as an approval** (`D-094`): a till has no
keyboard and a cashier does not type an email address between customers, so the
PIN is what signs them in. That makes every member of staff a PIN holder rather
than only managers, which is what the lookup index below exists for.

Storage mirrors the correction in D-015: a ``Password`` DocField is persisted
reversibly (``encrypted = 1``) and is invisible to ``check_password()``, which
reads only ``encrypted = 0``. The value is therefore taken off the document
before save and written as a one-way hash.

Refs: 08_Security.md §4, FR-12.2, FR-12.8, D-094
"""

import hashlib
import hmac

import frappe
from frappe import _
from frappe.auth import LoginAttemptTracker
from frappe.utils.password import check_password, update_password

FIELDNAME = "pos_manager_pin"

#: Five digits, matching the length a till user expects to type.
#:
#: Four would do for approving an override, where the manager is already known.
#: As an *identity* the PIN has to be unique across everyone who signs in, and
#: 10,000 values give a roughly one-in-twenty chance of a collision across thirty
#: staff. 100,000 makes that a tenth of it.
PIN_LENGTH = 5

#: Where the fast lookup lives. Never returned by any API, never rendered.
LOOKUP_FIELD = "rpos_pin_lookup"


# --------------------------------------------------------------------------- #
# doc_events on User
# --------------------------------------------------------------------------- #


def hold_pin_aside(doc, method=None):
	"""``User.validate`` — keep the PIN out of reversible storage.

	**Nothing is touched unless a PIN was actually typed** (`D-136`). This used
	to blank the field on every save, and Frappe reads a `Password` field saved
	empty as "delete the stored one" — so *any* edit to a User destroyed their
	PIN. Adding a role to a cashier logged them out of the till, permanently,
	and the pad said only "not recognised" because the refusal is deliberately
	vague (`D-099`). The lookup digest stayed behind, so the account was still
	*found* and then failed to verify.

	Proven, not guessed: a `middle_name` edit and a save took the PIN away.
	"""
	_keep_frappe_off_the_pin(doc)

	pin = (doc.get(FIELDNAME) or "").strip()
	doc._new_manager_pin = None

	if not pin:
		return

	# Only now, and only because it is about to be hashed into `__Auth` by
	# `store_pin_hashed`: what must not persist is the reversible copy.
	doc.set(FIELDNAME, None)

	validate_format(pin)
	assert_pin_is_unique(pin, doc.name)
	doc._new_manager_pin = pin


def _keep_frappe_off_the_pin(doc) -> None:
	"""Stop `BaseDocument._save_passwords` from deleting the PIN (`D-136`).

	It runs on **every** save and reads an empty `Password` field as an
	instruction:

	    new_password = self.get(df.fieldname)
	    if not new_password:
	        remove_encrypted_password(...)

	Our column is always empty — the value lives in `__Auth` as a one-way hash
	written by `_write`, not as Frappe's reversible copy — so every ordinary
	edit to a User silently destroyed that person's PIN. Adding a role to a
	cashier locked them out of the till, and the pad said only "not recognised"
	because the refusal is deliberately vague (`D-099`).

	`ignore_save_passwords` is Frappe's own way of saying *this field is not
	yours*. Appended rather than assigned: another app may have named its own
	fields, and taking the list from it would move the bug rather than fix it.
	"""
	current = doc.flags.ignore_save_passwords

	if current is True:
		return

	doc.flags.ignore_save_passwords = (
		[*current, FIELDNAME] if isinstance(current, list | tuple | set) else [FIELDNAME]
	)


def store_pin_hashed(doc, method=None):
	"""``User.on_update`` — write the one-way hash and the lookup digest."""
	pin = getattr(doc, "_new_manager_pin", None)
	if not pin:
		return

	_write(doc.name, pin)
	doc._new_manager_pin = None


def _write(user: str, pin: str) -> None:
	"""The only place a PIN is stored, so the two halves cannot drift apart.

	The digest without the hash would admit somebody the verify then rejects;
	the hash without the digest is a PIN that silently stops signing in. Written
	together, in one function, for the same reason the shift gate lives in one
	place (`CLAUDE.md` §5.5).
	"""
	update_password(user, pin, doctype="User", fieldname=FIELDNAME)
	frappe.db.set_value("User", user, LOOKUP_FIELD, lookup_of(pin), update_modified=False)


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #


def validate_format(pin: str) -> None:
	if not pin.isdigit() or len(pin) != PIN_LENGTH:
		frappe.throw(_("The PIN must be exactly {0} digits.").format(PIN_LENGTH))


def assert_pin_is_unique(pin: str, user: str | None = None) -> None:
	"""Reject a PIN already used by someone else.

	Two people sharing a PIN was always an accountability failure — the audit
	trail would name whichever row was read first. Now that the PIN also signs
	people in it is worse than that: the second person would sign in **as the
	first**, and every order they took would be recorded against somebody who
	was not there (`D-094`).

	Goes through `find_user_by_pin` rather than the index alone, so a PIN issued
	before the index existed still counts as taken. Checking the index only
	would let a second person be given a colliding PIN, and collisions are the
	one thing this function exists to stop.
	"""
	owner = find_user_by_pin(pin)
	if owner and owner != user:
		frappe.throw(_("That PIN is already in use. Choose a different one."))


def set_pin(user: str, pin: str) -> None:
	"""Set or replace a user's PIN. Write-only; the value is never read back."""
	validate_format(pin)
	assert_pin_is_unique(pin, user)
	_write(user, pin)


def clear_pin(user: str) -> None:
	auth = frappe.qb.Table("__Auth")
	frappe.qb.from_(auth).delete().where(
		(auth.doctype == "User") & (auth.name == user) & (auth.fieldname == FIELDNAME)
	).run()

	# Or the digest would still find a user whose PIN no longer verifies — a
	# sign-in that fails for a reason nobody can see.
	frappe.db.set_value("User", user, LOOKUP_FIELD, None, update_modified=False)


def has_pin(user: str) -> bool:
	"""Whether ``user`` has a PIN, without reading it (FR-12.8)."""
	return user in pin_holders()


def pin_holders() -> list[str]:
	"""Users with a PIN set. Read through the query builder because ``__Auth``
	is not a DocType, the same way Frappe's own password utilities read it."""
	auth = frappe.qb.Table("__Auth")
	rows = (
		frappe.qb.from_(auth)
		.select(auth.name)
		.where((auth.doctype == "User") & (auth.fieldname == FIELDNAME) & (auth.encrypted == 0))
		.run()
	)
	return [row[0] for row in rows]


def lookup_of(pin: str) -> str:
	"""A keyed digest of the PIN, for finding its owner in one query (`D-094`).

	**Measured, not assumed.** The password hash is deliberately slow — 44 ms a
	try on this machine — and the previous lookup tried every PIN holder in
	turn. With managers only that was a handful; once the PIN signs people in,
	every member of staff holds one, and a *wrong* PIN pays the full price
	because it matches nobody. Twenty staff came to ~900 ms per mistyped digit
	sequence, at a counter, with a queue.

	Keyed with the site's encryption key, so a stolen database alone cannot be
	brute-forced against it. That is the honest limit of it: five digits is
	100,000 guesses, and anyone holding both the database and the site key
	breaks this in a moment — as they would the slow hash in an afternoon. A
	till PIN is a convenience credential, and the defence that matters is the
	lockout in `identify`, not the digest.
	"""
	key = (frappe.local.conf.get("encryption_key") or frappe.local.site).encode()
	return hmac.new(key, pin.encode(), hashlib.sha256).hexdigest()


def find_user_by_pin(pin: str) -> str | None:
	"""Return the user whose PIN matches, or ``None``.

	One indexed read, then one slow verify. The digest finds the candidate and
	`check_password` is still what decides — so a digest collision, or a stale
	index left by a half-finished write, cannot let anybody in.
	"""
	user = frappe.db.get_value("User", {LOOKUP_FIELD: lookup_of(pin)}, "name")
	if user:
		try:
			check_password(user, pin, doctype="User", fieldname=FIELDNAME)
		except Exception:
			return None
		return user

	return _find_and_index_legacy(pin)


def _find_and_index_legacy(pin: str) -> str | None:
	"""The old scan, for PINs set before the index existed — once each.

	The hash is one way, so the digest cannot be computed for an existing PIN
	from the database: a migration would have had to **delete everyone's PIN**
	and ask a restaurant to reissue them. Instead the first sign-in with an old
	PIN pays the old cost, and writes the digest on its way through. The set of
	users this touches only ever shrinks, and it is empty on a new site.
	"""
	stale = [user for user in pin_holders() if not frappe.db.get_value("User", user, LOOKUP_FIELD)]

	for user in stale:
		try:
			check_password(user, pin, doctype="User", fieldname=FIELDNAME)
		except Exception:
			continue

		frappe.db.set_value("User", user, LOOKUP_FIELD, lookup_of(pin), update_modified=False)
		return user

	return None


#: Wrong PINs one device may type before it has to wait (`D-204`).
#:
#: Counted per address across sign-in and both overrides, and **not** cleared by
#: a right PIN: a cashier who knows their own would otherwise sign in between
#: guesses and never be stopped. Five every five minutes makes a sweep of all
#: 100,000 PINs about ten weeks, with every guess in the audit log.
WRONG_PINS_ALLOWED = 5
LOCK_SECONDS = 5 * 60


def attempts_from(ip: str, scope: str = "pin") -> LoginAttemptTracker:
	"""Frappe's own failed-login counter, kept per device rather than per account.

	``scope`` keeps one kind of guess from spending another's allowance: a print
	agent's pairing code (`D-212`) counts apart from the till's PINs.
	"""
	# Frappe locks when the count *exceeds* its maximum, hence the minus one.
	return LoginAttemptTracker(
		f"rpos_{scope}:{ip}",
		max_consecutive_login_attempts=WRONG_PINS_ALLOWED - 1,
		lock_interval=LOCK_SECONDS,
	)


def identify(pin: str) -> str | None:
	"""`find_user_by_pin` for a person at a pad — the door every guess comes through.

	Sign-in and both manager overrides pass here, so the count lives in one place
	(`CLAUDE.md` §5.5). `assert_pin_is_unique` does not: a new PIN matching
	nobody is the answer it hopes for, not a wrong guess.

	The limit before this was Frappe's `rate_limit(key="pin")` on `sign_in`,
	which keys on the address **and the value typed** — so every new guess
	started a fresh count and nothing was ever limited. The overrides had no
	limit at all.

	Only a real request is counted: a console or a background job types no
	guess, and a test suite sharing one count would lock itself out.
	"""
	ip = frappe.local.request_ip
	tracker = attempts_from(ip) if ip else None
	if tracker and not tracker.is_user_allowed():
		frappe.throw(
			_("Too many wrong PINs on this device. Try again in {0} minutes.").format(LOCK_SECONDS // 60),
			frappe.RateLimitExceededError,
		)

	user = find_user_by_pin(pin) if (pin or "").isdigit() else None
	if tracker and not user:
		tracker.add_failure_attempt()
	return user


def find_approver_for_pin(action: str, pin: str) -> str | None:
	"""Return the user whose PIN matches **and** who holds ``action``.

	A valid PIN is not a master key. Returns ``None`` on any failure with no
	detail about which part failed, so a caller cannot probe for valid PINs.
	"""
	from restaurant_pos.utils.permissions import get_pos_permission_set

	user = identify(pin)
	if not user:
		return None

	if not frappe.db.get_value("User", user, "enabled"):
		return None

	return user if get_pos_permission_set(user).get(action) else None
