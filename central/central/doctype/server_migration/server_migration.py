from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

# A migration replaces the VM rather than moving it: provision a replacement in the
# target region (Atlas restores the data — see AtlasClient.create_vm's clone_from
# params), open the replacement's Subscription, cancel the source's, then terminate
# the source VM. The Asset mirror follows via Atlas events, exactly as with create
# and terminate. Execution mirrors the resize job's discipline: flag the Asset,
# run in a background job, always clear the flag (central/billing/catalog/
# subscriptions.py::_apply_resize).

ACTIVE_STATUSES = ("Scheduled", "Running")


class ServerMigration(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		asset: DF.Link
		completed_at: DF.Datetime | None
		error: DF.SmallText | None
		from_cluster: DF.Link
		includes_json: DF.JSON | None
		new_resource_id: DF.Data | None
		plan: DF.Link | None
		pricing_mode: DF.Literal["Preset", "Composed"]
		scheduled_at: DF.Datetime | None
		started_at: DF.Datetime | None
		status: DF.Literal["Scheduled", "Running", "Completed", "Failed", "Cancelled"]
		sub_category: DF.Data | None
		subscription: DF.Link | None
		team: DF.Link
		to_cluster: DF.Link
	# end: auto-generated types

	def validate(self):
		if self.to_cluster == self.from_cluster:
			frappe.throw(_("The server is already in {0} — pick a different region.").format(self.from_cluster))
		if self.is_new():
			self._validate_target_active()
			self._validate_pricing()
			self._validate_schedule()
			self._validate_no_active_sibling()

	def _validate_target_active(self):
		if frappe.db.get_value("Atlas Instance", self.to_cluster, "status") != "Active":
			frappe.throw(_("Region {0} isn't accepting servers right now.").format(self.to_cluster))

	def _validate_pricing(self):
		if self.pricing_mode == "Preset" and not self.plan:
			frappe.throw(_("A Preset migration needs a plan."))
		if self.pricing_mode == "Composed" and not self.includes():
			frappe.throw(_("A Composed migration needs its config rows."))

	def _validate_schedule(self):
		if self.scheduled_at and get_datetime(self.scheduled_at) <= now_datetime():
			frappe.throw(_("The scheduled time must be in the future."))

	def _validate_no_active_sibling(self):
		if frappe.db.exists(
			"Server Migration", {"asset": self.asset, "status": ["in", ACTIVE_STATUSES], "name": ["!=", self.name]}
		):
			frappe.throw(_("A migration for this server is already scheduled or running."))

	def includes(self) -> list[dict]:
		"""The composed config rows carried by this migration ([] for a preset)."""
		if not self.includes_json:
			return []
		rows = json.loads(self.includes_json) if isinstance(self.includes_json, str) else self.includes_json
		return [dict(r) for r in rows]

	def cancel_migration(self):
		"""Withdraw a not-yet-started migration. Running ones can't be pulled back —
		the replacement VM may already exist."""
		if self.status != "Scheduled":
			frappe.throw(_("Only a scheduled migration can be cancelled."))
		self.db_set("status", "Cancelled", notify=True)


def run_due_migrations():
	"""Cron picker: enqueue every Scheduled migration whose time has come. Immediate
	migrations (no scheduled_at) are enqueued by the API at request time; picking them
	up here too makes the cron a backstop for a lost job."""
	due = frappe.get_all(
		"Server Migration",
		filters={"status": "Scheduled"},
		or_filters=[["scheduled_at", "is", "not set"], ["scheduled_at", "<=", now_datetime()]],
		pluck="name",
	)
	for name in due:
		enqueue_migration(name)


def enqueue_migration(name: str):
	frappe.enqueue(run_migration, queue="long", timeout=900, enqueue_after_commit=True, name=name)


def run_migration(name: str):
	"""Execute one migration end-to-end (background job). Claims the doc by flipping
	Scheduled → Running, so the cron backstop and a direct enqueue can't double-run it.
	On failure: roll back the partial write, record Failed on a fresh committed write,
	clear the Asset flag so the console can't wedge on "Migrating", and re-raise."""
	from central.central.doctype.asset.asset import Asset

	doc = frappe.get_doc("Server Migration", name)
	if doc.status != "Scheduled":
		return
	doc.db_set({"status": "Running", "started_at": now_datetime()}, notify=True)
	Asset.mark_migrating(doc.asset, True)
	try:
		_execute(doc)
	except Exception as e:
		frappe.db.rollback()
		frappe.db.set_value(
			"Server Migration", name, {"status": "Failed", "error": str(e)[:500]}, update_modified=True
		)
		Asset.mark_migrating(doc.asset, False)
		frappe.db.commit()
		raise
	Asset.mark_migrating(doc.asset, False)
	doc.db_set({"status": "Completed", "completed_at": now_datetime()}, notify=True)


def _execute(doc: ServerMigration):
	"""Provision the replacement, move the subscription, retire the source — in an
	order where every failure leaves the team no worse off: nothing is cancelled or
	terminated until the replacement exists and its billing segment is open."""
	from central.billing.catalog.subscriptions import (
		cancel_subscription,
		enforce_headroom,
		provision_composed_subscription,
		provision_subscription,
	)
	from central.integrations.atlas import AtlasClient

	asset = frappe.get_doc("Asset", doc.asset)
	if asset.status == "Terminated":
		frappe.throw(_("The source server is already terminated."))

	enforce_headroom(doc.team, _target_rate(doc), exclude=doc.subscription)

	shape = _target_shape(doc)
	email = frappe.db.get_value("Team", doc.team, "owner_user")
	vm = AtlasClient.for_region(doc.to_cluster).create_vm(
		team=doc.team,
		title=asset.title or "server",
		vcpus=int(shape.get("vcpus") or 1),
		memory_megabytes=int(shape.get("memory_megabytes") or 512),
		disk_gigabytes=int(shape.get("disk_gigabytes") or 10),
		email=email,
		frappe_version=asset.frappe_version,
		clone_from_region=doc.from_cluster,
		clone_from_vm=doc.asset,
	)
	new_id = vm.get("name")
	doc.db_set("new_resource_id", new_id)

	if doc.pricing_mode == "Preset":
		provision_subscription(doc.team, doc.to_cluster, doc.plan, resource_id=new_id)
	else:
		provision_composed_subscription(doc.team, doc.to_cluster, doc.includes(), doc.sub_category, resource_id=new_id)
	if doc.subscription:
		cancel_subscription(doc.subscription)

	AtlasClient.for_region(doc.from_cluster).vm_action(doc.asset, "terminate")


def _target_shape(doc: ServerMigration) -> dict:
	# Reuse the resize flow's shape resolution so a migrated VM sizes exactly like a
	# resized one would.
	from central.billing.catalog.subscriptions import _asset_shape, _plan_shape

	return _plan_shape(doc.plan) if doc.pricing_mode == "Preset" else _asset_shape(doc.includes())


def _target_rate(doc: ServerMigration):
	from central.billing.catalog.pricing import resolve_config_rate

	currency = frappe.db.get_value("Billing Profile", doc.team, "currency")
	if doc.pricing_mode == "Preset":
		return frappe.get_doc("Plan", doc.plan).get_rate(currency, doc.to_cluster)
	return resolve_config_rate(doc.includes(), currency, doc.to_cluster)
