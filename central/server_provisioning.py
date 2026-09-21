from __future__ import annotations

import hashlib
import json
import math
import re

import frappe
from cryptography.hazmat.primitives.serialization import load_ssh_public_key
from frappe import _
from frappe.query_builder.functions import Sum
from pydantic import ValidationError

from central.billing.api.dashboard._shared import _team_currency
from central.billing.api.dashboard.catalog import get_eligible_plans
from central.billing.catalog.composition import (
	COMPUTE,
	DISK,
	MEMORY,
	composition_quantities,
	validate_composition,
)
from central.billing.catalog.pricing import resolve_config_rate
from central.iam import can
from central.integrations.images import selected_image
from central.server_models import CreateServerInput, ServerCreation

PENDING_STATES = ("Queued", "Dispatching", "Sent", "In Progress", "Uncertain")


def submit_request(
	*,
	team: str,
	region: str,
	title: str,
	offering: str,
	image_id: str,
	request_key: str,
	plan: str | None = None,
	includes: list[dict] | None = None,
	sub_category: str | None = None,
	hostname: str | None = None,
	ssh_keys: list[str] | None = None,
	resource_type: str = "Server",
	subdomain: str | None = None,
) -> dict:
	"""Authorize and persist intent before any remote mutation.

	`resource_type` says what the customer asked for, which decides how the request is
	driven: a server is queued, a site is sent in the request its customer is waiting on."""
	try:
		input = CreateServerInput.model_validate(
			dict(
				team=team,
				region=region,
				title=title,
				offering=offering,
				image_id=image_id,
				request_key=request_key,
				plan=plan,
				includes=includes or [],
				sub_category=sub_category,
				hostname=hostname or "",
				ssh_keys=ssh_keys or [],
			)
		)
	except ValidationError as error:
		frappe.throw(
			_("Invalid server configuration: {0}").format(
				"; ".join(
					".".join(map(str, item["loc"])) + ": " + item["msg"]
					for item in error.errors(include_input=False)
				)
			)
		)

	if not can(frappe.session.user, input.team, "server:create"):
		frappe.throw(_("You cannot create servers for this Team."), frappe.PermissionError)

	values = input.model_dump()
	team, region, offering, image_id = input.team, input.region, input.offering, input.image_id
	request_key, plan, sub_category = input.request_key, input.plan, input.sub_category
	includes = [row.model_dump() for row in input.includes]
	if bool(input.plan) == bool(input.includes):
		frappe.throw(_("Choose either a plan or a custom configuration."))
	if input.includes and len({row.resource_type for row in input.includes}) != len(input.includes):
		frappe.throw(_("Each resource type must occur once."))

	settings = {
		**{key: value for key, value in values.items() if key != "request_key"},
		"resource_type": resource_type,
		"subdomain": subdomain,
	}
	digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
	# Serialize budget reservations and repeated submissions within one Team.
	frappe.db.get_value("Team", team, "name", for_update=True)
	existing = frappe.db.get_value(
		"Resource Action", {"team": team, "request_key": request_key}, for_update=True
	)
	if existing:
		request = frappe.get_doc("Resource Action", existing)
		if request.request_digest != digest:
			frappe.throw(_("This request key was already used for different server settings."))
		return request.customer_status()

	unanswered = unanswered_request(team, digest)
	if unanswered:
		return frappe.get_doc("Resource Action", unanswered).customer_status()

	image = selected_image(team, region, offering, image_id, "server:create")
	composition, rate = validate_purchase(team, region, plan, includes, sub_category)
	shape = image_shape(composition, image)
	validate_guest_input(values, image)

	configuration = ServerCreation.model_validate(
		{
			**{
				key: values[key]
				for key in (
					"offering",
					"image_id",
					"plan",
					"sub_category",
					"hostname",
					"ssh_keys",
				)
			},
			"currency": _team_currency(team),
			"billing_cycle": frappe.db.get_value("Plan", plan, "billing_cycle") if plan else "Monthly",
			"includes": composition,
			"image_tags": image["tags"],
			**shape,
		}
	)
	request = frappe.get_doc(
		{
			"doctype": "Resource Action",
			"resource_type": resource_type,
			"subdomain": subdomain,
			"action": "create",
			"team": input.team,
			"atlas_instance": input.region,
			"title": input.title,
			"request_payload": configuration.model_dump(),
			"correlation_id": frappe.generate_hash(length=32),
			"request_key": input.request_key,
			"request_digest": digest,
			"reserved_monthly_rate": rate,
			"requested_by": frappe.session.user,
			"status": "Queued",
		}
	)
	# Only this authorized service accepts customer intent; customers cannot write outcomes.
	request.insert(ignore_permissions=True)
	return request.customer_status()


