from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.object_storage import ObjectStorageNotFound, ObjectStorageRejected
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
		client = self.enterContext(patch(f"{CONTROLLER}.ObjectStorageClient"))
		client.from_region.return_value = self.cargo
		self.subscribe = self.enterContext(
			patch(f"{CONTROLLER}.provision_service_subscription", return_value={"subscription": "sub-1"})
		)
		self.enterContext(patch(f"{CONTROLLER}.get_storage_plan", return_value="storage-plan"))
		self.enterContext(patch(f"{CONTROLLER}.get_storage_endpoint_url", return_value=ENDPOINT))
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

	def _create(self, team: str | None = None, bucket_name: str | None = None) -> dict:
		frappe.set_user(self.owner)
		return api.create_bucket(team or self.team, bucket_name or f"media-{self.suffix}", self.region)


class TestTeamServiceLifecycle(ObjectStorageTestCase):
	def test_insert_creates_the_bucket_then_bills_it(self):
		bucket = self._create()

		self.cargo.create_bucket.assert_called_once_with(f"media-{self.suffix}")
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

	def test_delete_removes_the_record_when_cargo_already_lost_the_bucket(self):
		bucket = self._create()
		self.cargo.delete_bucket.side_effect = ObjectStorageNotFound("gone")

		api.delete_bucket(self.team, bucket["name"])

		self.assertFalse(frappe.db.exists("Team Service", bucket["name"]))


class TestObjectStorageApi(ObjectStorageTestCase):
	def test_lists_regions_and_only_the_teams_buckets_without_secrets(self):
		frappe.get_doc(
			{"doctype": "Service Detail", "region": self.region, "service": "storage", "status": "Available"}
		).insert(ignore_permissions=True)
		mine = self._create()
		self._create(self.other_team, f"other-{self.suffix}")

		frappe.set_user(self.viewer)
		storage = api.get_object_storage(self.team)

		self.assertIn(self.region, [region.region for region in storage["regions"]])
		self.assertEqual([bucket.name for bucket in storage["buckets"]], [mine["name"]])
		self.assertNotIn("secret_access_key", storage["buckets"][0])

	def test_a_viewer_cannot_change_buckets(self):
		bucket = self._create()
		frappe.set_user(self.viewer)

		for call in (
			lambda: api.create_bucket(self.team, f"new-{self.suffix}", self.region),
			lambda: api.rotate_credentials(self.team, bucket["name"]),
			lambda: api.delete_bucket(self.team, bucket["name"]),
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_cannot_reach_another_teams_bucket(self):
		other = self._create(self.other_team, f"other-{self.suffix}")

		with self.assertRaises(frappe.DoesNotExistError):
			api.rotate_credentials(self.team, other["name"])

	def test_rotate_returns_the_new_key_once(self):
		bucket = self._create()

		rotated = api.rotate_credentials(self.team, bucket["name"])

		self.assertEqual(rotated["access_key"], "rotated")
		self.assertEqual(frappe.db.get_value("Team Service", bucket["name"], "access_key"), "rotated")

	def test_the_backup_bucket_cannot_be_rotated_or_deleted(self):
		backup = self._create(bucket_name=f"team-{self._tenant_id()}-{self.region}-backups")

		with self.assertRaisesRegex(frappe.ValidationError, "backup bucket"):
			api.delete_bucket(self.team, backup["name"])

		self.cargo.delete_bucket.assert_not_called()

	def _tenant_id(self) -> str:
		return frappe.db.get_value("Team", self.team, "tenant_id")
