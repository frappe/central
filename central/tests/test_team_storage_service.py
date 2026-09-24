import json
from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from central.integrations.bucket_provisioning import BucketProvisioning
from central.integrations.object_storage import ObjectStorageRejected, ObjectStorageRequestUncertain
from central.integrations.server_provisioning import _create_payload

BUCKETS = "central.integrations.bucket_provisioning"
SERVERS = "central.integrations.server_provisioning"
BUCKET = "team-42-in-mumbai-backups"
ENDPOINT = "https://s3.in-mumbai.example.test"
STORAGE_CONFIG = {
	"access_key": "access",
	"secret_key": "secret",
	"bucket": BUCKET,
	"provider": "garage",
	"region": "in-mumbai",
	"endpoint_url": ENDPOINT,
}


def storage_service(name="team-service-1", status="Active", subscription="subscription-1"):
	service = Mock(
		access_key="access",
		bucket_name=BUCKET,
		endpoint_url=ENDPOINT,
		region="in-mumbai",
		status=status,
		subscription=subscription,
		team="TEAM-00001",
	)
	service.name = name
	service.get_password.return_value = "secret"
	service.insert.return_value = service
	return service


def receipt():
	return {
		"name": BUCKET,
		"region": "in-mumbai",
		"credentials": {"access_key": "access", "secret_access_key": "secret"},
	}


def provisioning_request():
	return Mock(team="TEAM-00001", region="in-mumbai", requested_by="Administrator")


def pilot_request():
	request = Mock(team="TEAM-00001")
	request.name = "action-1"
	request.get_configuration.return_value = Mock(
		image_id="image-1",
		virtual_cpu_count=2,
		memory_mib=4096,
		disk_mib=10240,
		hostname="pilot-1",
		ssh_keys=[],
		ssh_key_ids=[],
		image_tags={"purpose": "pilot"},
	)
	return request


def lookup(team_service):
	"""frappe.db.get_value for a team whose storage service is `team_service`."""

	def get_value(doctype, filters, fieldname=None, **kwargs):
		if doctype == "Team":
			return 42
		if doctype == "Team Service":
			return team_service
		if doctype == "Plan":
			return "storage-plan"
		raise AssertionError(f"Unexpected lookup: {doctype}")

	return get_value


@contextmanager
def no_lock(recorder=None):
	"""The file lock, held by nobody, so a test exercises the work it guards."""

	@contextmanager
	def acquire(lock_name, **kwargs):
		if recorder is not None:
			recorder.append((lock_name, kwargs))
		yield

	with patch(f"{BUCKETS}.filelock", acquire):
		yield


