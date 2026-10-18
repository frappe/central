import os

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

GMAIL_DOMAINS = ("gmail.com", "googlemail.com")
BUNDLED_TEMPORARY_DOMAINS = os.path.join(os.path.dirname(__file__), "temporary_email_domains.txt")
SIGNUP_DOMAINS_KEY = "signup_domains"
GMAIL_ACCOUNTS_KEY = "signup_gmail_accounts"
_temporary_domains: dict[str, tuple[float, frozenset[str]]] = {}


def validate_signup_email(email: str) -> None:
	"""Refuse a new account that is likely abuse, since every new owner gets free credit."""
	domain = get_domain(email)
	if is_blocked_domain(domain) or is_temporary_domain(domain):
		frappe.throw(_("Sign up with a different email address. This email domain is not accepted."))

	if is_alias_email(email):
		frappe.throw(_("Sign up with your own email address. Aliases such as name+tag are not allowed."))


def get_domain(email: str) -> str:
	return email.lower().rpartition("@")[2]


def get_domain_status(domain: str) -> dict | None:
	"""The Signup Domain closest to the domain, so a subdomain entry wins over its parent."""
	entries = get_signup_domains()
	return next((entries[parent] for parent in get_parent_domains(domain) if parent in entries), None)


def get_signup_domains() -> dict[str, dict]:
	"""Every Signup Domain by name, cached until one changes, so a signup reads no table."""
	return frappe.cache.get_value(SIGNUP_DOMAINS_KEY, generator=load_signup_domains)


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

	temporary = get_temporary_domains()
	return any(parent in temporary for parent in get_parent_domains(domain))


def is_alias_email(email: str) -> bool:
	"""Whether the address is a plus alias, or a dotted spelling of a Gmail account that already exists."""
	local, _at, domain = email.lower().rpartition("@")
	if domain in get_alias_domains():
		return False

	if "+" in local:
		return True

	return domain in GMAIL_DOMAINS and has_gmail_account(local)


def get_alias_domains() -> set[str]:
	"""Domains whose addresses may use aliases, from Central Settings."""
	domains = frappe.get_cached_value("Central Settings", "Central Settings", "alias_email_domains") or ""
	return {domain.strip().lower() for domain in domains.replace(",", "\n").splitlines() if domain.strip()}


def get_parent_domains(domain: str) -> list[str]:
	"""The domain and every domain above it, closest first, so cs.example.edu also matches example.edu."""
	parts = domain.split(".")
	return [".".join(parts[index:]) for index in range(len(parts) - 1)]


def get_temporary_domains() -> frozenset[str]:
	"""The site's refreshed list when the weekly job has saved one, else the list shipped with the app.
	It is read again only when the file changes."""
	path = get_temporary_domains_path()
	if not os.path.exists(path):
		path = BUNDLED_TEMPORARY_DOMAINS

	modified = os.path.getmtime(path)
	cached = _temporary_domains.get(path)
	if not cached or cached[0] != modified:
		with open(path) as file:
			domains = frozenset(line.strip() for line in file if line.strip() and not line.startswith("#"))
		cached = _temporary_domains[path] = (modified, domains)
	return cached[1]


def get_temporary_domains_path() -> str:
	return frappe.get_site_path("private", "temporary_email_domains.txt")


def has_gmail_account(local: str) -> bool:
	"""Gmail ignores dots, so a.b@gmail.com and ab@gmail.com reach the same inbox. The known
	accounts sit in a cached set, filled once from the users and kept up as accounts are made."""
	if not frappe.cache.exists(GMAIL_ACCOUNTS_KEY):
		load_gmail_accounts()
	return bool(frappe.cache.sismember(GMAIL_ACCOUNTS_KEY, local.replace(".", "")))


def load_gmail_accounts() -> None:
	user = frappe.qb.DocType("User")
	condition = user.name.like(f"%@{GMAIL_DOMAINS[0]}")
	for domain in GMAIL_DOMAINS[1:]:
		condition |= user.name.like(f"%@{domain}")
	emails = frappe.qb.from_(user).select(user.name).where(condition).run(pluck=True)
	accounts = [email.lower().rpartition("@")[0].replace(".", "") for email in emails]
	for index in range(0, len(accounts), 1000):
		frappe.cache.sadd(GMAIL_ACCOUNTS_KEY, *accounts[index : index + 1000])
	if not accounts:
		frappe.cache.sadd(GMAIL_ACCOUNTS_KEY, "")


def remember_gmail_account(doc, method: str | None = None) -> None:
	"""Add a new Gmail user to the cached set, once the set exists."""
	local, _at, domain = doc.name.lower().rpartition("@")
	if domain in GMAIL_DOMAINS and frappe.cache.exists(GMAIL_ACCOUNTS_KEY):
		frappe.cache.sadd(GMAIL_ACCOUNTS_KEY, local.replace(".", ""))