def unanswered_request(team: str, digest: str) -> str | None:
	"""The creation this requester already sent with these settings, that no region has
	answered yet.

	Central saves a request before it calls a region, so a lost reply leaves the record
	behind while the browser keeps nothing. Answering the repeat with that record is what
	stops one click, or one click and a reload, from building two servers. A request that
	already holds a VM identity has been answered and never matches, so a deliberate
	second server is still a second record."""
	return frappe.db.get_value(
		"Resource Action",
		{
			"team": team,
			"action": "create",
			"requested_by": frappe.session.user,
			"request_digest": digest,
			"status": ["in", PENDING_STATES],
			"remote_vm_id": ["is", "not set"],
		},
	)


def validate_purchase(
	team: str, region: str, plan: str | None, includes: list[dict] | None, sub_category: str | None
) -> tuple[list[dict], float]:
	trial = bool(frappe.db.get_value("Team", team, "is_staging_trial"))
	if trial:
		validate_trial(team)
	else:
		from central.billing.api.dashboard._shared import require_billing_profile

		require_billing_profile(team, "create servers")

	catalog = get_eligible_plans(cluster=region, team=team)
	if plan:
		choices = [row for rows in catalog["plans"].values() for row in rows]
		selected = next((row for row in choices if row["plan"] == plan), None)
		if not selected:
			frappe.throw(_("This plan is not available for the selected Team and region."))
		composition, rate = selected["includes"], selected["rate"]
	else:
		if (
			trial
			or not catalog["rate_card"]
			or not any(p["sub_category"] == sub_category for p in catalog["profiles"])
		):
			frappe.throw(_("A custom configuration is not available for this Team and region."))
		validate_composition(sub_category, includes)
		composition = includes
		rate = float(resolve_config_rate(includes, catalog["currency"], region))

	if not trial and rate + reserved_rate(team) > catalog["available"]:
		frappe.throw(_("Pending server requests and this plan exceed your spending limit."))
	return composition, float(rate)


def reserved_rate(team: str) -> float:
	request = frappe.qb.DocType("Resource Action")
	rows = (
		frappe.qb.from_(request)
		.select(Sum(request.reserved_monthly_rate))
		.where(
			(request.team == team)
			& request.status.isin(PENDING_STATES)
			& (request.server.isnull() | (request.server == ""))
		)
	).run()
	return float(rows[0][0] or 0)


def validate_trial(team: str) -> None:
	from central.billing.revenue.credits import get_balance

	if get_balance(team).get("balance", 0) <= 0:
		frappe.throw(_("Your trial credits are used up. Add a payment method to continue."))
	servers = frappe.db.count("Virtual Machine", {"team": team, "status": ["!=", "Terminated"]})
	pending = frappe.db.count(
		"Resource Action",
		{"team": team, "status": ["in", PENDING_STATES], "server": ["is", "not set"]},
	)
	if servers + pending >= 3:
		frappe.throw(_("Trial Teams can have at most three active or pending servers."))


def image_shape(includes: list[dict], image: dict) -> dict[str, int]:
	quantities = composition_quantities(includes)
	values = (quantities.get(COMPUTE, 0), quantities.get(MEMORY, 0) * 1024, quantities.get(DISK, 0) * 1024)
	if any(not math.isfinite(value) or value <= 0 or int(value) != value for value in values):
		frappe.throw(_("Choose whole virtual CPUs and positive memory and disk sizes in MiB."))
	shape = dict(zip(("virtual_cpu_count", "memory_mib", "disk_mib"), map(int, values), strict=True))
	if shape["disk_mib"] < image["rootfs_size_mib"]:
		frappe.throw(_("This plan's disk is smaller than the selected image."))
	return shape


def validate_guest_input(values: dict, image: dict) -> None:
	if not values["title"] or len(values["title"]) > 140:
		frappe.throw(_("Enter a server name of at most 140 characters."))
	if values["hostname"] and not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", values["hostname"]):
		frappe.throw(_("Use a valid lowercase guest hostname."))
	if image["tags"].get("purpose") != "pilot" and not values["ssh_keys"]:
		frappe.throw(_("Add an SSH public key for this server."))
	for key in values["ssh_keys"]:
		try:
			load_ssh_public_key(key.strip().encode())
		except ValueError, TypeError:
			frappe.throw(_("Enter a valid OpenSSH public key on each line."))