class TestBucketProvisioning(TestCase):
	def test_reuses_the_active_bucket_without_asking_cargo(self):
		service = storage_service()

		with (
			no_lock(),
			patch(f"{BUCKETS}.frappe.db.get_value", side_effect=lookup("service-1")),
			patch(f"{BUCKETS}.frappe.get_doc", return_value=service),
			patch(f"{BUCKETS}.ObjectStorageClient") as client_class,
		):
			configuration = BucketProvisioning(provisioning_request()).get_configuration()

		self.assertEqual(configuration, STORAGE_CONFIG)
		client_class.from_region.assert_not_called()

	def test_creates_the_bucket_before_the_record(self):
		order = []
		service = storage_service()
		service.insert.side_effect = lambda **kwargs: order.append("record") or service

		storage_client = Mock()
		storage_client.create_bucket.side_effect = lambda name: order.append("bucket") or receipt()
		subscribe = Mock(
			side_effect=lambda *args, **kwargs: (
				order.append("subscription") or {"subscription": "subscription-1"}
			)
		)

		with (
			no_lock(),
			patch(f"{BUCKETS}.frappe.db.get_value", side_effect=lookup(None)),
			patch(f"{BUCKETS}.frappe.db.commit") as commit,
			patch(f"{BUCKETS}.ObjectStorageClient") as client_class,
			patch(f"{BUCKETS}.ServiceDetail") as service_detail,
			patch(f"{BUCKETS}.provision_service_subscription", subscribe),
			patch(f"{BUCKETS}.frappe.get_doc", return_value=service) as get_doc,
		):
			client_class.from_region.return_value = storage_client
			service_detail.endpoint_for.return_value = ENDPOINT
			configuration = BucketProvisioning(provisioning_request()).get_configuration()

		self.assertEqual(configuration, STORAGE_CONFIG)
		self.assertEqual(order, ["bucket", "subscription", "record"])
		storage_client.create_bucket.assert_called_once_with(BUCKET)
		subscribe.assert_called_once_with(
			"TEAM-00001", "storage-plan", cluster="in-mumbai", changed_by="Administrator"
		)
		get_doc.assert_called_once_with(
			{
				"doctype": "Team Service",
				"team": "TEAM-00001",
				"add_on_service": "storage",
				"region": "in-mumbai",
				"status": "Active",
				"subscription": "subscription-1",
				"bucket_name": BUCKET,
				"endpoint_url": ENDPOINT,
				"access_key": "access",
				"secret_access_key": "secret",
			}
		)
		commit.assert_called_once()

	def test_never_rotates_the_key_of_a_bucket_cargo_already_holds(self):
		"""One key opens a bucket, so rotating it would cut off every server in this team
		and region already backing up. A taken name is left for an operator instead."""
		storage_client = Mock()
		storage_client.create_bucket.side_effect = ObjectStorageRejected("bucket name taken")

		with (
			no_lock(),
			patch(f"{BUCKETS}.frappe.db.get_value", side_effect=lookup(None)),
			patch(f"{BUCKETS}.ObjectStorageClient") as client_class,
			patch(f"{BUCKETS}.provision_service_subscription") as subscribe,
			patch(f"{BUCKETS}.frappe.get_doc") as get_doc,
			self.assertRaises(ObjectStorageRejected),
		):
			client_class.from_region.return_value = storage_client
			BucketProvisioning(provisioning_request()).get_configuration()

		storage_client.rotate_credentials.assert_not_called()
		subscribe.assert_not_called()
		get_doc.assert_not_called()

	def test_records_nothing_when_cargo_never_answers(self):
		storage_client = Mock()
		storage_client.create_bucket.side_effect = ObjectStorageRequestUncertain()

		with (
			no_lock(),
			patch(f"{BUCKETS}.frappe.db.get_value", side_effect=lookup(None)),
			patch(f"{BUCKETS}.ObjectStorageClient") as client_class,
			patch(f"{BUCKETS}.ServiceDetail") as service_detail,
			patch(f"{BUCKETS}.provision_service_subscription") as subscribe,
			patch(f"{BUCKETS}.frappe.get_doc") as get_doc,
			self.assertRaises(ObjectStorageRequestUncertain),
		):
			client_class.from_region.return_value = storage_client
			service_detail.endpoint_for.return_value = ENDPOINT
			BucketProvisioning(provisioning_request()).get_configuration()

		subscribe.assert_not_called()
		get_doc.assert_not_called()

	def test_refuses_a_suspended_service(self):
		with (
			no_lock(),
			patch(f"{BUCKETS}.frappe.db.get_value", side_effect=lookup("service-1")),
			patch(f"{BUCKETS}.frappe.get_doc", return_value=storage_service(status="Suspended")),
			self.assertRaisesRegex(frappe.ValidationError, "suspended"),
		):
			BucketProvisioning(provisioning_request()).get_configuration()

	def test_holds_one_lock_named_for_the_bucket(self):
		held = []

		with (
			no_lock(held),
			patch(f"{BUCKETS}.frappe.db.get_value", side_effect=lookup("service-1")),
			patch(f"{BUCKETS}.frappe.get_doc", return_value=storage_service()),
		):
			BucketProvisioning(provisioning_request()).get_configuration()

		self.assertEqual(held, [(f"team-storage-{BUCKET}", {"timeout": 60})])


class TestPilotStoragePayload(TestCase):
	def test_pilot_payload_contains_the_team_storage_configuration(self):
		provisioning = Mock()
		provisioning.get_configuration.return_value = STORAGE_CONFIG

		with (
			patch(f"{SERVERS}.PilotCredential.mint", return_value="token"),
			patch(f"{SERVERS}.central_url", return_value="https://central.test"),
			patch(f"{SERVERS}.jwks_url", return_value="https://central.test/jwks"),
			patch(f"{SERVERS}.BucketProvisioning", return_value=provisioning),
		):
			payload = _create_payload(pilot_request())

		metadata = json.loads(payload["metadata"]["pilot-central"])
		self.assertEqual(metadata["s3"], STORAGE_CONFIG)

	def test_storage_failure_does_not_block_pilot_creation(self):
		request = pilot_request()
		with (
			patch(f"{SERVERS}.PilotCredential.mint", return_value="token"),
			patch(f"{SERVERS}.central_url", return_value="https://central.test"),
			patch(f"{SERVERS}.jwks_url", return_value="https://central.test/jwks"),
			patch(f"{SERVERS}.BucketProvisioning", side_effect=ObjectStorageRequestUncertain()),
		):
			payload = _create_payload(request)

		metadata = json.loads(payload["metadata"]["pilot-central"])
		self.assertNotIn("s3", metadata)
		request.record_diagnostic.assert_called_once()
