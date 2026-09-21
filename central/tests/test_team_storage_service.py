import json
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from central.integrations.object_storage import ObjectStorageRejected, ObjectStorageRequestUncertain
from central.integrations.server_provisioning import _create_payload, _get_team_storage_service

MODULE = "central.integrations.server_provisioning"
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
	return Mock(team="TEAM-00001", atlas_instance="in-mumbai", requested_by="Administrator")


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
		image_tags={"purpose": "pilot"},
	)
	return request


def lookup(team_service):
	"""frappe.db.get_value for a team whose storage service is `team_service`."""

	def get_value(doctype, filters, fieldname=None, **kwargs):
		if doctype == "Team":
			return "TEAM-00001" if fieldname == "name" else 42
		if doctype == "Team Service":
			return team_service
		if doctype == "Plan":
			return "storage-plan"
		raise AssertionError(f"Unexpected lookup: {doctype}")

	return get_value


class TestTeamStorageService(TestCase):
	def test_reuses_active_storage_service_in_the_same_region(self):
		service = storage_service("service-1")

		with (
			patch(
				f"{MODULE}.frappe.db.get_value",
				side_effect=lookup(frappe._dict(name="service-1", status="Active")),
			) as get_value,
			patch(f"{MODULE}.frappe.get_doc", return_value=service),
			patch(f"{MODULE}.ObjectStorageClient") as client_class,
		):
			configuration = _get_team_storage_service(provisioning_request())

		self.assertEqual(configuration, STORAGE_CONFIG)
		client_class.from_region.assert_not_called()
		self.assertEqual(get_value.call_args_list[0].args, ("Team", "TEAM-00001", "name"))
		self.assertTrue(get_value.call_args_list[0].kwargs["for_update"])
		self.assertEqual(
			get_value.call_args_list[1].args,
			(
				"Team Service",
				{"team": "TEAM-00001", "add_on_service": "storage", "region": "in-mumbai"},
				["name", "status"],
			),
		)

	def test_records_the_bucket_before_it_is_created(self):
		order = []
		service = storage_service(status="Provisioning", subscription=None)
		service.insert.side_effect = lambda **kwargs: order.append("record") or service
		service.save.side_effect = lambda **kwargs: order.append("activate")

		storage_client = Mock()
		storage_client.create_bucket.side_effect = lambda name: order.append("bucket") or receipt()
		subscribe = Mock(
			side_effect=lambda *args, **kwargs: (
				order.append("subscription") or {"subscription": "subscription-1"}
			)
		)

		with (
			patch(f"{MODULE}.frappe.db.get_value", side_effect=lookup(None)),
			patch(f"{MODULE}.frappe.db.exists", return_value=True),
			patch(f"{MODULE}.frappe.db.commit") as commit,
			patch(f"{MODULE}.ObjectStorageClient") as client_class,
			patch(f"{MODULE}.ServiceDetail") as service_detail,
			patch(f"{MODULE}.provision_service_subscription", subscribe),
			patch(f"{MODULE}.frappe.get_doc", return_value=service) as get_doc,
		):
			client_class.from_region.return_value = storage_client
			service_detail.endpoint_for.return_value = ENDPOINT
			configuration = _get_team_storage_service(provisioning_request())

		self.assertEqual(configuration, STORAGE_CONFIG)
		self.assertEqual(order, ["record", "bucket", "subscription", "activate"])
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
				"status": "Provisioning",
				"bucket_name": BUCKET,
				"endpoint_url": ENDPOINT,
			}
		)
		self.assertEqual(service.status, "Active")
		self.assertEqual(service.subscription, "subscription-1")
		self.assertEqual(service.secret_access_key, "secret")
		# The record is committed before the create, and again once the service is active.
		self.assertEqual(commit.call_count, 2)

	def test_keeps_the_record_when_cargo_does_not_confirm_the_bucket(self):
		service = storage_service(status="Provisioning", subscription=None)
		storage_client = Mock()
		storage_client.create_bucket.side_effect = ObjectStorageRequestUncertain()

		with (
			patch(f"{MODULE}.frappe.db.get_value", side_effect=lookup(None)),
			patch(f"{MODULE}.frappe.db.exists", return_value=True),
			patch(f"{MODULE}.frappe.db.commit"),
			patch(f"{MODULE}.ObjectStorageClient") as client_class,
			patch(f"{MODULE}.ServiceDetail") as service_detail,
			patch(f"{MODULE}.provision_service_subscription") as subscribe,
			patch(f"{MODULE}.frappe.get_doc", return_value=service),
			self.assertRaises(ObjectStorageRequestUncertain),
		):
			client_class.from_region.return_value = storage_client
			service_detail.endpoint_for.return_value = ENDPOINT
			_get_team_storage_service(provisioning_request())

		service.delete.assert_not_called()
		subscribe.assert_not_called()

	def test_drops_the_record_when_cargo_rejects_the_bucket(self):
		service = storage_service(status="Provisioning", subscription=None)
		storage_client = Mock()
		storage_client.create_bucket.side_effect = ObjectStorageRejected("bucket exists")

		with (
			patch(f"{MODULE}.frappe.db.get_value", side_effect=lookup(None)),
			patch(f"{MODULE}.frappe.db.exists", return_value=True),
			patch(f"{MODULE}.frappe.db.commit"),
			patch(f"{MODULE}.ObjectStorageClient") as client_class,
			patch(f"{MODULE}.ServiceDetail") as service_detail,
			patch(f"{MODULE}.frappe.get_doc", return_value=service),
			self.assertRaises(ObjectStorageRejected),
		):
			client_class.from_region.return_value = storage_client
			service_detail.endpoint_for.return_value = ENDPOINT
			_get_team_storage_service(provisioning_request())

		service.delete.assert_called_once_with(ignore_permissions=True)

	def test_reconciles_an_unconfirmed_bucket_instead_of_creating_another(self):
		service = storage_service("service-1", status="Provisioning", subscription=None)
		storage_client = Mock()
		storage_client.rotate_credentials.return_value = receipt()
		subscribe = Mock(return_value={"subscription": "subscription-1"})

		with (
			patch(
				f"{MODULE}.frappe.db.get_value",
				side_effect=lookup(frappe._dict(name="service-1", status="Provisioning")),
			),
			patch(f"{MODULE}.frappe.db.commit"),
			patch(f"{MODULE}.provision_service_subscription", subscribe),
			patch(f"{MODULE}.ObjectStorageClient") as client_class,
			patch(f"{MODULE}.frappe.get_doc", return_value=service),
		):
			client_class.from_region.return_value = storage_client
			configuration = _get_team_storage_service(provisioning_request())

		self.assertEqual(configuration, STORAGE_CONFIG)
		storage_client.rotate_credentials.assert_called_once_with(BUCKET)
		storage_client.create_bucket.assert_not_called()
		self.assertEqual(service.status, "Active")

	def test_reconciliation_provisions_again_when_the_bucket_does_not_exist(self):
		unconfirmed = storage_service("service-1", status="Provisioning", subscription=None)
		fresh = storage_service("service-2", status="Provisioning", subscription=None)
		storage_client = Mock()
		storage_client.rotate_credentials.side_effect = ObjectStorageRejected("no such bucket")
		storage_client.create_bucket.return_value = receipt()

		with (
			patch(
				f"{MODULE}.frappe.db.get_value",
				side_effect=lookup(frappe._dict(name="service-1", status="Provisioning")),
			),
			patch(f"{MODULE}.frappe.db.exists", return_value=True),
			patch(f"{MODULE}.frappe.db.commit"),
			patch(f"{MODULE}.ObjectStorageClient") as client_class,
			patch(f"{MODULE}.ServiceDetail") as service_detail,
			patch(f"{MODULE}.provision_service_subscription", return_value={"subscription": "sub-1"}),
			patch(f"{MODULE}.frappe.get_doc", side_effect=[unconfirmed, fresh]),
		):
			client_class.from_region.return_value = storage_client
			service_detail.endpoint_for.return_value = ENDPOINT
			configuration = _get_team_storage_service(provisioning_request())

		self.assertEqual(configuration, STORAGE_CONFIG)
		unconfirmed.delete.assert_called_once_with(ignore_permissions=True)
		storage_client.create_bucket.assert_called_once_with(BUCKET)

	def test_refuses_a_suspended_storage_service(self):
		with (
			patch(
				f"{MODULE}.frappe.db.get_value",
				side_effect=lookup(frappe._dict(name="service-1", status="Suspended")),
			),
			self.assertRaisesRegex(frappe.ValidationError, "suspended"),
		):
			_get_team_storage_service(provisioning_request())

	def test_pilot_payload_contains_the_team_storage_configuration(self):
		request = pilot_request()

		with (
			patch(f"{MODULE}.PilotCredential.mint", return_value="token"),
			patch(f"{MODULE}.central_url", return_value="https://central.test"),
			patch(f"{MODULE}.jwks_url", return_value="https://central.test/jwks"),
			patch(f"{MODULE}._get_team_storage_service", return_value=STORAGE_CONFIG),
		):
			payload = _create_payload(request)

		metadata = json.loads(payload["metadata"]["pilot-central"])
		self.assertEqual(metadata["s3"], STORAGE_CONFIG)

	def test_storage_failure_does_not_block_pilot_creation(self):
		request = pilot_request()

		with (
			patch(f"{MODULE}.PilotCredential.mint", return_value="token"),
			patch(f"{MODULE}.central_url", return_value="https://central.test"),
			patch(f"{MODULE}.jwks_url", return_value="https://central.test/jwks"),
			patch(
				f"{MODULE}._get_team_storage_service",
				side_effect=ObjectStorageRequestUncertain(),
			),
			patch(f"{MODULE}.frappe.log_error") as log_error,
		):
			payload = _create_payload(request)

		metadata = json.loads(payload["metadata"]["pilot-central"])
		self.assertNotIn("s3", metadata)
		log_error.assert_called_once()
