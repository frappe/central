from __future__ import annotations

import hashlib

import frappe
from frappe import _
from frappe.utils import getdate
from frappe.utils.password import get_decrypted_password

from central.services import provisioning
from central.services.drivers.base import get_driver
from central.services.permissions import assert_operator, require_service_capability

# Every endpoint is a capability-gated whitelisted method rather than the native
# DocType list/get: team access to services is governed by capability IAM
# (central.iam), not Frappe roles, so team users hold no DocType permission — and the
# read shapes are curated for the console. @require_service_capability resolves the
# team from the call (team | managed_service | key name) and checks the capability.
#
# Per-site enable/disable is NOT here: the bench (Pilot) is authoritative for its
# sites and drives that via central.services.api.pilot. Central owns team activation
# (below), team-level API keys, and the read surfaces.


@frappe.whitelist()
@require_service_capability("service:manage")
def activate_service(team: str, service: str) -> dict:
	"""Activate a team's add-on (idempotent). Needs an active billing subscription in
	the service's plan category, except LLM Hosting: it is prepaid at Grove and has no
	billing plan. LLM registers the team owner as the team's Grove user."""
	add_on = provisioning.get_active_service(service)

	subscription = _resolve_subscription(team, add_on)
	if not subscription and add_on.handler_key != "grove":
		frappe.throw(
			_(
				"{0} is not available in this team's plan. Ask your account administrator to add it, then try again."
			).format(add_on.title)
		)

	existing = frappe.db.get_value(
		"Managed Service", {"team": team, "add_on_service": add_on.name}, ["name", "status"], as_dict=True
	)
	if existing:
		return {"managed_service": existing.name, "status": existing.status}

	doc = frappe.new_doc("Managed Service")
	doc.update(
		{
			"team": team,
			"add_on_service": add_on.name,
			"subscription": subscription,
			"status": "Active",
			"provider_ref": _register_at_provider(add_on, team),
		}
	)
	# Team users hold no DocType permission. The decorator checked the team capability.
	doc.insert(ignore_permissions=True)

	return {"managed_service": doc.name, "status": doc.status}


@frappe.whitelist(methods=["POST"])
@require_service_capability("service:manage")
def generate_api_key(managed_service: str, label: str) -> dict:
	"""Mint a team-level inference key for use in the customer's own apps, for the
	team's Grove user. The secret is returned once here and re-readable later via
	reveal_api_key."""
	service = provisioning.get_managed_service(managed_service)
	if service.status != "Active":
		frappe.throw(_("Managed service is not active."))

	label = (label or "").strip()
	if not label:
		frappe.throw(_("A label is required."))

	add_on = provisioning.get_active_service(service.add_on_service)
	backend = provisioning.get_backend(add_on.name)

	# Provision first, persist second: a provider failure leaves no orphan row. The key is
	# minted for the team's Grove user, so its usage is the team's. No plan options go
	# with it: Grove decides the models. If insert dies after minting, the key's secret
	# is never disclosed, so it's inert.
	email = _grove_user(managed_service)
	result = get_driver(add_on.handler_key).provision_key(backend, label, email, {})

	doc = frappe.new_doc("Service Credential")
	doc.update(
		{
			"subject_type": "Team",
			"managed_service": managed_service,
			"label": label,
			"status": "Active",
			"gateway_url": result["gateway_url"],
			"provider_ref": result.get("provider_ref", email),
			"api_key": result["api_key"],
		}
	)
	# Team users hold no DocType permission. The decorator checked the team capability.
	doc.insert(ignore_permissions=True)

	return {
		"name": doc.name,
		"label": label,
		"gateway_url": result["gateway_url"],
		"api_key": result["api_key"],
		"status": "Active",
	}


@frappe.whitelist(methods=["GET"])
@require_service_capability("service:view")
def list_api_keys(managed_service: str) -> list[dict]:
	"""A managed service's issued API keys, masked (no raw secrets). service:view."""
	rows = frappe.get_all(
		"Service Credential",
		filters={"managed_service": managed_service, "subject_type": "Team"},
		fields=["name", "label", "status", "gateway_url", "creation"],
		order_by="creation desc",
	)
	for row in rows:
		row["masked_key"] = _mask_key(get_decrypted_password("Service Credential", row.name, "api_key"))

	return rows


def _mask_key(key: str) -> str:
	return f"{key[:6]}••••{key[-4:]}" if key and len(key) > 10 else "••••"


