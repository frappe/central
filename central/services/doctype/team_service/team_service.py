# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from central.billing.catalog.subscriptions import end_subscription, provision_service_subscription
from central.integrations.object_storage import ObjectStorageClient, ObjectStorageNotFound
from central.services.doctype.service.service import AI_SERVICE, STORAGE_SERVICE
from central.services.doctype.service_detail.service_detail import ServiceDetail


class TeamService(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		access_key: DF.Data | None
		add_on_service: DF.Literal["storage", "ai"]
		bucket_name: DF.Data | None
		endpoint_url: DF.Data | None
		external_id: DF.Data | None
		region: DF.Link | None
		secret_access_key: DF.Password | None
		status: DF.Literal["Active", "Suspended"]
		subscription: DF.Link | None
		team: DF.Link
	# end: auto-generated types

	@property
	def is_bucket(self) -> bool:
		return self.add_on_service == STORAGE_SERVICE

	@property
	def is_ai(self) -> bool:
		return self.add_on_service == AI_SERVICE

	def before_insert(self) -> None:
		"""Create the bucket, bill it, then let the record save. Cargo answers first, so a
		record always names a bucket that exists. AI registers the team at Grove first; its keys
		each call their own geography's gateway, so an AI row has no endpoint."""
		if self.is_ai:
			from central.services.ai import register_team

			self.validate_one_ai_service()
			register_team(self.team)
			self.subscribe_ai()
			return

		if not self.is_bucket:
			return

		if not self.bucket_name:
			frappe.throw(_("A bucket needs a name."))
		self.validate_bucket_region()
		self.validate_bucket_is_unclaimed()

		# Read everything that can refuse first, so a refusal leaves no bucket in Cargo.
		plan = get_storage_plan()
		endpoint_url = get_storage_endpoint_url(self.region)
		client = ObjectStorageClient.from_region(self.region)

		# Cargo mints a bucket's key once, and only a rotation issues another. A name it
		# already holds is refused rather than taken over, so no live key is revoked.
		receipt = client.create_bucket(self.bucket_name)
		self.set_credentials(receipt["credentials"])

		subscription = provision_service_subscription(
			self.team, plan, cluster=self.region, changed_by=self.flags.requested_by or frappe.session.user
		)
		self.update(
			{"status": "Active", "subscription": subscription["subscription"], "endpoint_url": endpoint_url}
		)

	def on_trash(self) -> None:
		"""Delete the bucket with its record. Cargo refuses a bucket that still holds objects."""
		if not self.is_bucket:
			return

		try:
			ObjectStorageClient.from_region(self.region).delete_bucket(self.bucket_name)
		except ObjectStorageNotFound:
			pass

		self.release_subscription()

	def release_subscription(self) -> None:
		"""End the storage subscription with the last bucket on it. One subscription bills
		every bucket the team holds in a region."""
		if not self.subscription:
			return

		others = {"subscription": self.subscription, "name": ("!=", self.name)}
		if not frappe.db.exists(self.doctype, others):
			end_subscription(self.subscription)

	def get_usage(self) -> dict:
		"""What the bucket holds, against its caps, as Cargo counts it."""
		return ObjectStorageClient.from_region(self.region).get_usage(self.bucket_name)["usage"]

	def set_quota(self, size_gib: int, max_objects: int) -> None:
		"""Cap the bucket in Cargo, which owns and enforces the quota. Zero lifts a cap."""
		ObjectStorageClient.from_region(self.region).set_quota(self.bucket_name, size_gib, max_objects)

	def get_allowed_origins(self) -> list[str]:
		"""The websites that may call the bucket from a browser. Cargo owns the list."""
		receipt = ObjectStorageClient.from_region(self.region).get_allowed_origins(self.bucket_name)
		return receipt["allowed_origins"]

	def set_allowed_origins(self, origins: list[str]) -> list[str]:
		"""Replace the websites that may call the bucket from a browser. Returns the list as
		Cargo stored it: each origin once, lowercase, without a default port."""
		receipt = ObjectStorageClient.from_region(self.region).set_allowed_origins(self.bucket_name, origins)
		return receipt["allowed_origins"]

	def rotate_credentials(self) -> None:
		"""Replace the bucket's key. The old key stops working at once."""
		receipt = ObjectStorageClient.from_region(self.region).rotate_credentials(
			self.bucket_name, self.access_key
		)
		self.set_credentials(receipt["credentials"])
		self.save()

	def set_credentials(self, credentials: dict) -> None:
		self.access_key = credentials["access_key"]
		self.secret_access_key = credentials["secret_access_key"]

	def subscribe_ai(self) -> None:
		"""Bill the team's AI on the AI plan, once the team has a billing currency."""
		if self.subscription or not has_billing_currency(self.team):
			return
		from central.billing.catalog.plan_setup import AI_PLAN

		subscription = provision_service_subscription(
			self.team, AI_PLAN, changed_by=self.flags.requested_by or frappe.session.user
		)
		self.subscription = subscription["subscription"]

	def validate(self) -> None:
		# AI can be turned on before the team has a billing currency; it is subscribed once it has one.
		waits_for_currency = self.is_ai and not has_billing_currency(self.team)
		if self.status == "Active" and not self.subscription and not waits_for_currency:
			frappe.throw(_("An active service must have a subscription."))

		self.validate_bucket_region()
		self.validate_bucket_is_unclaimed()
		self.validate_one_ai_service()
		self.external_id = self.bucket_name if self.is_bucket else self.team

	def validate_bucket_region(self) -> None:
		"""The form asks for it through mandatory_depends_on, which the server does not check."""
		if self.is_bucket and not self.region:
			frappe.throw(_("A bucket needs a region."), frappe.MandatoryError)

	def validate_one_ai_service(self) -> None:
		"""A team is one Central Team at Grove, so it has one AI service."""
		if not self.is_ai:
			return

		others = {"team": self.team, "add_on_service": AI_SERVICE, "name": ("!=", self.name or "")}
		if frappe.db.exists(self.doctype, others):
			frappe.throw(_("Team {0} already has AI.").format(self.team))

	def validate_bucket_is_unclaimed(self) -> None:
		"""A readable error ahead of the unique constraint, which is what enforces this.
		Two records over one bucket would each hold a key the other has rotated away."""
		if not self.bucket_name:
			return

		duplicate = frappe.db.exists(
			self.doctype,
			{
				"team": self.team,
				"bucket_name": self.bucket_name,
				"name": ("!=", self.name or ""),
			},
		)

		if duplicate:
			frappe.throw(
				_("Team {0} already has a service for bucket {1}.").format(self.team, self.bucket_name)
			)


def get_bucket_name(team: str, region: str, name: str) -> str:
	"""The bucket a team names `name`. Bucket names are shared by every team in a region,
	so the tenant and region prefix keeps teams apart."""
	tenant_id = frappe.db.get_value("Team", team, "tenant_id")
	if not tenant_id:
		frappe.throw(_("This team has no tenant ID."))

	return f"{tenant_id}-{region.casefold()}-{name}"


def get_storage_endpoint_url(region: str) -> str:
	endpoint_url = ServiceDetail.endpoint_for(region, STORAGE_SERVICE)
	if not endpoint_url:
		frappe.throw(_("Object storage is not available in region {0}.").format(region))

	return endpoint_url


def get_storage_plan() -> str:
	plan = frappe.db.get_value(
		"Plan",
		{
			"title": "Object Storage Plan",
			"category": "Remote Storage",
			"sub_category": "Backups",
			"is_active": 1,
		},
		"name",
	)
	if not plan:
		frappe.throw(_("The Object Storage Plan is not configured."))

	return plan


def has_billing_currency(team: str) -> bool:
	return bool(frappe.db.get_value("Billing Profile", team, "currency"))


def on_doctype_update():
	frappe.db.add_unique(
		"Team Service", ["team", "bucket_name"], constraint_name="unique_team_service_bucket"
	)


def billed_subjects(service: str, external_ids: list[str] | None = None) -> dict:
	"""The Team Services that bill a subscription for `service`, by subject, suspended ones included."""
	filters = {"add_on_service": service, "subscription": ["is", "set"]}
	if external_ids is not None:
		filters["external_id"] = ["in", external_ids]
	rows = frappe.get_all(
		"Team Service",
		filters=filters,
		fields=["name", "external_id", "team", "subscription", "region", "creation"],
		order_by="name asc",
	)
	return {row.external_id: row for row in rows}
