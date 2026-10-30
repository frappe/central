import frappe
from frappe import _

from central.identity.doctype.team.archive import get_archive_blockers


class TeamLifecycle:
	"""How a Team closes and opens again, and the operator actions on it: archive, restore,
	suspend, unsuspend and impersonation. Team inherits it, so callers use `team.archive()`."""

	# Internal; the HTTP surface is central.api.teams.archive_team.
	def archive(self) -> None:
		"""Close the team. Its records stay for billing and audit, and every member loses access."""
		self._require_capability("team:delete")
		if self.status != "Active":
			frappe.throw(_("Only an active team can be archived."))
		if blockers := get_archive_blockers(self.name):
			frappe.throw(_("Before you archive this team, clear: {0}.").format(", ".join(blockers)))

		from central.notification.engine import dispatch
		from central.services.ai import stop_team_keys

		# Grove bills AI usage outside Central, so the keys stop before members lose access.
		stop_team_keys(self.name)
		for invitation in frappe.get_all(
			"Team Invitation", {"team": self.name, "status": "Pending"}, pluck="name"
		):
			frappe.get_doc("Team Invitation", invitation).revoke()

		self.status = "Archived"
		self.flags.from_team_archive = True
		self.save()
		self.add_comment("Info", _("{0} archived this team.").format(frappe.session.user))
		dispatch(self.name, "team_archived", affected_user=self.owner_user)

	# Internal; the HTTP surface is central.api.teams.restore_team.
	def restore(self) -> None:
		"""Operator action: open an archived team again. AI keys stay revoked."""
		frappe.only_for("System Manager")
		if self.status != "Archived":
			frappe.throw(_("Only an archived team can be restored."))

		self.status = "Active"
		self.save()
		self.add_comment("Info", _("{0} restored this team.").format(frappe.session.user))

	# Internal; the HTTP surface is central.api.teams.suspend_team.
	def suspend(self, reason: str) -> None:
		"""Operator action: close the team for now, for example for abuse. Running servers stop,
		AI keys pause, bucket keys are replaced and members lose access. The reason stays on the
		team for staff."""
		from central.notification.engine import dispatch
		from central.resource_actions import submit_command
		from central.services.ai import set_team_suspended
		from central.services.doctype.team_service.team_service import STORAGE_SERVICE

		frappe.only_for("System Manager")
		reason = (reason or "").strip()
		if not reason:
			frappe.throw(_("Enter why you are suspending this team."))
		if self.status != "Active":
			frappe.throw(_("Only an active team can be suspended."))

		running = frappe.get_all(
			"Virtual Machine",
			{"team": self.name, "status": "Running", "atlas_vm_id": ("is", "set")},
			pluck="name",
		)
		for server in running:
			submit_command("stop", self.name, server)
		set_team_suspended(self.name, True)
		# Cargo cannot pause a key, so a new key, which only staff can read, replaces each one.
		buckets = frappe.get_all(
			"Team Service",
			{"team": self.name, "add_on_service": STORAGE_SERVICE, "status": "Active"},
			pluck="name",
		)
		for bucket in buckets:
			frappe.get_doc("Team Service", bucket).rotate_credentials()

		self.status = "Suspended"
		self.save()
		self.add_comment(
			"Info", _("{0} suspended this team. Reason: {1}").format(frappe.session.user, reason)
		)
		dispatch(self.name, "team_suspended", affected_user=self.owner_user)

	# Internal; the HTTP surface is central.api.teams.unsuspend_team.
	def unsuspend(self) -> None:
		"""Operator action: give members access again. Servers stay stopped until the owner starts them."""
		from central.notification.engine import dispatch
		from central.services.ai import set_team_suspended

		frappe.only_for("System Manager")
		if self.status != "Suspended":
			frappe.throw(_("Only a suspended team can be unsuspended."))

		set_team_suspended(self.name, False)
		self.status = "Active"
		self.save()
		self.add_comment("Info", _("{0} unsuspended this team.").format(frappe.session.user))
		dispatch(self.name, "team_unsuspended", affected_user=self.owner_user)

	# Internal; the HTTP surface is central.api.teams.impersonate_team_owner.
	def get_impersonation_url(self, reason: str, notify_owner: bool = False) -> str:
		"""Operator action: open the console as this team. The reason stays on the team for staff.
		The owner gets an email only when the operator asks for one."""
		frappe.only_for("System Manager")
		reason = (reason or "").strip()
		if not reason:
			frappe.throw(_("Enter why you are opening this team."))

		if notify_owner:
			from central.notification.engine import dispatch

			dispatch(self.name, "team_impersonated", affected_user=self.owner_user)

		comment = (
			_("{0} impersonated the team owner and emailed them. Reason: {1}")
			if notify_owner
			else _("{0} impersonated the team owner. Reason: {1}")
		)
		self.add_comment("Info", comment.format(frappe.session.user, reason))
		return f"/dashboard/servers?view_as={self.name}"
