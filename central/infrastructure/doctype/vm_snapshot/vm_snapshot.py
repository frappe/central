from __future__ import annotations

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, get_datetime, now_datetime, today

from central.errors import AtlasConnectionError, AtlasRequestUncertain, AtlasResourceGone
from central.integrations.atlas import AtlasClient

# The Atlas image states this record acts on. Every other state is still in progress.
ATLAS_OUTCOME = {"available": "Available", "failed": "Failed"}
# A snapshot the region never recorded is given this long before it is called failed.
UNRECORDED_TIMEOUT_MINUTES = 30


class VMSnapshot(Document):
	"""One disk image of a server, kept in its region. Central takes, bills and deletes it;
	the region only runs each command."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		atlas_image_id: DF.Data | None
		error_detail: DF.LongText | None
		expires_at: DF.Datetime | None
		image_offering: DF.Link | None
		is_free: DF.Check
		is_restorable: DF.Check
		region: DF.Link | None
		requested_by: DF.Link | None
		server: DF.Link
		size_mib: DF.Int
		snapshot_type: DF.Literal["Automatic", "Manual", "Terminate"]
		status: DF.Literal["Pending", "Available", "Failed", "Deleted"]
		subscription: DF.Link | None
		team: DF.Link
		title: DF.Data
	# end: auto-generated types

	def before_insert(self) -> None:
		server = frappe.db.get_value(
			"Virtual Machine",
			self.server,
			["team", "cluster", "status", "atlas_vm_id", "image_offering"],
			as_dict=True,
		)
		if not server or server.team != self.team:
			frappe.throw(
				_("Server {0} does not belong to this team.").format(self.server), frappe.PermissionError
			)
		if not server.atlas_vm_id or server.status == "Terminated":
			frappe.throw(_("Only a live server can be snapshotted."))
		if frappe.db.exists("VM Snapshot", {"server": self.server, "status": "Pending"}):
			frappe.throw(_("A snapshot of this server is already in progress."))

		self.region = server.cluster
		self.image_offering = server.image_offering
		self.is_restorable = not is_pilot_offering(server.image_offering)
		self.status = "Pending"
		self.requested_by = self.requested_by or frappe.session.user
		if self.snapshot_type == "Automatic":
			from central.billing.settings import daily_snapshot_retention_hours

			self.expires_at = add_to_date(now_datetime(), hours=daily_snapshot_retention_hours())

	def after_insert(self) -> None:
		frappe.enqueue_doc(self.doctype, self.name, "send_to_region", enqueue_after_commit=True)

	def on_update(self) -> None:
		if not self.has_value_changed("status"):
			return
		if self.status in ("Failed", "Deleted"):
			self.stop_billing()
		if self.status in ("Available", "Deleted"):
			apply_free_allowance(self.server)

	def send_to_region(self) -> None:
		"""Ask the region to image the server. The image carries this record's name as a tag,
		so a reply lost in transit is found again by `sync`."""
		if self.atlas_image_id or self.status != "Pending":
			return

		vm_id = frappe.db.get_value("Virtual Machine", self.server, "atlas_vm_id")
		try:
			image = self.get_client().create_snapshot(vm_id, self.title, self.name)
		except AtlasRequestUncertain:
			return  # The region may have it; `sync` looks it up by tag.
		except AtlasConnectionError as error:
			self.fail(str(error))
			return

		self.db_set("atlas_image_id", image.get("id"))

	@frappe.whitelist(methods=["POST"])
	def sync(self) -> None:
		"""Read the region's image and record where it is. Safe to repeat."""
		self.check_permission("write")
		if self.status != "Pending":
			return

		client = self.get_client()
		try:
			if self.atlas_image_id:
				image = client.get_machine_image(self.atlas_image_id)
			else:
				image = client.find_snapshot_image(self.name)
		except AtlasResourceGone:
			self.fail(_("The region no longer has this snapshot."))
			return

		if image is None:
			if self.is_unrecorded_too_long:
				self.fail(_("The region never started this snapshot."))
			return

		self.atlas_image_id = image["id"]
		outcome = ATLAS_OUTCOME.get(image.get("status"))
		if outcome == "Available":
			self.size_mib = image.get("rootfs_size_mib") or 0
		elif outcome == "Failed":
			self.error_detail = image.get("transfer_error") or _("The region could not finish this snapshot.")
		self.status = outcome or "Pending"
		# The region's answer is system state; no user writes it.
		self.save(ignore_permissions=True)

	@property
	def is_unrecorded_too_long(self) -> bool:
		started = add_to_date(get_datetime(self.creation), minutes=UNRECORDED_TIMEOUT_MINUTES)
		return now_datetime() > started

	@property
	def size_gib(self) -> int:
		return math.ceil((self.size_mib or 0) / 1024)

	def fail(self, reason: str) -> None:
		self.status = "Failed"
		self.error_detail = reason
		# A failed region call is system state; no user writes it.
		self.save(ignore_permissions=True)

	def keep(self) -> None:
		"""Stop the automatic deletion of a daily snapshot. It is billed only while it is not
		one of its server's free snapshots."""
		if self.status != "Available":
			frappe.throw(_("Only an available snapshot can be kept."))
		if not self.expires_at:
			frappe.throw(_("This snapshot is kept already."))

		# Only the deletion time changes; the free flag and billing belong to the allowance.
		self.db_set("expires_at", None)

	def set_free(self, is_free: bool) -> None:
		"""Bill this snapshot by size, or stop billing it, as its place among the server's
		snapshots decides."""
		if is_free:
			self.stop_billing()
		elif not self.subscription:
			from central.billing.catalog.snapshots import open_snapshot_subscription

			self.subscription = open_snapshot_subscription(self.team, self.name, self.region, self.size_gib)
		self.db_set({"is_free": int(is_free), "subscription": self.subscription})

	def stop_billing(self) -> None:
		"""Close the storage subscription. A later one opens if the snapshot is billed again."""
		if not self.subscription:
			return

		from central.billing.catalog.snapshots import close_snapshot_subscription

		close_snapshot_subscription(self.subscription)
		self.subscription = None
		self.db_set("subscription", None)

	def delete_from_region(self) -> None:
		"""Remove the image from the region and stop billing. The record stays for the invoice."""
		# The allowance may have changed the free flag and billing since this copy was read.
		self.reload()
		if self.status == "Deleted":
			return
		if self.status == "Pending":
			frappe.throw(_("Wait until the snapshot finishes before you delete it."))

		if self.atlas_image_id:
			try:
				self.get_client().delete_image(self.atlas_image_id)
			except AtlasResourceGone:
				pass

		self.status = "Deleted"
		self.expires_at = None
		# The API authorizes the customer by capability; the DocType grants no team write.
		self.save(ignore_permissions=True)

	def get_client(self) -> AtlasClient:
		instance = frappe.get_cached_doc("Region", self.region)
		return AtlasClient(instance, frappe.db.get_value("Team", self.team, "tenant_id"))


