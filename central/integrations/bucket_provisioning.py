from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

import frappe
from frappe import _
from frappe.utils.synchronization import filelock

from central.services.doctype.service_detail.service_detail import ServiceDetail

STORAGE_SERVICE = "storage"
STORAGE_PLAN = {
	"title": "Object Storage Plan",
	"category": "Remote Storage",
	"sub_category": "Backups",
	"is_active": 1,
}
# One create answered by Cargo, or the wait gives up and the server boots without backups.
LOCK_TIMEOUT_SECONDS = 60

if TYPE_CHECKING:
	from central.services.doctype.team_service.team_service import TeamService


class BucketConfiguration(TypedDict):
	"""The bucket as Pilot reads it. The keys are fixed by `pilot.integrations.central`."""

	access_key: str
	secret_key: str
	bucket: str
	provider: str
	region: str
	endpoint_url: str


class BucketProvisioning:
	"""A team's backup bucket in one region: the existing one, or a new one created and
	billed. Cargo owns the bucket's own state; Central records only that it holds one."""

	def __init__(self, request):
		self.team = request.team
		self.region = request.region
		self.requested_by = request.requested_by
		self.bucket_name = get_backup_bucket_name(self.team, self.region)

	def get_configuration(self) -> BucketConfiguration:
		"""The team's bucket, provisioned once under a lock so two requests for the same
		server cannot each ask Cargo for it."""
		with filelock(f"team-storage-{self.bucket_name}", timeout=LOCK_TIMEOUT_SECONDS):
			return self.get_existing() or self.create_new()

	def get_existing(self) -> BucketConfiguration | None:
		name = frappe.db.get_value(
			"Team Service",
			{"team": self.team, "region": self.region, "bucket_name": self.bucket_name},
		)
		if not name:
			return None

		service: TeamService = frappe.get_doc("Team Service", name)
		if service.status == "Suspended":
			frappe.throw(_("This team's storage service is suspended. Please contact support."))

		return self.read_configuration(service)

	def create_new(self) -> BucketConfiguration:
		service: TeamService = frappe.get_doc(
			{
				"doctype": "Team Service",
				"team": self.team,
				"add_on_service": STORAGE_SERVICE,
				"region": self.region,
				"bucket_name": self.bucket_name,
			}
		)
		service.flags.requested_by = self.requested_by
		# The authorized provisioning request owns this system-created service record.
		service.insert(ignore_permissions=True)
		frappe.db.commit()

		return self.read_configuration(service)

	def read_configuration(self, service: TeamService) -> BucketConfiguration:
		configuration = BucketConfiguration(
			access_key=service.access_key,
			secret_key=service.get_password("secret_access_key"),
			bucket=service.bucket_name,
			provider="garage",
			region=service.region,
			endpoint_url=service.endpoint_url,
		)
		if not all(configuration.values()):
			frappe.throw(_("This team's storage credentials are incomplete. Please contact support."))

		return configuration


def get_backup_bucket_name(team: str, region: str) -> str:
	"""Derived, never chosen, so every request names the same bucket."""
	tenant_id = frappe.db.get_value("Team", team, "tenant_id")
	if not tenant_id:
		frappe.throw(_("This team has no tenant ID."))

	return f"team-{tenant_id}-{region.casefold()}-backups"


def get_storage_endpoint_url(region: str) -> str:
	endpoint_url = ServiceDetail.endpoint_for(region, STORAGE_SERVICE)
	if not endpoint_url:
		frappe.throw(_("Object storage is not available in region {0}.").format(region))

	return endpoint_url


def get_storage_plan() -> str:
	plan = frappe.db.get_value("Plan", STORAGE_PLAN, "name")
	if not plan:
		frappe.throw(_("The Object Storage Plan is not configured."))

	return plan
