from __future__ import annotations

import os
from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

if TYPE_CHECKING:
	from frappe.core.doctype.user.user import User

GMAIL_DOMAINS = ("gmail.com", "googlemail.com")
BUNDLED_TEMPORARY_DOMAINS = os.path.join(os.path.dirname(__file__), "temporary_email_domains.txt")
SIGNUP_DOMAINS_KEY = "signup_domains"
SIGNUP_DOMAINS_SECONDS = 5 * 60
GMAIL_ACCOUNTS_KEY = "signup_gmail_accounts"
TEMPORARY_DOMAINS_KEY = "signup_temporary_domains"


def validate_signup_email(email: str) -> None:
	"""Refuse a new account that is likely abuse, since every new owner gets free credit."""
	domain = get_domain(email)
	# Trusted is how an operator corrects a wrong entry in the public temporary list.
	if is_blocked_domain(domain) or (is_temporary_domain(domain) and not is_trusted_domain(domain)):
		frappe.throw(_("Sign up with a different email address. This email domain is not accepted."))

	if is_alias_email(email):
		throw_alias()


def throw_alias() -> None:
	frappe.throw(_("Sign up with your own email address. Aliases such as name+tag are not allowed."))


def get_domain(email: str) -> str:
	return email.lower().rpartition("@")[2]


def get_domain_status(domain: str) -> dict | None:
	"""The Signup Domain closest to the domain, so a subdomain entry wins over its parent."""
	entries = get_signup_domains()
	return next((entries[parent] for parent in get_parent_domains(domain) if parent in entries), None)


def get_signup_domains() -> dict[str, dict]:
	"""Every Signup Domain by name, cached so a signup reads no table. A change clears the cache, and
	the expiry bounds a stale copy that a signup read before the change committed."""
	entries = frappe.cache.get_value(SIGNUP_DOMAINS_KEY, expires=True)
	if entries is None:
		entries = load_signup_domains()
		frappe.cache.set_value(SIGNUP_DOMAINS_KEY, entries, expires_in_sec=SIGNUP_DOMAINS_SECONDS)
	return entries


def load_signup_domains() -> dict[str, dict]:
	rows = frappe.get_all("Signup Domain", fields=["name", "status", "blocked_until"])
	return {row.name: {"status": row.status, "blocked_until": row.blocked_until} for row in rows}


def clear_signup_domains() -> None:
	frappe.cache.delete_value(SIGNUP_DOMAINS_KEY)


def is_blocked_domain(domain: str) -> bool:
	entry = get_domain_status(domain)
	if not entry or entry["status"] != "Blocked":
		return False
	return not entry["blocked_until"] or get_datetime(entry["blocked_until"]) > now_datetime()


def is_trusted_domain(domain: str) -> bool:
	entry = get_domain_status(domain)
	return bool(entry) and entry["status"] == "Trusted"


def is_temporary_domain(domain: str) -> bool:
	"""Whether the domain belongs to a temporary email provider, when Central Settings refuses them."""
	if not cint(frappe.get_cached_value("Central Settings", "Central Settings", "refuse_temporary_emails")):
		return False

	if not frappe.cache.exists(TEMPORARY_DOMAINS_KEY):
		load_temporary_domains(replace=False)
	return any(frappe.cache.sismember(TEMPORARY_DOMAINS_KEY, parent) for parent in get_parent_domains(domain))


def load_temporary_domains(replace: bool = True) -> None:
	"""Cache the site's refreshed list when the weekly job has saved one, else the list shipped with the app.
	The lock stops a signup that read the old file from swapping it in after a refresh."""
	with frappe.cache.lock(frappe.cache.make_key(f"{TEMPORARY_DOMAINS_KEY}:lock"), timeout=30):
		if not replace and frappe.cache.exists(TEMPORARY_DOMAINS_KEY):
			return

		path = get_temporary_domains_path()
		if not os.path.exists(path):
			path = BUNDLED_TEMPORARY_DOMAINS

		# nosemgrep: frappe-security-file-traversal -- the path is built here, with no user input.
		with open(path) as file:
			domains = [line.strip() for line in file if line.strip() and not line.startswith("#")]
		replace_cached_set(TEMPORARY_DOMAINS_KEY, domains)


