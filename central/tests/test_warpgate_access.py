from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.errors import AtlasRejected
from central.infrastructure.doctype.warpgate_access.warpgate_access import (
	ACCESS_ROLE,
	ADMIN_ROLE,
	expire_access,
)
from central.tests.utils import ensure_atlas_instance

REGION = "host-access-test"
OPERATOR = "host-access-operator@example.com"
HOST_ID = "01a0d2b4-898d-750f-b2d6-048ab4bd6b77"
MODULE = "central.infrastructure.doctype.warpgate_access.warpgate_access"


class TestWarpgateAccess(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		ensure_atlas_instance(REGION, proxy_domain="par-2.example.com")
		self.create_user(OPERATOR, ACCESS_ROLE)

		self.atlas = Mock()
		self.enterContext(patch(f"{MODULE}.AtlasClient.for_operator", return_value=self.atlas))
		self.enterContext(patch(f"{MODULE}.get_warpgate_regions", return_value=[REGION]))

	def test_a_user_without_the_access_role_is_refused(self) -> None:
		self.create_user("no-access@example.com")

		with self.assertRaisesRegex(frappe.ValidationError, ACCESS_ROLE):
			self.make_access(user="no-access@example.com").insert()

	def test_one_host_needs_a_host(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "Select a host"):
			self.make_access(host=None, host_title=None).insert()

	def test_host_access_lasts_at_most_one_day(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "cannot last 7 days"):
			self.make_access(duration="7 days").insert()

	def test_submit_grants_the_host_until_the_stored_expiry(self) -> None:
		before = datetime.now(UTC)
		access = self.make_access(duration="3 hours").insert()
		access.submit()

		host_id, email, expires_at = self.atlas.grant_host_access.call_args.args
		self.assertEqual((host_id, email), (HOST_ID, OPERATOR))
		self.assertAlmostEqual(expires_at - before, timedelta(hours=3), delta=timedelta(minutes=1))
		self.assertEqual(expires_at.replace(tzinfo=None), frappe.utils.get_datetime(access.expires_at))
		self.assertEqual(access.status, "Active")

	def test_all_hosts_grants_every_host(self) -> None:
		access = self.make_access(access_type="All hosts").insert()
		access.submit()

		self.assertEqual(access.host, "all")
		self.assertEqual(self.atlas.grant_host_access.call_args.args[0], "all")

	def test_cancel_revokes_the_host_access(self) -> None:
		access = self.make_access().insert()
		access.submit()

		access.cancel()

		self.atlas.revoke_host_access.assert_called_once_with(HOST_ID, OPERATOR)
		self.assertEqual(access.status, "Revoked")

	def test_a_second_active_access_for_the_same_host_is_refused(self) -> None:
		self.make_access().insert().submit()

		with self.assertRaisesRegex(frappe.ValidationError, "already gives this access"):
			self.make_access().insert().submit()

	def test_one_host_and_all_hosts_access_cannot_overlap(self) -> None:
		for first, second in (({"access_type": "All hosts"}, {}), ({}, {"access_type": "All hosts"})):
			with self.subTest(first=first):
				access = self.make_access(**first).insert()
				access.submit()

				with self.assertRaisesRegex(frappe.ValidationError, "already gives this access"):
					self.make_access(**second).insert().submit()
				access.cancel()

	def test_access_to_different_hosts_can_be_active_together(self) -> None:
		self.make_access().insert().submit()

		self.make_access(host="another-host", host_title="node-par-2-00002").insert().submit()

		self.assertEqual(self.atlas.grant_host_access.call_count, 2)

	def test_the_active_access_check_runs_under_a_lock_on_the_person(self) -> None:
		access = self.make_access().insert()
		calls = []
		get_value = frappe.db.get_value

		def record(*args, **kwargs):
			calls.append((args[:3], kwargs.get("for_update")))
			return get_value(*args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=record):
			access.submit()

		self.assertIn((("User", OPERATOR, "name"), True), calls)
		self.assertIn("Warpgate Access", [args[0] for args, for_update in calls if for_update])

	def test_an_atlas_refusal_stops_the_submit(self) -> None:
		self.atlas.grant_host_access.side_effect = AtlasRejected("This region has no Warpgate.")

		with self.assertRaises(AtlasRejected):
			self.make_access().insert().submit()

	def test_admin_access_adds_and_removes_the_admin_role(self) -> None:
		access = self.make_admin_access(duration="7 days").insert()
		access.submit()

		self.assertIn(ADMIN_ROLE, frappe.get_roles(OPERATOR))
		self.atlas.grant_host_access.assert_not_called()
		self.assertIsNone(access.region)

		access.cancel()

		self.assertNotIn(ADMIN_ROLE, frappe.get_roles(OPERATOR))
		self.atlas.close_sessions.assert_called_once_with(OPERATOR)
		self.assertEqual(access.status, "Revoked")

	def test_admin_access_can_never_expire(self) -> None:
		access = self.make_admin_access(duration="Never").insert()
		access.submit()

		self.assertIsNone(access.expires_at)

	def test_a_second_active_admin_access_is_refused(self) -> None:
		self.make_admin_access().insert().submit()

		with self.assertRaisesRegex(frappe.ValidationError, "already gives this access"):
			self.make_admin_access().insert().submit()

	def test_the_expiry_job_revokes_ended_access(self) -> None:
		host_access = self.make_access().insert()
		host_access.submit()
		admin_access = self.make_admin_access().insert()
		admin_access.submit()
		current = self.make_access(host="another-host", host_title="node-par-2-00002").insert()
		current.submit()
		for access in (host_access, admin_access):
			access.db_set("expires_at", frappe.utils.add_to_date(None, minutes=-1))

		with patch.object(frappe.db, "commit"):
			expire_access()

		self.atlas.revoke_host_access.assert_called_once_with(HOST_ID, OPERATOR)
		self.atlas.close_sessions.assert_called_once_with(OPERATOR)
		self.assertNotIn(ADMIN_ROLE, frappe.get_roles(OPERATOR))
		statuses = [
			frappe.db.get_value("Warpgate Access", access.name, "status")
			for access in (host_access, admin_access, current)
		]
		self.assertEqual(statuses, ["Expired", "Expired", "Active"])

	def test_a_failed_expiry_stays_active_for_the_next_run(self) -> None:
		access = self.make_access().insert()
		access.submit()
		access.db_set("expires_at", frappe.utils.add_to_date(None, minutes=-1))
		self.atlas.revoke_host_access.side_effect = AtlasRejected("Warpgate did not answer.")

		with patch.object(frappe.db, "commit"), patch.object(frappe.db, "rollback"):
			expire_access()

		self.assertEqual(frappe.db.get_value("Warpgate Access", access.name, "status"), "Active")

	def test_the_ssh_command_names_the_person_host_and_regional_warpgate(self) -> None:
		access = self.make_access().insert()

		self.assertEqual(
			access.get_ssh_command(),
			f"ssh -p 2223 {OPERATOR}:node-par-2-00001@warpgate.par-2.example.com",
		)

	def make_access(self, **values):
		return frappe.get_doc(
			{
				"doctype": "Warpgate Access",
				"access_type": "One host",
				"region": REGION,
				"host": HOST_ID,
				"host_title": "node-par-2-00001",
				"user": OPERATOR,
				"duration": "1 hour",
				**values,
			}
		)

	def make_admin_access(self, **values):
		return frappe.get_doc(
			{
				"doctype": "Warpgate Access",
				"access_type": "Admin",
				"user": OPERATOR,
				"duration": "1 hour",
				**values,
			}
		)

	def create_user(self, email: str, *roles: str) -> None:
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "Host"}).insert()
		frappe.get_doc("User", email).add_roles(*roles)