@frappe.whitelist(methods=["POST"])
@require_service_capability("service:manage")
def reveal_api_key(name: str) -> dict:
	"""Reveal one issued key's secret + endpoint for copy/curl. service:manage."""
	doc = frappe.get_doc("Service Credential", name)
	if doc.status != "Active":
		frappe.throw(_("This key has been revoked."))

	return {
		"name": doc.name,
		"label": doc.label,
		"gateway_url": doc.gateway_url,
		"api_key": doc.get_password("api_key"),
	}


@frappe.whitelist(methods=["POST"])
@require_service_capability("service:manage")
def revoke_api_key(name: str) -> dict:
	"""Revoke an issued key at the provider and mark it revoked. service:manage."""
	doc = frappe.get_doc("Service Credential", name)
	if doc.status == "Revoked":
		return {"name": name, "status": "Revoked"}

	add_on = provisioning.get_active_service(
		provisioning.get_managed_service(doc.managed_service).add_on_service
	)
	get_driver(add_on.handler_key).revoke_site(
		provisioning.get_backend(add_on.name), doc.get_password("api_key")
	)
	doc.db_set("status", "Revoked")

	return {"name": name, "status": "Revoked"}


@frappe.whitelist(methods=["POST"])
@require_service_capability("service:manage")
def create_bucket(team: str, bucket: str) -> dict:
	"""Create an object-storage bucket for the team and mint its key. service:manage."""
	from central.services.storage import create_bucket as mint

	return mint(team, bucket)


@frappe.whitelist(methods=["POST"])
@require_service_capability("service:manage")
def revoke_bucket_key(name: str) -> dict:
	"""Revoke a bucket's key. The bucket and its objects are untouched. service:manage."""
	from central.services.storage import revoke_bucket

	return revoke_bucket(name)


@frappe.whitelist(methods=["GET"])
@require_service_capability("service:view")
def list_buckets(managed_service: str) -> list[dict]:
	"""The team's object-storage buckets, masked (no raw secrets). service:view."""
	print(managed_service)
	rows = frappe.get_all(
		"Service Credential",
		filters={"managed_service": managed_service, "subject_type": "Team"},
		fields=[
			"name",
			"label",
			"status",
			"gateway_url",
			"provider_ref",
			"service_backend",
			"creation",
		],
		order_by="creation desc",
	)
	for row in rows:
		row["masked_key"] = _mask_key(
			get_decrypted_password("Service Credential", row.name, "api_key", raise_exception=False)
		)
		row["region"] = frappe.db.get_value("Service Backend", row.service_backend, "region")

	return rows


@frappe.whitelist(methods=["POST"])
@require_service_capability("service:manage")
def reveal_bucket_key(name: str) -> dict:
	"""Reveal one bucket's endpoint and both key halves, for an S3 client. service:manage."""
	doc = frappe.get_doc("Service Credential", name)
	if doc.status != "Active":
		frappe.throw(_("This bucket's key has been revoked."))

	return {
		"name": doc.name,
		"bucket": doc.label,
		"endpoint_url": doc.gateway_url,
		"access_key_id": doc.provider_ref,
		"secret_access_key": doc.get_password("api_key"),
	}


@frappe.whitelist(methods=["GET"])
@require_service_capability("service:view")
def list_offers(team: str) -> list[dict]:
	"""Catalogue of active add-on services with the team's status for each. service:view."""
	offers = frappe.get_all(
		"Add-on Service",
		filters={"is_active": 1},
		fields=["name", "title", "plan_category"],
		order_by="title",
	)
	activated = {
		row.add_on_service: row.name
		for row in frappe.get_all(
			"Managed Service", filters={"team": team}, fields=["name", "add_on_service"]
		)
	}
	for offer in offers:
		offer["managed_service"] = activated.get(offer.name)

	return offers


