from datetime import UTC, datetime
from unittest.mock import Mock, patch

import frappe
from botocore.exceptions import ClientError, EndpointConnectionError
from frappe.tests import IntegrationTestCase

from central.integrations.object_storage import (
	ObjectStorageConnectionError,
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
		self.cargo.rotate_credentials.side_effect = lambda name, access_key: receipt(name, "rotated")
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
		self._create(self.other_team)

		frappe.set_user(self.viewer)
		storage = api.get_object_storage(self.team)

		self.assertIn(self.region, [region.region for region in storage["regions"]])
		self.assertEqual([bucket.name for bucket in storage["buckets"]], [mine["name"]])
		self.assertNotIn("secret_access_key", storage["buckets"][0])

	def test_two_teams_can_use_the_same_bucket_name(self):
		mine = self._create()
		theirs = self._create(self.other_team)

		self.assertEqual(mine["bucket_name"], f"{self._tenant_id(self.team)}-{self.region}-media")
		self.assertEqual(theirs["bucket_name"], f"{self._tenant_id(self.other_team)}-{self.region}-media")

	def test_a_customer_cannot_name_another_teams_bucket(self):
		other_bucket = f"{self._tenant_id(self.other_team)}-{self.region}-media"

		bucket = self._create(bucket_name=other_bucket)

		self.assertEqual(bucket["bucket_name"], f"{self._tenant_id(self.team)}-{self.region}-{other_bucket}")

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
		# Cargo replaces the key it is named, so Central names the one it holds.
		self.cargo.rotate_credentials.assert_called_once_with(bucket["bucket_name"], "access")

	def test_quota_is_set_in_cargo(self):
		bucket = self._create()

		api.set_bucket_quota(self.team, bucket["name"], 50, 1000)

		self.cargo.set_quota.assert_called_once_with(bucket["bucket_name"], 50, 1000)


class TestBucketObjects(ObjectStorageTestCase):
	def setUp(self):
		super().setUp()
		self.bucket = self._create()
		self.s3 = Mock()
		self.s3.generate_presigned_url.return_value = "https://s3.example.test/signed"
		self.boto3 = self.enterContext(patch("central.integrations.object_storage.boto3"))
		self.boto3.client.return_value = self.s3

	def test_lists_one_page_of_objects_and_folders_with_the_buckets_key(self):
		self.s3.list_objects_v2.return_value = {
			"Contents": [
				{
					"Key": "media/a.png",
					"Size": 2048,
					"LastModified": datetime(2026, 9, 30, tzinfo=UTC),
					"ETag": '"abc"',
				}
			],
			"CommonPrefixes": [{"Prefix": "media/thumbnails/"}],
			"NextContinuationToken": "page-2",
		}
		frappe.set_user(self.viewer)

		page = api.list_objects(self.team, self.bucket["name"], prefix="media/", offset="page-1", limit=50)

		self.assertEqual(
			page,
			{
				"objects": [
					{
						"key": "media/a.png",
						"size_bytes": 2048,
						"last_modified": "2026-09-30T00:00:00+00:00",
						"etag": "abc",
					}
				],
				"folders": ["media/thumbnails/"],
				"next_offset": "page-2",
			},
		)
		self.s3.list_objects_v2.assert_called_once_with(
			Bucket=self.bucket["bucket_name"],
			Prefix="media/",
			Delimiter="/",
			MaxKeys=50,
			ContinuationToken="page-1",
		)
		credentials = self.boto3.client.call_args.kwargs
		self.assertEqual(
			(
				credentials["endpoint_url"],
				credentials["aws_access_key_id"],
				credentials["aws_secret_access_key"],
				credentials["region_name"],
			),
			# Garage checks the SigV4 signature against the region Cargo installed it with.
			(ENDPOINT, "access", "secret", self.region),
		)

	def test_the_last_page_has_no_offset(self):
		self.s3.list_objects_v2.return_value = {}

		page = api.list_objects(self.team, self.bucket["name"])

		self.assertEqual(page, {"objects": [], "folders": [], "next_offset": None})
		self.assertNotIn("ContinuationToken", self.s3.list_objects_v2.call_args.kwargs)

	def test_page_size_is_capped_at_the_s3_maximum(self):
		self.s3.list_objects_v2.return_value = {}

		for limit, expected in ((5000, 1000), (0, 1)):
			with self.subTest(limit=limit):
				api.list_objects(self.team, self.bucket["name"], limit=limit)
				self.assertEqual(self.s3.list_objects_v2.call_args.kwargs["MaxKeys"], expected)

	def test_download_url_is_signed_for_an_existing_object(self):
		frappe.set_user(self.owner)

		result = api.get_object_url(self.team, self.bucket["name"], "media/a.png")

		self.assertEqual(result, {"url": "https://s3.example.test/signed"})
		self.s3.head_object.assert_called_once_with(Bucket=self.bucket["bucket_name"], Key="media/a.png")
		self.s3.generate_presigned_url.assert_called_once_with(
			"get_object",
			Params={"Bucket": self.bucket["bucket_name"], "Key": "media/a.png"},
			ExpiresIn=300,
		)

	def test_a_viewer_cannot_download_an_object(self):
		frappe.set_user(self.viewer)

		with self.assertRaises(frappe.PermissionError):
			api.get_object_url(self.team, self.bucket["name"], "media/a.png")

		self.s3.generate_presigned_url.assert_not_called()

	def test_a_missing_object_gets_no_download_url(self):
		self.s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

		with self.assertRaises(ObjectStorageNotFound):
			api.get_object_url(self.team, self.bucket["name"], "gone.png")

		self.s3.generate_presigned_url.assert_not_called()

	def test_s3_failures_map_to_object_storage_errors(self):
		cases = (
			(ClientError({"Error": {"Code": "NoSuchBucket"}}, "ListObjectsV2"), ObjectStorageNotFound),
			(ClientError({"Error": {"Code": "AccessDenied"}}, "ListObjectsV2"), ObjectStorageRejected),
			(EndpointConnectionError(endpoint_url=ENDPOINT), ObjectStorageConnectionError),
		)
		for error, expected in cases:
			with self.subTest(error=type(error).__name__):
				self.s3.list_objects_v2.side_effect = error
				with self.assertRaises(expected):
					api.list_objects(self.team, self.bucket["name"])

	def test_cannot_read_another_teams_bucket(self):
		other = self._create(self.other_team)
		frappe.set_user(self.owner)

		for call in (api.list_objects, lambda team, name: api.get_object_url(team, name, "a.png")):
			with self.assertRaises(frappe.DoesNotExistError):
				call(self.team, other["name"])

		self.boto3.client.assert_not_called()

	def test_a_non_member_cannot_list_objects(self):
		frappe.set_user(self.viewer)

		with self.assertRaises(frappe.PermissionError):
			api.list_objects(self.other_team, self.bucket["name"])
