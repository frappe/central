from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.model.document import Document

from central.infrastructure.doctype.team_ssh_key.team_ssh_key import fingerprint
from central.infrastructure.runway import leases_blocking_pool_change


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
			("cpu_millicores", 1000, 4000),
			("memory_mib", 512, 8192),
			("disk_mib", 1024, 16384),
			("max_job_seconds", 60, 3600),
		):
			if not minimum <= int(self.get(field) or 0) <= maximum:
				frappe.throw(_("Runner pool capacity or deadline is outside pilot limits."))
		if int(self.scale_set_id or 0) < 1:
			frappe.throw(_("Set a positive GitHub scale set ID."))
		fingerprint(self.ssh_public_key)
		if not self.is_new():
			immutable = (
				"team",
				"region",
				"controller_user",
				"repository_url",
				"scale_set_id",
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
