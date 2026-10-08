from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.model.document import Document

from central.infrastructure.doctype.team_ssh_key.team_ssh_key import fingerprint
from central.infrastructure.runway import (
	MAX_CPU_MILLICORES,
	MAX_MEMORY_MIB,
	SCALE_SET_NAME_PATTERN,
	leases_blocking_pool_change,
	shape_from_scale_set_name,
)


class RunnerPool(Document):
	def validate(self) -> None:
		url = urlsplit(self.repository_url or "")
		if (
			url.scheme != "https"
			or url.netloc != "github.com"
			or len(url.path.strip("/").split("/")) != 2
			or url.query
			or url.fragment
		):
			frappe.throw(_("Use one HTTPS github.com repository URL."))
		for field, minimum, maximum in (
			("max_concurrency", 1, 4),
			("cpu_millicores", 1000, MAX_CPU_MILLICORES),
			("memory_mib", 512, MAX_MEMORY_MIB),
			("disk_mib", 1024, 16384),
			("max_job_seconds", 60, 3600),
		):
			if not minimum <= int(self.get(field) or 0) <= maximum:
				frappe.throw(_("Runner pool capacity or deadline is outside pilot limits."))
		if int(self.scale_set_id or 0) < 1:
			frappe.throw(_("Set a positive GitHub scale set ID."))
		if not SCALE_SET_NAME_PATTERN.match(self.scale_set_name or ""):
			frappe.throw(
				_("Scale set name must begin runway- and hold lowercase letters, numbers or hyphens.")
			)
		# The scale set's name is the label a workflow writes, so when that name states a
		# shape it has to be this pool's shape. Otherwise a workflow asking for 8 GiB would
		# be admitted by the name and handed 6, which is the mismatch the label exists to
		# prevent. A name that states no shape, like runway-dogfood, says nothing to check.
		stated = shape_from_scale_set_name(self.scale_set_name)
		if stated and stated != (int(self.cpu_millicores or 0), int(self.memory_mib or 0)):
			frappe.throw(
				_("Scale set {0} states {1} vCPU and {2} GiB, but this pool serves {3} vCPU and {4} GiB.").format(
					self.scale_set_name,
					stated[0] // 1000,
					stated[1] // 1024,
					int(self.cpu_millicores or 0) // 1000,
					int(self.memory_mib or 0) // 1024,
				)
			)
		fingerprint(self.ssh_public_key)
		if not self.is_new():
			immutable = (
				"team",
				"region",
				"controller_user",
				"repository_url",
				"scale_set_id",
				"scale_set_name",
				"image_id",
				"ssh_public_key",
				"cpu_millicores",
				"memory_mib",
				"disk_mib",
			)
			if any(self.has_value_changed(field) for field in immutable) and leases_blocking_pool_change(
				self.name, self.team
			):
				frappe.throw(_("Drain every runner lease before changing pool identity or image."))

	def on_trash(self) -> None:
		if frappe.db.exists("Runner Lease", {"pool": self.name}):
			frappe.throw(_("Retain a pool while its lease history exists."))


def on_doctype_update() -> None:
	frappe.db.add_index("Runner Pool", ["team", "status"])