@frappe.whitelist(methods=["GET"])
@require_service_capability("service:view")
def get_instance(managed_service: str) -> dict:
	"""A managed service's status, enabled sites, and the models it may call. service:view.
	`enabled_sites` are the sites Central has minted keys for — its own record, not a
	VM scan (the bench owns the authoritative site list)."""
	instance = provisioning.get_managed_service(managed_service)
	sites = frappe.get_all(
		"Service Credential",
		filters={"subject_type": "Site", "managed_service": managed_service, "status": "Active"},
		fields=["site", "gateway_url"],
		order_by="site",
	)
	clusters = frappe.get_all(
		"Site", filters={"name": ["in", [row.site for row in sites]]}, fields=["name", "cluster"]
	)
	cluster_by_site = {row.name: row.cluster for row in clusters}
	# LLM Hosting has no billing plan. A blank name would match any Subscription.
	plan = (
		frappe.db.get_value("Subscription", instance.subscription, "plan") if instance.subscription else None
	)

	return {
		"managed_service": instance.name,
		"service": instance.add_on_service,
		"status": instance.status,
		"plan": plan,
		"plan_title": frappe.db.get_value("Plan", plan, "title") if plan else None,
		"enabled_sites": [{"site": row.site, "cluster": cluster_by_site.get(row.site)} for row in sites],
		"models": _reachable_models(instance.add_on_service, managed_service),
	}


@frappe.whitelist(methods=["GET"])
@require_service_capability("service:view")
def get_usage(
	managed_service: str,
	period: str = "Last 7 Days",
	api_key: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
) -> dict:
	"""What the team used at Grove over a named period or a `from_date`..`to_date` range (UTC
	days, both included), or through one of its API keys: requests and cost, in total, per
	model, and per day. service:view."""
	instance = provisioning.get_managed_service(managed_service)
	_assert_grove(instance.add_on_service)

	from central.services import llm

	dates = _usage_dates(from_date, to_date) if (from_date or to_date) else None
	key_hash = _team_key_hash(managed_service, api_key) if api_key else None
	return llm.get_usage_report(
		_grove_user(managed_service), period, instance.add_on_service, key_hash, dates
	)


def _usage_dates(from_date: str | None, to_date: str | None) -> tuple[str, str]:
	"""A custom range needs both ends, in order."""
	if not (from_date and to_date):
		frappe.throw(_("A custom range needs a start and an end date."))

	start, end = getdate(from_date), getdate(to_date)
	if start > end:
		frappe.throw(_("The start date is after the end date."))

	return str(start), str(end)


def _team_key_hash(managed_service: str, api_key: str) -> str:
	"""The sha256 Grove knows a team key by, so the secret itself is never sent. Only a key of
	this managed service: another team's key must not reveal its usage."""
	credential = frappe.db.get_value(
		"Service Credential", {"name": api_key, "managed_service": managed_service, "subject_type": "Team"}
	)
	if not credential:
		frappe.throw(_("Unknown API key."), frappe.DoesNotExistError)

	secret = get_decrypted_password("Service Credential", credential, "api_key")
	return hashlib.sha256(secret.encode()).hexdigest()


@frappe.whitelist(methods=["POST"])
def add_credit(managed_service: str, amount: float, reference: str | None = None) -> dict:
	"""Add USD credit to the team's balance at Grove. Operator only: nothing is charged to
	the team for it, and no screen calls it yet. A repeat with the same `reference` adds
	nothing. Returns the balance after it."""
	assert_operator()

	instance = provisioning.get_managed_service(managed_service)
	_assert_grove(instance.add_on_service)

	return get_driver("grove").add_credit(
		provisioning.get_backend(instance.add_on_service), _grove_user(managed_service), amount, reference
	)


def _reachable_models(service: str, managed_service: str) -> list[dict]:
	if frappe.db.get_value("Add-on Service", service, "handler_key", cache=True) != "grove":
		return []

	from central.services import llm

	return llm.get_reachable_models(_grove_user(managed_service), service)


def _grove_user(managed_service: str) -> str | None:
	# The team's Grove user: its owner's email, kept from the time the team activated.
	return frappe.db.get_value("Managed Service", managed_service, "provider_ref")


def _register_at_provider(add_on, team: str) -> str | None:
	# Only the LLM handler has a team-level identity at the provider: the team owner,
	# registered as a Grove user.
	if add_on.handler_key != "grove":
		return None

	from central.services import llm

	return llm.register_grove_user(team, add_on.name)


def _assert_grove(service: str) -> None:
	add_on = provisioning.get_active_service(service)
	if add_on.handler_key != "grove":
		frappe.throw(_("{0} has no usage or credit at a provider.").format(add_on.title))


def _resolve_subscription(team: str, add_on) -> str | None:
	# The team's active subscription whose plan sits in the service's billing family.
	plans = frappe.get_all("Plan", filters={"category": add_on.plan_category}, pluck="name")
	if not plans:
		return None
	return frappe.db.get_value("Subscription", {"team": team, "enabled": 1, "plan": ["in", plans]}, "name")
