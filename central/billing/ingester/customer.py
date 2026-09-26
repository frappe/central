# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Keep a team's customer, address and contact in the accounting system in step
with its Billing Profile.

A sync is a chain of background jobs, one step each. Creating a record is a step,
so its id commits at the end of that job, and a failed step resumes from the last
id instead of creating the customer again.
"""

from urllib.parse import quote

import frappe
from redis.exceptions import LockError

from central.billing.ingester.connection import enabled, get, post, put

# Changes to these are what the accounting system needs to hear about.
SYNCED_FIELDS = (
	"legal_name",
	"email",
	"phone",
	"gstin",
	"address_line1",
	"address_line2",
	"city",
	"state",
	"country",
	"pincode",
)

PENDING_BATCH = 100

# Longest one step may hold its team's lock: a request at its timeout, and room.
LOCK_SECONDS = 5 * 60


def enqueue_sync(profile) -> None:
	"""Queue a sync for a complete, real profile whose synced details changed."""
	if not _should_sync(profile):
		return
	if profile.profile_id and not any(profile.has_value_changed(f) for f in SYNCED_FIELDS):
		return
	_enqueue(profile.team)


def sync_customer_profile(team: str) -> None:
	"""Background job: take the team's next sync step, then queue the one after.

	The team's lock is taken before anything is read and held until this job's
	transaction ends, so the next sync to get it sees every id this one wrote.
	"""
	if not _lock_until_transaction_ends(team):
		return  # another step for this team is running and queues what follows
	profile = frappe.get_doc("Billing Profile", team)
	if not _should_sync(profile):
		return
	if not profile.profile_id:
		_create(profile, "profile_id", "Customer", _customer_payload)
	elif not profile.address_id:
		_create(profile, "address_id", "Address", _address_payload)
	elif not profile.contact_id:
		_create(profile, "contact_id", "Contact", _contact_payload)
	else:
		update_customer_profile(profile)
		_release_held_drafts(team)
		return
	# A last update pass also catches profile edits made while the records were created.
	_enqueue(team, job_id=f"customer-sync::{team}::next")


def update_customer_profile(profile) -> None:
	"""Bring all three records up to date. Safe to repeat."""
	put(_resource("Customer", profile.profile_id), _customer_payload(profile))
	put(_resource("Address", profile.address_id), _address_payload(profile))
	put(_resource("Contact", profile.contact_id), _contact_payload(profile))


def ensure_customer(team: str) -> str | None:
	"""The team's customer id. Without one, queue the sync and return None."""
	customer = frappe.db.get_value("Billing Profile", team, "profile_id")
	if not customer:
		enqueue_for(team)
	return customer


def awaiting_records(team: str) -> bool:
	"""Whether the team's records should exist but don't yet. Queues their sync if so."""
	if not frappe.db.exists("Billing Profile", team):
		return False
	profile = frappe.get_doc("Billing Profile", team)
	if not _should_sync(profile) or (profile.profile_id and profile.address_id and profile.contact_id):
		return False
	_enqueue(team)
	return True


def enqueue_for(team: str) -> None:
	"""Queue a sync for this team if its profile is one we sync."""
	if frappe.db.exists("Billing Profile", team) and _should_sync(frappe.get_doc("Billing Profile", team)):
		_enqueue(team)


def sync_pending_profiles() -> None:
	"""Daily: retry profiles whose sync never finished."""
	if not enabled():
		return
	for team in _pending_teams():
		_enqueue(team)


def get_gstin_details(gstin: str) -> frappe._dict | None:
	return get(
		"api/method/india_compliance.gst_india.utils.gstin_info.get_gstin_info",
		params={"gstin": gstin},
	)


def _should_sync(profile) -> bool:
	"""Only complete profiles of real customers; staging trials carry placeholders."""
	from central.billing.api.dashboard._shared import missing_profile_fields_in

	if not enabled() or missing_profile_fields_in(profile):
		return False
	return not frappe.db.get_value("Team", profile.team, "is_staging_trial")


