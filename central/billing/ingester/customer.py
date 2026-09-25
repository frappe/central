# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Keep a team's customer, address and contact in the accounting system in step
with its Billing Profile.

Runs in the background; saving a profile never waits on it. Each record's id is
kept on the profile as soon as it exists, so a sync that fails half way resumes
where it stopped instead of creating the customer again.
"""

from urllib.parse import quote

import frappe

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


def enqueue_sync(profile) -> None:
	"""Queue a sync for a complete, real profile whose synced details changed."""
	if not _should_sync(profile):
		return
	if profile.profile_id and not any(profile.has_value_changed(f) for f in SYNCED_FIELDS):
		return
	_enqueue(profile.team)


def sync_customer_profile(team: str) -> None:
	"""Create the team's records, or bring them up to date."""
	profile = frappe.get_doc("Billing Profile", team)
	if not _should_sync(profile):
		return
	if profile.profile_id:
		update_customer_profile(profile)
	else:
		create_customer_profile(profile)


def create_customer_profile(profile) -> None:
	customer = post("api/resource/Customer", _customer_payload(profile))
	# Kept before anything else can fail, so a retry updates this customer.
	_keep(profile, "profile_id", customer.name)
	_keep(profile, "address_id", post("api/resource/Address", _address_payload(profile)).name)
	_keep(profile, "contact_id", post("api/resource/Contact", _contact_payload(profile)).name)


def update_customer_profile(profile) -> None:
	put(_resource("Customer", profile.profile_id), _customer_payload(profile))
	if profile.address_id:
		put(_resource("Address", profile.address_id), _address_payload(profile))
	else:
		_keep(profile, "address_id", post("api/resource/Address", _address_payload(profile)).name)
	if profile.contact_id:
		put(_resource("Contact", profile.contact_id), _contact_payload(profile))
	else:
		_keep(profile, "contact_id", post("api/resource/Contact", _contact_payload(profile)).name)


def ensure_customer(team: str) -> str | None:
	"""The team's customer id, syncing the profile first if it has none yet."""
	customer = frappe.db.get_value("Billing Profile", team, "profile_id")
	if not customer and enabled():
		sync_customer_profile(team)
		customer = frappe.db.get_value("Billing Profile", team, "profile_id")
	return customer


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


def _enqueue(team: str) -> None:
	frappe.enqueue(
		"central.billing.ingester.customer.sync_customer_profile",
		queue="short",
		job_id=f"customer-sync::{team}",
		deduplicate=True,
		enqueue_after_commit=True,
		team=team,
	)


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


def _keep(profile, field: str, value: str) -> None:
	"""Store a record id and commit it, so it survives a later step failing."""
	profile.db_set(field, value, update_modified=False)
	if not frappe.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the record exists remotely now


def _resource(doctype: str, name: str) -> str:
	return f"api/resource/{quote(doctype)}/{quote(name, safe='')}"


def _customer_payload(profile) -> dict:
	return {"customer_name": profile.legal_name, "customer_type": "Company", "gstin": profile.gstin}


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
		"gstin": profile.gstin,
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
