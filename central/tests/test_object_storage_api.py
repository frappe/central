from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.object_storage import (
	ObjectStorageNotFound,
	ObjectStorageRejected,
	ObjectStorageRequestUncertain,
)
from central.services.api import storage as api
from central.services.doctype.team_service.team_service import TeamService
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_region

CONTROLLER = "central.services.doctype.team_service.team_service"
ENDPOINT = "https://s3.example.test"


def receipt(name: str, access_key: str = "access") -> dict:
	return {"name": name, "credentials": {"access_key": access_key, "secret_access_key": "secret"}}


class ObjectStorageTestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)
		self.region = ensure_region(f"storage-{self.suffix}")
		self.owner = ensure_user("storage.owner@example.test")
		self.viewer = ensure_user("storage.viewer@example.test")
		self.team = self._team("Storage", {self.viewer: "Viewer"})
		self.other_team = self._team("Other storage", {})

		self.cargo = Mock()
		self.cargo.create_bucket.side_effect = receipt
		self.cargo.rotate_credentials.side_effect = lambda name: receipt(name, "rotated")
		self.cargo.get_usage.return_value = {"usage": {"used_bytes": 2048, "object_count": 3}}
		client = self.enterContext(patch(f"{CONTROLLER}.ObjectStorageClient"))
		client.from_region.return_value = self.cargo
		self.subscribe = self.enterContext(
			patch(f"{CONTROLLER}.provision_service_subscription", return_value={"subscription": "sub-1"})
		)
		self.enterContext(patch(f"{CONTROLLER}.get_storage_plan", return_value="storage-plan"))
		self.enterContext(patch(f"{CONTROLLER}.get_storage_endpoint_url", return_value=ENDPOINT))
		self.end_subscription = self.enterContext(patch(f"{CONTROLLER}.end_subscription"))
		# The storage add-on, plan and subscription are billing fixtures this suite does not need.
		self.enterContext(patch.object(TeamService, "_validate_links"))

	def tearDown(self):
		frappe.set_user("Administrator")

	def _team(self, label: str, members: dict[str, str]) -> str:
		rows = [{"user": self.owner, "role": "Owner", "status": "Active"}]
		rows += [{"user": user, "role": role, "status": "Active"} for user, role in members.items()]
		team = {
			"doctype": "Team",
			"team_name": f"{label} {self.suffix}",
			"owner_user": self.owner,
			"members": rows,
		}
		return frappe.get_doc(team).insert().name

	def _create(self, team: str | None = None, bucket_name: str = "media") -> dict:
		frappe.set_user(self.owner)
		return api.create_bucket(team or self.team, bucket_name, self.region)

	def _create_backup_bucket(self) -> str:
		"""The bucket server provisioning makes; customers cannot name one like it."""
		frappe.set_user("Administrator")
		service = frappe.get_doc(
			{
				"doctype": "Team Service",
				"team": self.team,
				"add_on_service": "storage",
				"region": self.region,
				"bucket_name": f"team-{self._tenant_id(self.team)}-{self.region}-backups",
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.owner)
		return service.name

	def _tenant_id(self, team: str) -> int:
		return frappe.db.get_value("Team", team, "tenant_id")


class TestTeamServiceLifecycle(ObjectStorageTestCase):
	def test_insert_creates_the_bucket_then_bills_it(self):
		bucket = self._create()

		self.cargo.create_bucket.assert_called_once_with(f"{self._tenant_id(self.team)}-{self.region}-media")
		self.subscribe.assert_called_once_with(
			self.team, "storage-plan", cluster=self.region, changed_by=self.owner
		)
		service = frappe.get_doc("Team Service", bucket["name"])
		self.assertEqual(
			(service.status, service.subscription, service.endpoint_url), ("Active", "sub-1", ENDPOINT)
		)
		self.assertEqual(bucket["secret_access_key"], "secret")

	def test_a_refused_bucket_bills_and_records_nothing(self):
		self.cargo.create_bucket.side_effect = ObjectStorageRejected("taken")

		with self.assertRaises(ObjectStorageRejected):
			self._create()

		self.subscribe.assert_not_called()
		self.assertFalse(frappe.db.exists("Team Service", {"team": self.team}))

	def test_an_unconfirmed_bucket_bills_and_records_nothing(self):
		self.cargo.create_bucket.side_effect = ObjectStorageRequestUncertain()

		with self.assertRaises(ObjectStorageRequestUncertain):
			self._create()

		self.subscribe.assert_not_called()
		self.assertFalse(frappe.db.exists("Team Service", {"team": self.team}))

	def test_a_region_without_an_endpoint_never_reaches_cargo(self):
		with (
			patch(f"{CONTROLLER}.get_storage_endpoint_url", side_effect=frappe.ValidationError("none")),
			self.assertRaises(frappe.ValidationError),
		):
			self._create()

		self.cargo.create_bucket.assert_not_called()

	def test_delete_removes_the_record_when_cargo_already_lost_the_bucket(self):
		bucket = self._create()
		self.cargo.delete_bucket.side_effect = ObjectStorageNotFound("gone")

		api.delete_bucket(self.team, bucket["name"])

		self.assertFalse(frappe.db.exists("Team Service", bucket["name"]))

	def test_deleting_the_last_bucket_ends_the_subscription(self):
		first = self._create(bucket_name="first")
		second = self._create(bucket_name="second")

		api.delete_bucket(self.team, first["name"])
		self.end_subscription.assert_not_called()

		api.delete_bucket(self.team, second["name"])
		self.end_subscription.assert_called_once_with("sub-1")


class TestObjectStorageApi(ObjectStorageTestCase):
	def test_lists_regions_and_only_the_teams_buckets_without_secrets(self):
		frappe.get_doc(
			{"doctype": "Service Detail", "region": self.region, "service": "storage", "status": "Available"}
		).insert(ignore_permissions=True)
		mine = self._create()
		backup = self._create_backup_bucket()
		self._create(self.other_team)

		frappe.set_user(self.viewer)
		storage = api.get_object_storage(self.team)

		self.assertIn(self.region, [region.region for region in storage["regions"]])
		managed = {bucket.name: bucket.is_managed for bucket in storage["buckets"]}
		self.assertEqual(managed, {mine["name"]: False, backup: True})
		self.assertNotIn("secret_access_key", storage["buckets"][0])

	def test_two_teams_can_use_the_same_bucket_name(self):
		mine = self._create()
		theirs = self._create(self.other_team)

		self.assertEqual(mine["bucket_name"], f"{self._tenant_id(self.team)}-{self.region}-media")
		self.assertEqual(theirs["bucket_name"], f"{self._tenant_id(self.other_team)}-{self.region}-media")

	def test_a_customer_cannot_name_another_teams_backup_bucket(self):
		other_backup = f"team-{self._tenant_id(self.other_team)}-{self.region}-backups"

		bucket = self._create(bucket_name=other_backup)

		self.assertNotEqual(bucket["bucket_name"], other_backup)
		self.assertTrue(bucket["bucket_name"].startswith(f"{self._tenant_id(self.team)}-"))

	def test_a_bucket_needs_a_name_and_a_region(self):
		frappe.set_user(self.owner)

		for bucket_name, region in (("  ", self.region), ("media", None)):
			with self.subTest(bucket_name=bucket_name, region=region):
				with self.assertRaisesRegex(frappe.ValidationError, "needs a name and a region"):
					api.create_bucket(self.team, bucket_name, region)

		self.cargo.create_bucket.assert_not_called()

	def test_usage_is_read_from_cargo(self):
		bucket = self._create()
		frappe.set_user(self.viewer)

		usage = api.get_bucket_usage(self.team, bucket["name"])

		self.assertEqual(usage, {"used_bytes": 2048, "object_count": 3})
		self.cargo.get_usage.assert_called_once_with(bucket["bucket_name"])

	def test_a_non_member_cannot_list_buckets(self):
		self._create(self.other_team)
		frappe.set_user(self.viewer)

		with self.assertRaises(frappe.PermissionError):
			api.get_object_storage(self.other_team)

	def test_a_viewer_cannot_change_buckets(self):
		bucket = self._create()
		frappe.set_user(self.viewer)

		for call in (
			lambda: api.create_bucket(self.team, f"new-{self.suffix}", self.region),
			lambda: api.rotate_credentials(self.team, bucket["name"]),
			lambda: api.delete_bucket(self.team, bucket["name"]),
			lambda: api.set_bucket_quota(self.team, bucket["name"], 10, 0),
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_cannot_reach_another_teams_bucket(self):
		other = self._create(self.other_team)

		for call in (api.rotate_credentials, api.delete_bucket, api.get_bucket_usage):
			with self.subTest(call=call.__name__), self.assertRaises(frappe.DoesNotExistError):
				call(self.team, other["name"])

	def test_a_service_that_is_not_a_bucket_is_not_reachable(self):
		frappe.set_user("Administrator")
		service = frappe.get_doc(
			{
				"doctype": "Team Service",
				"team": self.team,
				"add_on_service": "telemetry",
				"region": self.region,
			}
		)
		service.status = "Suspended"
		service.insert(ignore_permissions=True)
		frappe.set_user(self.owner)

		with self.assertRaises(frappe.DoesNotExistError):
			api.rotate_credentials(self.team, service.name)

	def test_rotate_returns_the_new_key_once(self):
		bucket = self._create()

		rotated = api.rotate_credentials(self.team, bucket["name"])

		self.assertEqual(rotated["access_key"], "rotated")
		self.assertEqual(frappe.db.get_value("Team Service", bucket["name"], "access_key"), "rotated")

	def test_the_backup_bucket_cannot_be_rotated_or_deleted(self):
		backup = self._create_backup_bucket()

		for call in (api.rotate_credentials, api.delete_bucket, api.set_bucket_quota):
			with self.subTest(call=call.__name__):
				with self.assertRaisesRegex(frappe.ValidationError, "backup bucket"):
					call(self.team, backup)

		self.cargo.rotate_credentials.assert_not_called()
		self.cargo.delete_bucket.assert_not_called()
		self.cargo.set_quota.assert_not_called()

	def test_quota_is_set_in_cargo(self):
		bucket = self._create()

		api.set_bucket_quota(self.team, bucket["name"], 50, 1000)

		self.cargo.set_quota.assert_called_once_with(bucket["bucket_name"], 50, 1000)