def apply_free_allowance(server: str) -> None:
	"""The newest available snapshots of a server, up to the free count, are free. Every
	older one is billed by size. Runs whenever a snapshot of the server becomes available
	or is deleted, so a snapshot moves between free and billed as newer ones come and go."""
	from central.billing.settings import free_snapshots_per_server

	names = frappe.get_all(
		"VM Snapshot",
		filters={"server": server, "status": "Available"},
		order_by="creation desc",
		pluck="name",
	)
	free = free_snapshots_per_server()
	for position, name in enumerate(names):
		snapshot = frappe.get_doc("VM Snapshot", name)
		try:
			snapshot.set_free(position < free)
		except frappe.ValidationError as error:
			# A region with no Snapshot rate cannot bill yet; the next change tries again.
			snapshot.db_set("error_detail", str(error))


def is_pilot_offering(offering: str | None) -> bool:
	if not offering:
		return False
	return frappe.get_cached_doc("Image Offering", offering).get_image_tags().get("purpose") == "pilot"


def take_automatic_snapshots() -> None:
	"""Scheduler: one daily snapshot of each running server in a region that has
	automatic snapshots on, unless its owner turned them off."""
	regions = frappe.get_all("Region", filters={"automatic_snapshots": 1, "status": "Active"}, pluck="name")
	if not regions:
		return

	servers = frappe.get_all(
		"Virtual Machine",
		filters={
			"cluster": ["in", regions],
			"status": "Running",
			"skip_automatic_snapshot": 0,
			"atlas_vm_id": ["is", "set"],
		},
		fields=["name", "team"],
	)
	taken = set(
		frappe.get_all(
			"VM Snapshot",
			filters={"snapshot_type": "Automatic", "creation": [">=", today()]},
			pluck="server",
		)
	)
	for server in servers:
		if server.name not in taken:
			_take_automatic_snapshot(server)


def _take_automatic_snapshot(server) -> None:
	try:
		frappe.get_doc(
			{
				"doctype": "VM Snapshot",
				"title": _("Daily {0}").format(today()),
				"team": server.team,
				"server": server.name,
				"snapshot_type": "Automatic",
				"requested_by": "Administrator",
			}
		).insert(ignore_permissions=True)  # A system schedule, not a user, takes it.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- keep each snapshot if a later server fails
	except frappe.ValidationError:
		frappe.db.rollback()
		frappe.log_error(title=f"Automatic snapshot failed: {server.name}")


def sync_pending_snapshots() -> None:
	"""Scheduler: record the region's answer for every snapshot still in progress."""
	for name in frappe.get_all("VM Snapshot", filters={"status": "Pending"}, pluck="name"):
		try:
			frappe.get_doc("VM Snapshot", name).sync()
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- keep each outcome if a later sync fails
		except AtlasConnectionError:
			frappe.db.rollback()  # The region did not answer; the next run asks again.


def delete_expired_snapshots() -> None:
	"""Scheduler: delete the daily snapshots that reached their deletion time."""
	# Frappe reads an empty date as the earliest one, so the date filter also needs "is set".
	expired = frappe.get_all(
		"VM Snapshot",
		filters=[
			["status", "in", ["Available", "Failed"]],
			["expires_at", "is", "set"],
			["expires_at", "<=", now_datetime()],
		],
		pluck="name",
	)
	for name in expired:
		_delete_expired(name)


def _delete_expired(name: str) -> None:
	try:
		frappe.get_doc("VM Snapshot", name).delete_from_region()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- keep each outcome if a later one fails
	except frappe.ValidationError as error:
		frappe.db.rollback()
		frappe.db.set_value("VM Snapshot", name, "error_detail", str(error))
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- leave the reason where the operator looks


def on_doctype_update() -> None:
	frappe.db.add_index("VM Snapshot", ["team", "status"])
	frappe.db.add_index("VM Snapshot", ["status", "expires_at"])