def _enqueue(team: str, job_id: str | None = None) -> None:
	frappe.enqueue(
		"central.billing.ingester.customer.sync_customer_profile",
		queue="short",
		job_id=job_id or f"customer-sync::{team}",
		deduplicate=True,
		enqueue_after_commit=True,
		team=team,
	)


def _release_held_drafts(team: str) -> None:
	from central.billing.revenue.invoicing.run import release_held_drafts

	release_held_drafts(team)


def _lock_name(team: str) -> str:
	return frappe.cache.make_key(f"customer-sync::{team}")


def _lock_until_transaction_ends(team: str) -> bool:
	"""Take the team's sync lock, released once this transaction commits or rolls back.

	The timeout frees it if the worker dies first.
	"""
	lock = frappe.cache.lock(_lock_name(team), timeout=LOCK_SECONDS)
	if not lock.acquire(blocking=False):
		return False

	def release():
		try:
			lock.release()
		except LockError:
			pass  # it outlived its timeout; nothing left to release

	frappe.db.after_commit.add(release)
	frappe.db.after_rollback.add(release)
	return True


def _pending_teams() -> list[str]:
	"""Complete profiles of real teams that are missing a record id."""
	from central.billing.api.dashboard._shared import _REQUIRED_PROFILE_FIELDS

	profile = frappe.qb.DocType("Billing Profile")
	team = frappe.qb.DocType("Team")
	query = (
		frappe.qb.from_(profile)
		.join(team)
		.on(team.name == profile.team)
		.select(profile.name)
		.where(team.is_staging_trial == 0)
		.where(_blank(profile.profile_id) | _blank(profile.address_id) | _blank(profile.contact_id))
	)
	for field in _REQUIRED_PROFILE_FIELDS:
		query = query.where(~_blank(profile[field]))
	return query.orderby(profile.modified).limit(PENDING_BATCH).run(pluck=True)


def _blank(column):
	return column.isnull() | (column == "")


def _create(profile, field: str, doctype: str, payload) -> None:
	record = post(f"api/resource/{doctype}", payload(profile))
	profile.db_set(field, record.name, update_modified=False)


def _resource(doctype: str, name: str) -> str:
	return f"api/resource/{quote(doctype)}/{quote(name, safe='')}"


def _gstin(profile) -> str:
	"""The GSTIN our own invoices carry: blank while the GST portal calls it lapsed."""
	from central.billing.revenue import gst_status

	return gst_status.standing(profile.team).gstin or ""


def _customer_payload(profile) -> dict:
	return {"customer_name": profile.legal_name, "customer_type": "Company", "gstin": _gstin(profile)}


def _address_payload(profile) -> dict:
	return {
		"address_title": profile.legal_name,
		"address_type": "Billing",
		"address_line1": profile.address_line1,
		"address_line2": profile.address_line2,
		"city": profile.city,
		"state": profile.state,
		"pincode": profile.pincode,
		"country": profile.country,
		"gstin": _gstin(profile),
		"is_primary_address": 1,
		"is_shipping_address": 1,
		"links": [{"link_doctype": "Customer", "link_name": profile.profile_id}],
	}


def _contact_payload(profile) -> dict:
	owner = profile.team_owner or frappe.db.get_value("Team", profile.team, "owner_user")
	names = (
		frappe.db.get_value("User", owner, ["first_name", "last_name"], as_dict=True) if owner else None
	) or frappe._dict()
	emails = [e for e in dict.fromkeys([owner, profile.email]) if e]
	return {
		"first_name": names.first_name or profile.legal_name,
		"last_name": names.last_name,
		"is_primary_contact": 1,
		"email_ids": [{"email_id": e, "is_primary": int(i == 0)} for i, e in enumerate(emails)],
		"phone_nos": [{"phone": profile.phone, "is_primary_phone": 1}] if profile.phone else [],
		"links": [{"link_doctype": "Customer", "link_name": profile.profile_id}],
	}
