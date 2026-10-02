from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.errors import AtlasRejected
from central.infrastructure.doctype.host_access_grant.host_access_grant import ACCESS_ROLE
from central.tests.utils import ensure_atlas_instance

REGION = "host-access-test"
OPERATOR = "host-access-operator@example.com"
HOST_ID = "01a0d2b4-898d-750f-b2d6-048ab4bd6b77"


class TestHostAccessGrant(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		ensure_atlas_instance(REGION, proxy_domain="par-2.example.com")
		self.create_user(OPERATOR, ACCESS_ROLE)

		self.atlas = Mock()
		self.enterContext(
			patch(
				"central.infrastructure.doctype.host_access_grant.host_access_grant.AtlasClient.for_operator",
				return_value=self.atlas,
			)
		)

	def test_a_user_without_the_access_role_is_refused(self) -> None:
		self.create_user("no-access@example.com")

		with self.assertRaisesRegex(frappe.ValidationError, ACCESS_ROLE):
			self.make_grant(user="no-access@example.com").insert()

	def test_one_host_needs_a_host(self) -> None:
		with self.assertRaisesRegex(frappe.ValidationError, "Select a host"):
			self.make_grant(host=None, host_title=None).insert()

	def test_submit_grants_the_host_until_the_stored_expiry(self) -> None:
		before = datetime.now(UTC)
		grant = self.make_grant(duration_hours="3").insert()
		grant.submit()

		host_id, email, expires_at = self.atlas.grant_host_access.call_args.args
		self.assertEqual((host_id, email), (HOST_ID, OPERATOR))
		self.assertIsNotNone(expires_at.tzinfo)
		self.assertAlmostEqual(expires_at - before, timedelta(hours=3), delta=timedelta(minutes=1))
		self.assertEqual(expires_at.replace(tzinfo=None), frappe.utils.get_datetime(grant.expires_at))

	def test_all_hosts_grants_every_host(self) -> None:
		grant = self.make_grant(scope="All hosts").insert()
		grant.submit()

		self.assertEqual(grant.host, "all")
		self.assertEqual(self.atlas.grant_host_access.call_args.args[0], "all")

	def test_cancel_revokes_the_access(self) -> None:
		grant = self.make_grant().insert()
		grant.submit()

		grant.cancel()

		self.atlas.revoke_host_access.assert_called_once_with(HOST_ID, OPERATOR)

	def test_a_second_active_grant_for_the_same_host_is_refused(self) -> None:
		self.make_grant().insert().submit()

		with self.assertRaisesRegex(frappe.ValidationError, "already gives access"):
			self.make_grant().insert().submit()

	def test_one_host_and_all_hosts_grants_cannot_overlap(self) -> None:
		for first, second in (({"scope": "All hosts"}, {}), ({}, {"scope": "All hosts"})):
			with self.subTest(first=first):
				grant = self.make_grant(**first).insert()
				grant.submit()

				with self.assertRaisesRegex(frappe.ValidationError, "already gives access"):
					self.make_grant(**second).insert().submit()
				grant.cancel()

	def test_grants_for_different_hosts_can_be_active_together(self) -> None:
		self.make_grant().insert().submit()

		self.make_grant(host="another-host", host_title="node-par-2-00002").insert().submit()

		self.assertEqual(self.atlas.grant_host_access.call_count, 2)

	def test_the_active_grant_check_runs_under_a_lock_on_the_person(self) -> None:
		grant = self.make_grant().insert()
		calls = []
		get_value = frappe.db.get_value

		def record(*args, **kwargs):
			calls.append((args[:3], kwargs.get("for_update")))
			return get_value(*args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=record):
			grant.submit()

		self.assertIn((("User", OPERATOR, "name"), True), calls)
		self.assertIn("Host Access Grant", [args[0] for args, for_update in calls if for_update])

	def test_an_atlas_refusal_stops_the_submit(self) -> None:
		self.atlas.grant_host_access.side_effect = AtlasRejected("This region has no Warpgate.")

		with self.assertRaises(AtlasRejected):
			self.make_grant().insert().submit()

	def test_the_ssh_command_names_the_person_host_and_regional_warpgate(self) -> None:
		grant = self.make_grant().insert()

		self.assertEqual(
			grant.get_ssh_command(),
			f"ssh -p 2223 {OPERATOR}:node-par-2-00001@warpgate.par-2.example.com",
		)

	def make_grant(self, **values):
		return frappe.get_doc(
			{
				"doctype": "Host Access Grant",
				"region": REGION,
				"scope": "One host",
				"host": HOST_ID,
				"host_title": "node-par-2-00001",
				"user": OPERATOR,
				"duration_hours": "1",
				**values,
			}
		)

	def create_user(self, email: str, *roles: str) -> None:
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "Host"}).insert()
		frappe.get_doc("User", email).add_roles(*roles)
