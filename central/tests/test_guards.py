import frappe
from frappe.tests import IntegrationTestCase

from central.iam import clear_grants_cache
from central.tests.test_iam import ensure_user
from central.utils.guards import require_capability


@require_capability("server:view", "Server access is required.")
def guarded_team(team: str | None = None, marker: str | None = None) -> tuple[str, str | None]:
	return team, marker


class TestCapabilityGuard(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.user = ensure_user(f"guard.{frappe.generate_hash(length=8)}@example.test")
		self.team = frappe.get_doc("Team", {"owner_user": self.user})

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_resolves_omitted_positional_and_keyword_team_arguments(self):
		frappe.set_user(self.user)

		self.assertEqual(guarded_team(), (self.team.name, None))
		self.assertEqual(guarded_team(self.team.name, "positional"), (self.team.name, "positional"))
		self.assertEqual(guarded_team(team=self.team.name, marker="keyword"), (self.team.name, "keyword"))

	def test_omitted_team_is_ambiguous_for_a_user_with_multiple_teams(self):
		self._team("Second Guard Team")
		frappe.set_user(self.user)

		with self.assertRaises(frappe.ValidationError):
			guarded_team()

	def test_suspended_team_is_denied_but_operator_bypass_remains(self):
		self.team.status = "Suspended"
		self.team.save()
		clear_grants_cache()

		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			guarded_team(self.team.name)

		frappe.set_user("Administrator")
		self.assertEqual(guarded_team(self.team.name), (self.team.name, None))

	def _team(self, label: str):
		return frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": f"{label} {frappe.generate_hash(length=8)}",
				"owner_user": "Administrator",
				"members": [
					{"user": "Administrator", "role": "Owner", "status": "Active"},
					{"user": self.user, "role": "Viewer", "status": "Active"},
				],
			}
		).insert()
