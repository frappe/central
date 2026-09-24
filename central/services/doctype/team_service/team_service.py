# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from central.billing.catalog.subscriptions import end_subscription, provision_service_subscription
from central.integrations.bucket_provisioning import (
	STORAGE_SERVICE,
	get_backup_bucket_name,
	get_storage_endpoint_url,
	get_storage_plan,
)
from central.integrations.object_storage import ObjectStorageClient, ObjectStorageNotFound


class TeamService(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		access_key: DF.Data | None
		add_on_service: DF.Link
		bucket_name: DF.Data | None
		endpoint_url: DF.Data | None
		region: DF.Link
		secret_access_key: DF.Password | None
		status: DF.Literal["Active", "Suspended"]
		subscription: DF.Link | None
		team: DF.Link
	# end: auto-generated types

	_DOCTYPE_NAME = "Team Service"

	@property
	def is_bucket(self) -> bool:
		return self.add_on_service == STORAGE_SERVICE

	def is_backup_bucket(self) -> bool:
		"""The bucket this team's servers in the region back up to, managed by Central."""
		return self.is_bucket and self.bucket_name == get_backup_bucket_name(self.team, self.region)

	def before_insert(self) -> None:
		"""Create the bucket, bill it, then let the record save. Cargo answers first, so a
		record always names a bucket that exists."""
		if not self.is_bucket:
			return

		if not self.bucket_name:
			frappe.throw(_("A bucket needs a name."))
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
		if not frappe.db.exists(self._DOCTYPE_NAME, others):
			end_subscription(self.subscription)

	def get_usage(self) -> dict:
		"""What the bucket holds, against its caps, as Cargo counts it."""
		return ObjectStorageClient.from_region(self.region).get_usage(self.bucket_name)["usage"]

	def set_quota(self, size_gib: int, max_objects: int) -> None:
		"""Cap the bucket in Cargo, which owns and enforces the quota. Zero lifts a cap."""
		ObjectStorageClient.from_region(self.region).set_quota(self.bucket_name, size_gib, max_objects)

	def rotate_credentials(self) -> None:
		"""Replace the bucket's key. The old key stops working at once."""
		receipt = ObjectStorageClient.from_region(self.region).rotate_credentials(self.bucket_name)
		self.set_credentials(receipt["credentials"])
		self.save()

	def set_credentials(self, credentials: dict) -> None:
		self.access_key = credentials["access_key"]
		self.secret_access_key = credentials["secret_access_key"]

	def validate(self) -> None:
		if self.status == "Active" and not self.subscription:
			frappe.throw(_("An active service must have a subscription."))

		self.validate_bucket_is_unclaimed()

	def validate_bucket_is_unclaimed(self) -> None:
		"""A readable error ahead of the unique constraint, which is what enforces this.
		Two records over one bucket would each hold a key the other has rotated away."""
		if not self.bucket_name:
			return

		duplicate = frappe.db.exists(
			self._DOCTYPE_NAME,
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


def on_doctype_update():
	frappe.db.add_unique(
		"Team Service", ["team", "bucket_name"], constraint_name="unique_team_service_bucket"
	)
