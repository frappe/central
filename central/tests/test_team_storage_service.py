import json
from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from central.integrations.bucket_provisioning import BucketProvisioning
from central.integrations.object_storage import ObjectStorageRequestUncertain
from central.integrations.server_provisioning import _create_payload

BUCKETS = "central.integrations.bucket_provisioning"
SERVERS = "central.integrations.server_provisioning"
CONTROLLER = "central.services.doctype.team_service.team_service"
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
			patch(f"{CONTROLLER}.ObjectStorageClient") as client_class,
		):
			configuration = BucketProvisioning(provisioning_request()).get_configuration()

		self.assertEqual(configuration, STORAGE_CONFIG)
		client_class.from_region.assert_not_called()

	def test_records_a_new_bucket_for_the_requester(self):
		service = storage_service()
		service.flags = frappe._dict()

		with (
			no_lock(),
			patch(f"{BUCKETS}.frappe.db.get_value", side_effect=lookup(None)),
			patch(f"{BUCKETS}.frappe.db.commit") as commit,
			patch(f"{BUCKETS}.frappe.get_doc", return_value=service) as get_doc,
		):
			configuration = BucketProvisioning(provisioning_request()).get_configuration()

		self.assertEqual(configuration, STORAGE_CONFIG)
		get_doc.assert_called_once_with(
			{
				"doctype": "Team Service",
				"team": "TEAM-00001",
				"add_on_service": "storage",
				"region": "in-mumbai",
				"bucket_name": BUCKET,
			}
		)
		self.assertEqual(service.flags.requested_by, "Administrator")
		service.insert.assert_called_once_with(ignore_permissions=True)
		commit.assert_called_once()

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