def get_temporary_domains_path() -> str:
	return frappe.get_site_path("private", "temporary_email_domains.txt")


def is_alias_email(email: str) -> bool:
	"""Whether the address is a plus alias on a domain that does not allow aliases."""
	local, _at, domain = email.lower().rpartition("@")
	return "+" in local and domain not in get_alias_domains()


def get_alias_domains() -> set[str]:
	"""Domains whose addresses may use aliases, from Central Settings."""
	domains = frappe.get_cached_value("Central Settings", "Central Settings", "alias_email_domains") or ""
	return {domain.strip().lower() for domain in domains.replace(",", "\n").splitlines() if domain.strip()}


def get_parent_domains(domain: str) -> list[str]:
	"""The domain and every domain above it, closest first, so cs.example.edu also matches example.edu."""
	parts = domain.split(".")
	return [".".join(parts[index:]) for index in range(len(parts) - 1)]


def get_gmail_inbox(local: str) -> str:
	"""Gmail ignores dots and everything after a +, so a.b+work@gmail.com reaches ab@gmail.com."""
	return local.lower().partition("+")[0].replace(".", "")


def reserve_gmail_account(email: str) -> None:
	"""Claim a new Gmail account's inbox before the account is made, so two spellings of one inbox
	cannot both pass at once. A request that rolls back gives the inbox up again. This runs only after
	the code is verified: a refusal before it would tell anyone that a Gmail address has an account."""
	local, _at, domain = email.lower().rpartition("@")
	if domain not in GMAIL_DOMAINS or domain in get_alias_domains():
		return

	ensure_gmail_accounts()
	inbox = get_gmail_inbox(local)
	with frappe.cache.lock(frappe.cache.make_key(f"{GMAIL_ACCOUNTS_KEY}:{inbox}:lock"), timeout=10):
		if frappe.cache.sismember(GMAIL_ACCOUNTS_KEY, inbox):
			throw_alias()
		frappe.cache.sadd(GMAIL_ACCOUNTS_KEY, inbox)

	frappe.db.after_rollback.add(lambda: frappe.cache.srem(GMAIL_ACCOUNTS_KEY, inbox))


def ensure_gmail_accounts() -> None:
	if frappe.cache.exists(GMAIL_ACCOUNTS_KEY):
		return

	user = frappe.qb.DocType("User")
	condition = user.name.like(f"%@{GMAIL_DOMAINS[0]}")
	for domain in GMAIL_DOMAINS[1:]:
		condition |= user.name.like(f"%@{domain}")
	emails = frappe.qb.from_(user).select(user.name).where(condition).run(pluck=True)
	replace_cached_set(GMAIL_ACCOUNTS_KEY, [get_gmail_inbox(email.rpartition("@")[0]) for email in emails])


def remember_gmail_account(doc: User, method: str | None = None) -> None:
	"""Add a Gmail user made outside signup, such as from Desk, to the cached set once it exists."""
	local, _at, domain = doc.name.lower().rpartition("@")
	if domain in GMAIL_DOMAINS and frappe.cache.exists(GMAIL_ACCOUNTS_KEY):
		frappe.cache.sadd(GMAIL_ACCOUNTS_KEY, get_gmail_inbox(local))


def replace_cached_set(name: str, members: list[str]) -> None:
	"""Build the set under a new key and swap it in, so no reader sees it half filled. An empty
	member marks a set that is loaded but has nothing in it."""
	building = f"{name}:building:{frappe.generate_hash(length=8)}"
	members = ["", *members]
	for index in range(0, len(members), 1000):
		frappe.cache.sadd(building, *members[index : index + 1000])
	frappe.cache.rename(frappe.cache.make_key(building), frappe.cache.make_key(name))
