from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.patches.v0_0.initialize_resource_actions import execute


class TestResourceActionMigration(IntegrationTestCase):
	def test_preserves_history_and_marks_unconfirmed_acceptance(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Migration", "owner_user": "Administrator"}
		).insert()
		actions = []
		for status in ("Sent", "In Progress", "Succeeded", "Failed"):
			actions.append(
				frappe.get_doc(
					{
						"doctype": "Resource Action",
						"team": team.name,
						"resource_type": "Server",
						"resource_id": "historical-vm",
						"action": "create",
						"status": status,
						"correlation_id": frappe.generate_hash(length=32),
					}
				).insert()
			)

		with patch("frappe.reload_doc"):
			execute()
			first = [action.reload().as_dict() for action in actions]
			execute()
			self.assertEqual(first, [action.reload().as_dict() for action in actions])

		self.assertEqual(
			[action.status for action in actions], ["Uncertain", "Uncertain", "Succeeded", "Failed"]
		)
		for action in actions:
			self.assertEqual(action.title, "historical-vm")
			self.assertEqual(action.request_key, f"migrated-{action.name}")
			self.assertFalse(action.remote_vm_id)
		self.assertFalse(actions[0].retriable)
		self.assertEqual(actions[0].error_code, "OUTCOME_UNKNOWN")
