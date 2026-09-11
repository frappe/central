# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.cargo_client import CargoClient
from central.services import storage
from central.tests.test_iam import ensure_user

_BUCKET = "acme-backups"
_REGION = "test-dc"
_S3 = "http://garage.localhost:3900"
_CREDENTIALS = {"access_key": "GK31c2f218a2e44f48", "secret_access_key": "b892c0665f0ada8a"}


def _ensure_storage_service():
	"""The catalog row. Set rather than skipped when it already exists: another suite may
	have left it pointing at a different handler."""
	if frappe.db.exists("Add-on Service", "storage"):
		frappe.db.set_value("Add-on Service", "storage", {"handler_key": "storage", "is_active": 1})
		return

	frappe.get_doc(
		{
			"doctype": "Add-on Service",
			"service_key": "storage",
			"title": "Object storage",
			"handler_key": "storage",
			"plan_category": "Remote Storage",
			"is_active": 1,
		}
	).insert(ignore_permissions=True)


def ensure_region(region: str) -> str:
	if not frappe.db.exists("Region", region):
		frappe.get_doc({"doctype": "Region", "region": region}).insert(ignore_permissions=True)

	return region


class TestStorageProvisioning(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		owner = ensure_user("storage.bucket.owner@example.test")
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": "Storage Bucket Team",
					"owner_user": owner,
					"members": [{"user": owner, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)
		subscription = frappe.get_doc({"doctype": "Subscription", "team": self.team}).insert().name

		_ensure_storage_service()
		ensure_region(_REGION)
		# Frappe rolls back only at class teardown; clear our own rows between methods.
		for managed in frappe.get_all(
			"Managed Service", {"team": self.team, "add_on_service": "storage"}, pluck="name"
		):
			frappe.db.delete("Service Credential", {"managed_service": managed})
		frappe.db.delete("Managed Service", {"team": self.team, "add_on_service": "storage"})
		frappe.db.delete("Service Backend", {"service": "storage"})

		self.backend = frappe.get_doc(
			{
				"doctype": "Service Backend",
				"service": "storage",
				"region": _REGION,
				"service_endpoint": _S3,
				"is_active": 1,
			}
		).insert()
		self.managed = frappe.get_doc(
			{
				"doctype": "Managed Service",
				"team": self.team,
				"add_on_service": "storage",
				"subscription": subscription,
				"status": "Active",
			}
		).insert()

	def _cargo(self):
		"""The region's Cargo host stubbed out: it owns the cluster, so nothing here talks
		to Garage."""
		return patch.multiple(
			CargoClient,
			create_bucket=MagicMock(return_value=_CREDENTIALS),
			delete_bucket=MagicMock(),
			revoke_credentials=MagicMock(),
			rotate_credentials=MagicMock(return_value=_CREDENTIALS),
		)

	def test_create_bucket_stores_an_encrypted_credential(self):
		with self._cargo():
			config = storage.create_bucket(self.team, _BUCKET)

		self.assertEqual(config["status"], "Active")
		self.assertEqual(config["bucket"], _BUCKET)
		self.assertEqual(config["endpoint_url"], _S3)
		self.assertEqual(config["access_key_id"], _CREDENTIALS["access_key"])
		self.assertEqual(config["secret_access_key"], _CREDENTIALS["secret_access_key"])

		credential = frappe.get_doc("Service Credential", config["credential"])
		self.assertEqual(credential.subject_type, "Team")
		self.assertEqual(credential.get_password("api_key"), _CREDENTIALS["secret_access_key"])

	def test_the_bucket_is_asked_of_the_backends_own_region(self):
		with self._cargo(), patch.object(CargoClient, "__init__", return_value=None) as constructed:
			storage.create_bucket(self.team, _BUCKET)

		self.assertEqual(constructed.call_args.args[0], _REGION)

	def test_a_team_can_hold_many_buckets(self):
		with self._cargo():
			first = storage.create_bucket(self.team, _BUCKET)
			second = storage.create_bucket(self.team, "acme-uploads")

		self.assertNotEqual(first["credential"], second["credential"])
		self.assertEqual(second["bucket"], "acme-uploads")

	def test_the_same_name_twice_is_refused(self):
		with self._cargo():
			storage.create_bucket(self.team, _BUCKET)
			with self.assertRaisesRegex(frappe.ValidationError, "already have a bucket"):
				storage.create_bucket(self.team, _BUCKET)

	def test_a_name_cargo_refuses_leaves_nothing(self):
		"""Whether a name is free is Cargo's answer, and it arrives as a thrown error."""
		with (
			self._cargo(),
			patch.object(CargoClient, "create_bucket", side_effect=frappe.ValidationError("already taken")),
			patch.object(CargoClient, "delete_bucket") as delete_bucket,
			self.assertRaisesRegex(frappe.ValidationError, "already taken"),
		):
			storage.create_bucket(self.team, _BUCKET)

		delete_bucket.assert_not_called()
		self.assertFalse(frappe.db.exists("Service Credential", {"managed_service": self.managed.name}))

	def test_an_invalid_bucket_name_is_refused(self):
		for name in ("ab", "Acme-Backups", "-leading", "trailing-", "under_score"):
			with self.assertRaises(frappe.ValidationError):
				storage.create_bucket(self.team, name)

	def test_creating_requires_an_active_entitlement(self):
		frappe.db.set_value("Managed Service", self.managed.name, "status", "Draft")
		with self._cargo(), self.assertRaises(frappe.ValidationError):
			storage.create_bucket(self.team, _BUCKET)

	def test_revoke_targets_the_issuing_cluster_not_the_active_one(self):
		with self._cargo():
			config = storage.create_bucket(self.team, _BUCKET)

		frappe.db.set_value("Service Backend", self.backend.name, "is_active", 0)
		frappe.get_doc(
			{
				"doctype": "Service Backend",
				"service": "storage",
				"region": ensure_region("newer-dc"),
				"service_endpoint": "http://garage-2.localhost:3900",
				"is_active": 1,
			}
		).insert()

		with (
			patch.object(CargoClient, "revoke_credentials") as revoke,
			patch.object(CargoClient, "__init__", return_value=None) as constructed,
		):
			result = storage.revoke_bucket(config["credential"])

		self.assertEqual(result["status"], "Revoked")
		self.assertEqual(constructed.call_args.args[0], _REGION)
		revoke.assert_called_once_with(_BUCKET)

	def test_revoking_twice_is_a_no_op(self):
		with self._cargo():
			config = storage.create_bucket(self.team, _BUCKET)
			storage.revoke_bucket(config["credential"])
			result = storage.revoke_bucket(config["credential"])

		self.assertEqual(result["status"], "Revoked")

	def test_a_credential_that_cannot_be_stored_takes_the_bucket_with_it(self):
		original_insert = frappe.model.document.Document.insert

		def fail_on_activation(doc, *args, **kwargs):
			if doc.doctype == "Service Credential":
				raise RuntimeError("db gone")
			return original_insert(doc, *args, **kwargs)

		with (
			self._cargo(),
			patch.object(CargoClient, "delete_bucket") as delete_bucket,
			patch.object(frappe.model.document.Document, "insert", fail_on_activation),
			self.assertRaises(RuntimeError),
		):
			storage.create_bucket(self.team, _BUCKET)

		delete_bucket.assert_called_once_with(_BUCKET)

	def test_a_failed_cleanup_does_not_mask_the_original_error(self):
		original_insert = frappe.model.document.Document.insert

		def fail_on_activation(doc, *args, **kwargs):
			if doc.doctype == "Service Credential":
				raise RuntimeError("db gone")
			return original_insert(doc, *args, **kwargs)

		with (
			self._cargo(),
			patch.object(CargoClient, "delete_bucket", side_effect=RuntimeError("cargo down")),
			patch.object(frappe.model.document.Document, "insert", fail_on_activation),
			self.assertRaisesRegex(RuntimeError, "db gone"),
		):
			storage.create_bucket(self.team, _BUCKET)

	def test_a_failure_creating_the_bucket_leaves_nothing(self):
		with (
			self._cargo(),
			patch.object(CargoClient, "create_bucket", side_effect=RuntimeError("cargo down")),
			patch.object(CargoClient, "delete_bucket") as delete_bucket,
			self.assertRaisesRegex(RuntimeError, "cargo down"),
		):
			storage.create_bucket(self.team, _BUCKET)

		# Nothing was made, so nothing is undone -- and no half-built row.
		delete_bucket.assert_not_called()
		self.assertFalse(frappe.db.exists("Service Credential", {"managed_service": self.managed.name}))

	def test_a_storage_backend_cannot_be_enrolled_from_desk(self):
		"""Cargo mints the cluster's secrets and reports them; there is nothing to exchange."""
		with self.assertRaises(frappe.ValidationError):
			self.backend.enroll()


class TestCargoClient(IntegrationTestCase):
	"""Resolving the host, which is the only part of the client that is not the wire."""

	def setUp(self):
		frappe.set_user("Administrator")
		ensure_region(_REGION)
		frappe.db.delete("Cargo Instance", {"region": _REGION})

	def _instance(self, **values) -> str:
		instance = frappe.get_doc(
			{
				"doctype": "Cargo Instance",
				"region": _REGION,
				"base_url": "http://cargo.localhost:8000",
				"status": "Registered",
				**values,
			}
		).insert(ignore_permissions=True)

		return instance.name

	def test_a_region_with_no_registered_host_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "No registered Cargo host"):
			CargoClient(_REGION).instance

	def test_a_draft_host_does_not_serve(self):
		self._instance(status="Draft")
		with self.assertRaisesRegex(frappe.ValidationError, "No registered Cargo host"):
			CargoClient(_REGION).instance

	def test_the_registered_host_carries_its_own_token(self):
		name = self._instance()
		client = CargoClient(_REGION)

		self.assertEqual(client.instance.name, name)
		self.assertTrue(client.token)
