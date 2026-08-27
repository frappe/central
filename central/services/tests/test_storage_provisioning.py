# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.services import storage
from central.services.drivers.garage import GarageDriver
from central.tests.test_iam import ensure_user

_BUCKET_ID = "bucket-1"
_BUCKET = "acme-backups"
_KEY = {"access_key_id": "GK31c2f218a2e44f48", "secret_access_key": "b892c0665f0ada8a"}


def _ensure_storage_service():
	"""The catalog row, with the Garage handler. Set rather than skipped when it already
	exists: another suite may have left it pointing at a different handler."""
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
				"base_url": "http://garage.localhost:3903",
				"s3_endpoint": "http://garage.localhost:3900",
				"control_api_secret": "admin-token",
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

	def _mint(self, existing_bucket: str | None = None):
		"""Garage stubbed out; `existing_bucket` is what GetBucketInfo would find."""
		return patch.multiple(
			GarageDriver,
			get_bucket_id=MagicMock(return_value=existing_bucket),
			create_bucket=MagicMock(return_value=_BUCKET_ID),
			mint_key=MagicMock(return_value=_KEY),
			delete_bucket=MagicMock(),
			revoke_key=MagicMock(),
		)

	def test_create_bucket_stores_an_encrypted_credential(self):
		with self._mint():
			config = storage.create_bucket(self.team, _BUCKET)

		self.assertEqual(config["status"], "Active")
		self.assertEqual(config["bucket"], _BUCKET)
		self.assertEqual(config["endpoint_url"], "http://garage.localhost:3900")
		self.assertEqual(config["access_key_id"], _KEY["access_key_id"])
		self.assertEqual(config["secret_access_key"], _KEY["secret_access_key"])

		credential = frappe.get_doc("Service Credential", config["credential"])
		self.assertEqual(credential.subject_type, "Team")
		self.assertEqual(credential.provider_bucket_id, _BUCKET_ID)
		self.assertEqual(credential.get_password("api_key"), _KEY["secret_access_key"])

	def test_a_team_can_hold_many_buckets(self):
		with self._mint():
			first = storage.create_bucket(self.team, _BUCKET)
			second = storage.create_bucket(self.team, "acme-uploads")

		self.assertNotEqual(first["credential"], second["credential"])
		self.assertEqual(second["bucket"], "acme-uploads")

	def test_the_same_name_twice_is_refused(self):
		with self._mint():
			storage.create_bucket(self.team, _BUCKET)
			with self.assertRaisesRegex(frappe.ValidationError, "already have a bucket"):
				storage.create_bucket(self.team, _BUCKET)

	def test_a_name_another_tenant_holds_is_refused(self):
		with patch.object(GarageDriver, "get_bucket_id", return_value="someone-elses-bucket"):
			with self.assertRaisesRegex(frappe.ValidationError, "already taken"):
				GarageDriver().create_bucket(self.backend, _BUCKET)

	def test_an_invalid_bucket_name_is_refused(self):
		for name in ("ab", "Acme-Backups", "-leading", "trailing-", "under_score"):
			with self.assertRaises(frappe.ValidationError):
				storage.create_bucket(self.team, name)

	def test_creating_requires_an_active_entitlement(self):
		frappe.db.set_value("Managed Service", self.managed.name, "status", "Draft")
		with self._mint(), self.assertRaises(frappe.ValidationError):
			storage.create_bucket(self.team, _BUCKET)

	def test_revoke_targets_the_issuing_cluster_not_the_active_one(self):
		with self._mint():
			config = storage.create_bucket(self.team, _BUCKET)

		frappe.db.set_value("Service Backend", self.backend.name, "is_active", 0)
		newer = frappe.get_doc(
			{
				"doctype": "Service Backend",
				"service": "storage",
				"region": "newer-dc",
				"base_url": "http://garage-2.localhost:3903",
				"s3_endpoint": "http://garage-2.localhost:3900",
				"control_api_secret": "admin-token",
				"is_active": 1,
			}
		).insert()

		with patch.object(GarageDriver, "revoke_key") as revoke:
			result = storage.revoke_bucket(config["credential"])

		self.assertEqual(result["status"], "Revoked")
		self.assertEqual(revoke.call_args.args[0].name, self.backend.name)
		self.assertNotEqual(revoke.call_args.args[0].name, newer.name)

	def test_revoking_twice_is_a_no_op(self):
		with self._mint():
			config = storage.create_bucket(self.team, _BUCKET)
			storage.revoke_bucket(config["credential"])
			result = storage.revoke_bucket(config["credential"])

		self.assertEqual(result["status"], "Revoked")

	def test_a_bucket_this_attempt_created_is_deleted_on_failure(self):
		with (
			self._mint(),
			patch.object(GarageDriver, "mint_key", side_effect=RuntimeError("garage down")),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			self.assertRaises(RuntimeError),
		):
			storage.create_bucket(self.team, _BUCKET)

		self.assertEqual(delete_bucket.call_args.args[-1], _BUCKET_ID)
		# Garage is clean, so nothing is left to retry from.
		self.assertFalse(frappe.db.exists("Service Credential", {"managed_service": self.managed.name}))

	def test_a_clean_rollback_lets_the_next_attempt_start_fresh(self):
		with (
			self._mint(),
			patch.object(GarageDriver, "mint_key", side_effect=RuntimeError("garage down")),
			self.assertRaises(RuntimeError),
		):
			storage.create_bucket(self.team, _BUCKET)

		with self._mint():
			config = storage.create_bucket(self.team, _BUCKET)
			# A fresh create, not an adopted reservation.
			GarageDriver.create_bucket.assert_called_once()

		self.assertEqual(config["status"], "Active")

	def test_a_key_that_cannot_be_stored_is_revoked(self):
		original_save = frappe.model.document.Document.save

		def fail_on_activation(doc, *args, **kwargs):
			if doc.doctype == "Service Credential" and doc.status == "Active":
				raise RuntimeError("db gone")
			return original_save(doc, *args, **kwargs)

		with (
			self._mint(),
			patch.object(GarageDriver, "revoke_key") as revoke,
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			patch.object(frappe.model.document.Document, "save", fail_on_activation),
			self.assertRaises(RuntimeError),
		):
			storage.create_bucket(self.team, _BUCKET)

		revoke.assert_called_once()
		delete_bucket.assert_called_once()

	def test_cleanup_continues_and_preserves_the_original_error(self):
		with (
			self._mint(),
			patch.object(GarageDriver, "mint_key", side_effect=RuntimeError("garage down")),
			patch.object(GarageDriver, "revoke_key", side_effect=RuntimeError("revoke failed")),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			self.assertRaisesRegex(RuntimeError, "garage down"),
		):
			storage.create_bucket(self.team, _BUCKET)

		delete_bucket.assert_called_once()

	def test_a_row_survives_when_cleanup_could_not_finish(self):
		# The bucket is still out there, so the row is the only record of it.
		with (
			self._mint(),
			patch.object(GarageDriver, "mint_key", side_effect=RuntimeError("garage down")),
			patch.object(GarageDriver, "delete_bucket", side_effect=RuntimeError("delete failed")),
			self.assertRaises(RuntimeError),
		):
			storage.create_bucket(self.team, _BUCKET)

		stranded = frappe.get_doc("Service Credential", {"managed_service": self.managed.name})
		self.assertEqual(stranded.status, "Failed")
		self.assertEqual(stranded.provider_bucket_id, _BUCKET_ID)

	def test_enrolling_a_garage_backend_mints_its_secrets(self):
		first = self.backend.enroll()
		second = frappe.get_doc("Service Backend", self.backend.name).enroll()

		self.assertEqual(first, second)
		self.assertTrue(first["admin_token"])
		self.assertNotEqual(first["admin_token"], first["rpc_secret"])

	def test_cluster_tokens_are_minted_once_per_region(self):
		# Nodes 2 and 3 ask after node 1; identical secrets are what lets them cluster.
		frappe.db.delete("Service Backend", {"service": "storage", "region": "test-dc"})
		first = storage.mint_cluster_tokens("test-dc", "10.0.0.1")
		second = storage.mint_cluster_tokens("test-dc", "10.0.0.2")

		self.assertEqual(first, second)
		backend = frappe.get_doc("Service Backend", {"service": "storage", "region": "test-dc"})
		self.assertEqual(backend.get_password("control_api_secret"), first["admin_token"])
		self.assertEqual(backend.base_url, "http://10.0.0.1:3903")
