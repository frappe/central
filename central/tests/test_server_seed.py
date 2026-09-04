import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import ensure_team, purge_teams
from central.demo.servers import ASSETS, REGIONS, _seed_resource_ids, seed, summary, teardown


class TestServerSeed(IntegrationTestCase):
	"""The demo fleet seed commits real rows, so every test restores the site by
	running teardown() in cleanup (mirroring how developer_setup tests handle
	their committed bootstrap rows)."""

	TEAM = "team-server-seed"

	def setUp(self):
		frappe.set_user("Administrator")
		self.original_developer_mode = frappe.conf.get("developer_mode")
		# seed() attaches its fleet to the oldest Active Teams, so one has to exist.
		# A fresh site has none, so this can't lean on a team some other test happens
		# to leave behind. No commit needed: the suite shares one connection, so an
		# uncommitted insert is already visible to seed().
		ensure_team(self.TEAM)
		# Registered separately and run LIFO, so a failure in one step still runs the
		# rest: purge the team, then teardown() — whose commit is what persists the
		# purge — then restore the flag. Nothing here commits on its own.
		self.addCleanup(self._restore_developer_mode)
		self.addCleanup(self._teardown_fleet)
		self.addCleanup(self._purge_team)

	def _purge_team(self):
		frappe.set_user("Administrator")
		purge_teams([self.TEAM])

	def _teardown_fleet(self):
		frappe.set_user("Administrator")
		frappe.conf.developer_mode = 1
		teardown()

	def _restore_developer_mode(self):
		frappe.conf.developer_mode = self.original_developer_mode

	def test_refuses_without_developer_mode(self):
		frappe.conf.developer_mode = 0
		with self.assertRaises(frappe.PermissionError):
			seed()
		with self.assertRaises(frappe.PermissionError):
			teardown()

	def test_seed_is_idempotent(self):
		frappe.conf.developer_mode = 1
		first = seed()
		second = seed()

		self.assertEqual(first, second)
		self.assertEqual(first["atlas_instances"], len(REGIONS))
		self.assertEqual(first["assets"], len(ASSETS))
		# Only Running assets carry a billing contract (Asset.on_update).
		running = sum(1 for row in ASSETS if row[3] == "Running")
		self.assertEqual(first["subscriptions"], running)
		# Every seeded VM records the version it was "provisioned" with.
		versions = frappe.get_all(
			"Asset", filters={"name": ["in", _seed_resource_ids()]}, pluck="frappe_version"
		)
		self.assertTrue(all(versions))

	def test_teardown_removes_all_seeded_rows(self):
		frappe.conf.developer_mode = 1
		seed()
		teardown()

		leftovers = summary()
		self.assertEqual(leftovers["atlas_instances"], 0)
		self.assertEqual(leftovers["assets"], 0)
		self.assertEqual(leftovers["subscriptions"], 0)
		self.assertFalse(frappe.get_all("Subscription", filters={"asset_id": ["in", _seed_resource_ids()]}))
