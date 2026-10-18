import os

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

from central.identity.signup_email import get_domain, get_temporary_domains_path, is_trusted_domain

TEMPORARY_DOMAINS_URL = (
	"https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/main/"
	"disposable_email_blocklist.conf"
)
# Big public providers serve many real people, so one of them is never blocked as a whole.
PUBLIC_MAIL_DOMAINS = frozenset(
	(
		"gmail.com",
		"googlemail.com",
		"outlook.com",
		"hotmail.com",
		"live.com",
		"msn.com",
		"yahoo.com",
		"ymail.com",
		"icloud.com",
		"me.com",
		"mac.com",
		"aol.com",
		"proton.me",
		"protonmail.com",
		"zoho.com",
		"zohomail.in",
		"gmx.com",
		"gmx.net",
		"mail.com",
		"yandex.com",
		"yandex.ru",
		"rediffmail.com",
		"qq.com",
		"163.com",
		"126.com",
	)
)
SECOND_LEVEL_LABELS = frozenset(("ac", "co", "com", "edu", "gov", "net", "org", "res", "nic"))


def watch_signup_ip() -> None:
	"""Count a new-account request from the caller's IP, and block an IP that floods signups."""
	ip = frappe.local.request_ip
	if not ip:
		return

	if frappe.cache.exists(get_ip_block_key(ip)):
		refuse()

	limit = get_setting("signup_requests_per_minute")
	if limit and increment(f"ip:{ip}:{now_datetime():%Y%m%d%H%M}") > limit:
		frappe.cache.set_value(get_ip_block_key(ip), 1, expires_in_sec=get_block_hours() * 60 * 60)
		refuse()


def watch_signup_domain(email: str) -> None:
	"""Count a new-account request from the email's organisation, and block one that floods signups.
	A public provider is never blocked as a whole."""
	limit = get_setting("signup_requests_per_minute")
	domain = get_domain(email)
	if not limit or domain in PUBLIC_MAIL_DOMAINS or is_trusted_domain(domain):
		return

	organisation = get_organisation_domain(domain)
	if increment(f"domain:{organisation}:{now_datetime():%Y%m%d%H%M}") > limit:
		block_automatically(organisation, _("More than {0} signup requests in one minute.").format(limit))
		refuse()


def refuse() -> None:
	frappe.throw(_("Too many signups. Try again later."), frappe.TooManyRequestsError)


def get_ip_block_key(ip: str) -> str:
	return f"signup-blocked-ip:{ip}"


def block_automatically(organisation: str, reason: str) -> None:
	"""Record the block in its own job: the refused request rolls back, but the block must stay."""
	frappe.enqueue(
		save_automatic_block,
		domain=organisation,
		reason=reason,
		queue="short",
		job_id=f"signup-block:{organisation}",
		deduplicate=True,
	)


def save_automatic_block(domain: str, reason: str) -> None:
	"""Background job: block the domain for the configured hours and tell the operators."""
	blocked_until = add_to_date(now_datetime(), hours=get_block_hours())
	if frappe.db.exists("Signup Domain", domain):
		entry = frappe.get_doc("Signup Domain", domain)
		if entry.status == "Trusted" or entry.is_blocking():
			return
		entry.update({"source": "Automatic", "blocked_until": blocked_until, "reason": reason})
	else:
		entry = frappe.get_doc(
			{
				"doctype": "Signup Domain",
				"domain": domain,
				"status": "Blocked",
				"source": "Automatic",
				"blocked_until": blocked_until,
				"reason": reason,
			}
		)
	# The job runs for no user; the block is the system's own decision.
	entry.save(ignore_permissions=True)
	notify_operators(entry)


def notify_operators(entry) -> None:
	from central.billing.platform.alerts import operators

	recipients = operators()
	if not recipients:
		return

	frappe.sendmail(
		recipients=recipients,
		subject=_("New signups from {0} are blocked").format(entry.domain),
		message=_(
			"Central blocked new accounts from {0} until {1}. Reason: {2} If these are real users, "
			"open Signup Domain {0} and set its status to Trusted."
		).format(frappe.utils.escape_html(entry.domain), entry.blocked_until, entry.reason),
		delayed=True,
	)


def get_organisation_domain(domain: str) -> str:
	"""The domain an organisation registered, so cs.uni.edu and ee.uni.edu count together.
	Names such as uni.ac.in keep three labels."""
	labels = domain.split(".")
	keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL_LABELS else 2
	return ".".join(labels[-keep:])


def refresh_temporary_domains() -> None:
	"""Weekly: save the latest list of temporary email providers for this site. A list that looks
	wrong is not saved, and signups keep the last good one."""
	response = requests.get(TEMPORARY_DOMAINS_URL, timeout=30)
	response.raise_for_status()
	domains = {
		line.strip().lower()
		for line in response.text.splitlines()
		if line.strip() and not line.startswith("#")
	}
	if len(domains) < 1000 or domains & PUBLIC_MAIL_DOMAINS:
		frappe.log_error(title="Temporary email list looks wrong", message=f"{len(domains)} domains")
		return

	path = get_temporary_domains_path()
	with open(f"{path}.tmp", "w") as file:
		file.write("\n".join(sorted(domains)) + "\n")
	os.replace(f"{path}.tmp", path)


def increment(name: str) -> int:
	key = frappe.cache.make_key(f"signup-watch:{name}")
	count = frappe.cache.incr(key)
	if count == 1:
		frappe.cache.expire(key, 2 * 60)
	return count


def get_block_hours() -> int:
	return get_setting("automatic_block_hours") or 24


def get_setting(fieldname: str) -> int:
	return cint(frappe.get_cached_value("Central Settings", "Central Settings", fieldname))
