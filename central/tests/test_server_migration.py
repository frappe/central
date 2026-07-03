from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.api.migrations import cancel_migration, list_migrations, migrate_server
from central.api.servers import start_server
from central.central.doctype.server_migration.server_migration import run_due_migrations
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	make_billing_team,
	make_plan,
	make_user,
	run_enqueued_inline,
	seed_running_resource,
	set_team_tier,
)
from central.tests.test_iam import ensure_user

FROM_R = "sm-from-region"
TO_R = "sm-to-region"
VM = "sm-vm-1"
NEW_VM = "sm-vm-new"


def _ensure_tier_level(name):
	if not frappe.db.exists("Trust Tier Level", name):
		frappe.get_doc(
			{
				"doctype": "Trust Tier Level", "__newname": name, "tier": name,
				"sequence": 1, "is_default": 0, "max_resource_count": 50, "min_paid_invoices": 0,
				"thresholds": [{"currency": "INR", "max_spend": 100000, "min_cumulative_paid": 0}],
			}
		).insert(ignore_permissions=True)


class TestServerMigration(IntegrationTestCase):
	"""The Change Plan flow's migration path: request validation, scheduling, the
	execution job's provision→re-bill→terminate order, and its failure discipline."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("migration.owner@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Migration Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		ensure_atlas_instance(FROM_R)
		ensure_atlas_instance(TO_R)
		complete_billing_profile(self.team.name, currency="INR")
		_ensure_tier_level("t1")
		set_team_tier(self.team.name, max_spend=1_000_000)
		self.plan = make_plan("sm-plan")
		# Writes persist across tests in a class — start each test from a clean slate.
		frappe.db.delete("Server Migration", {"asset": VM})
		self.subscription = seed_running_resource(self.team.name, VM, FROM_R, self.plan)
		# db_set bypasses the Running-status doc event that enables the subscription.
		frappe.db.set_value("Subscription", self.subscription, "enabled", 1)
		frappe.db.set_value(
			"Asset",
			VM,
			{
				"status": "Running",
				"team": self.team.name,
				"cluster": FROM_R,
				"migration_in_progress": 0,
				"resize_in_progress": 0,
			},
		)

		create_patcher = patch(
			"central.integrations.atlas.AtlasClient.create_vm", return_value={"name": NEW_VM}
		)
		action_patcher = patch("central.integrations.atlas.AtlasClient.vm_action", return_value="task-1")
		self.create_vm = create_patcher.start()
		self.vm_action = action_patcher.start()
		self.addCleanup(create_patcher.stop)
		self.addCleanup(action_patcher.stop)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _migrate(self, **kwargs):
		"""Call the endpoint as the owner with jobs running inline."""
		frappe.set_user(self.owner)
		try:
			with patch("frappe.enqueue", side_effect=run_enqueued_inline):
				return migrate_server(
					team=kwargs.pop("team", self.team.name),
					resource_id=kwargs.pop("resource_id", VM),
					region=kwargs.pop("region", TO_R),
					plan=kwargs.pop("plan", self.plan),
					**kwargs,
				)
		finally:
			frappe.set_user("Administrator")

	# --- gating + request validation ---------------------------------------

	def test_member_without_caps_cannot_migrate(self):
		# A Billing member can see spend but holds neither server:create nor
		# server:terminate — the gate must refuse before any validation runs.
		biller = make_user("sm-biller@example.test")
		team = make_billing_team(biller)
		frappe.set_user(biller)
		with self.assertRaises(frappe.PermissionError):
			migrate_server(team=team.name, resource_id=VM, region=TO_R, plan=self.plan)

	def test_rejects_same_region(self):
		with self.assertRaises(frappe.ValidationError):
			self._migrate(region=FROM_R)
		self.create_vm.assert_not_called()

	def test_rejects_ambiguous_pricing(self):
		includes = [{"resource_type": "Compute", "quantity": 1, "unit": "vCPU"}]
		with self.assertRaises(frappe.ValidationError):
			self._migrate(includes=includes)  # plan default + includes
		with self.assertRaises(frappe.ValidationError):
			self._migrate(plan=None)  # neither

	def test_rejects_past_schedule(self):
		past = add_to_date(now_datetime(), hours=-1)
		with self.assertRaises(frappe.ValidationError):
			self._migrate(scheduled_at=str(past))

	def test_rejects_second_active_migration(self):
		future = str(add_to_date(now_datetime(), hours=2))
		self._migrate(scheduled_at=future)
		with self.assertRaises(frappe.ValidationError):
			self._migrate(scheduled_at=future)

	# --- scheduling ----------------------------------------------------------

	def test_scheduled_migration_waits_for_its_time(self):
		future = str(add_to_date(now_datetime(), hours=2))
		result = self._migrate(scheduled_at=future)
		self.assertEqual(result["status"], "Scheduled")
		self.create_vm.assert_not_called()

		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			run_due_migrations()  # not due yet
		self.create_vm.assert_not_called()

		frappe.db.set_value("Server Migration", result["migration"], "scheduled_at", now_datetime())
		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			run_due_migrations()
		self.assertEqual(
			frappe.db.get_value("Server Migration", result["migration"], "status"), "Completed"
		)

	# --- execution -----------------------------------------------------------

	def test_immediate_migration_end_to_end(self):
		result = self._migrate()
		doc = frappe.get_doc("Server Migration", result["migration"])

		self.assertEqual(doc.status, "Completed")
		self.assertEqual(doc.new_resource_id, NEW_VM)
		# Replacement provisioned with the clone handoff naming the source.
		kwargs = self.create_vm.call_args.kwargs
		self.assertEqual(kwargs["clone_from_vm"], VM)
		self.assertEqual(kwargs["clone_from_region"], FROM_R)
		# Billing moved: a new subscription opens on the replacement in the target
		# cluster; the old one is closed by a Cancelled segment.
		new_sub = frappe.db.get_value(
			"Subscription", {"asset_id": NEW_VM}, ["cluster", "plan"], as_dict=True
		)
		self.assertEqual(new_sub.cluster, TO_R)
		self.assertEqual(new_sub.plan, self.plan)
		self.assertTrue(
			frappe.db.exists(
				"Subscription Change", {"subscription": self.subscription, "change_type": "Cancelled"}
			)
		)
		# Source terminated, and the console flag is cleared.
		self.vm_action.assert_called_once_with(VM, "terminate")
		self.assertEqual(frappe.db.get_value("Asset", VM, "migration_in_progress"), 0)

	def test_failed_migration_records_error_and_clears_flag(self):
		self.create_vm.side_effect = Exception("atlas unreachable")
		# The job's failure path rollback/commits for worker context; neutralise both
		# so the test transaction can observe (and later discard) the Failed write.
		with patch("frappe.db.rollback"), patch("frappe.db.commit"):
			with self.assertRaises(Exception):
				self._migrate()
		migration = frappe.db.get_value(
			"Server Migration", {"asset": VM}, ["status", "error"], as_dict=True
		)
		self.assertEqual(migration.status, "Failed")
		self.assertIn("atlas unreachable", migration.error)
		self.assertEqual(frappe.db.get_value("Asset", VM, "migration_in_progress"), 0)

	# --- cancel + reads + power gate ----------------------------------------

	def test_cancel_scheduled_only(self):
		future = str(add_to_date(now_datetime(), hours=2))
		name = self._migrate(scheduled_at=future)["migration"]

		frappe.set_user(self.owner)
		result = cancel_migration(team=self.team.name, migration=name)
		self.assertEqual(result["status"], "Cancelled")

		frappe.db.set_value("Server Migration", name, "status", "Running")
		with self.assertRaises(frappe.ValidationError):
			cancel_migration(team=self.team.name, migration=name)

	def test_list_migrations_is_curated_and_team_scoped(self):
		future = str(add_to_date(now_datetime(), hours=2))
		self._migrate(scheduled_at=future)

		frappe.set_user(self.owner)
		rows = list_migrations(team=self.team.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["asset"], VM)
		self.assertEqual(rows[0]["to_cluster"], TO_R)
		self.assertNotIn("error", rows[0])

	def test_power_blocked_while_migrating(self):
		frappe.db.set_value("Asset", VM, "migration_in_progress", 1)
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			start_server(team=self.team.name, resource_id=VM)
