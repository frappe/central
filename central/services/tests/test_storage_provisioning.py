# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.services import storage
from central.services.drivers.garage import GarageDriver
from central.tests.test_iam import ensure_user

_BUCKET_ID = "bucket-1"
_BUCKET = "acme-backups"
_KEY = {"access_key_id": "GK31c2f218a2e44f48", "secret_access_key": "b892c0665f0ada8a"}


def _ensure_storage_service():
	if not frappe.db.exists("Add-on Service", "storage"):
		frappe.get_doc(
			{
				"doctype": "Add-on Service",
				"service_key": "storage",
				"title": "Object Storage",
				"handler_key": "storage",
				"plan_category": "Remote Storage",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)


class TestStorageProvisioning(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		owner = ensure_user("storage.bench.owner@example.test")
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": "Storage Bench Team",
					"owner_user": owner,
					"members": [{"user": owner, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)
		self.pilot = f"pcred-storage-{frappe.generate_hash(length=8)}"
		PilotCredential.mint(team=self.team, pilot_credential_id=self.pilot)
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

	def test_enable_bench_stores_encrypted_credential(self):
		with self._mint():
			config = storage.enable_bench(self.pilot, _BUCKET)

		self.assertEqual(config["status"], "Active")
		self.assertEqual(config["bucket"], _BUCKET)
		self.assertEqual(config["endpoint_url"], "http://garage.localhost:3900")
		self.assertEqual(config["access_key_id"], _KEY["access_key_id"])
		self.assertEqual(config["secret_access_key"], _KEY["secret_access_key"])

		credential = frappe.get_doc("Service Credential", config["credential"])
		self.assertEqual(credential.subject_type, "Bench")
		self.assertEqual(credential.pilot_credential, self.pilot)
		self.assertEqual(credential.get_password("api_key"), _KEY["secret_access_key"])

	def test_enable_bench_is_idempotent(self):
		with self._mint():
			first = storage.enable_bench(self.pilot, _BUCKET)
			second = storage.enable_bench(self.pilot, _BUCKET)

		self.assertEqual(first["credential"], second["credential"])

	def test_enable_after_revoke_reuses_the_row_and_bucket(self):
		with self._mint(), patch.object(GarageDriver, "revoke_key"):
			first = storage.enable_bench(self.pilot, _BUCKET)
			storage.disable_bench(self.pilot)
			again = storage.enable_bench(self.pilot, _BUCKET)

		self.assertEqual(first["credential"], again["credential"])
		self.assertEqual(again["bucket"], first["bucket"])

	def test_disable_revokes_by_access_key_id(self):
		with self._mint():
			storage.enable_bench(self.pilot, _BUCKET)
		with patch.object(GarageDriver, "revoke_key") as revoke:
			result = storage.disable_bench(self.pilot)

		self.assertEqual(result["status"], "Revoked")
		self.assertEqual(revoke.call_args.args[-1], _KEY["access_key_id"])

	def test_disable_without_an_enable_is_a_no_op(self):
		self.assertEqual(storage.disable_bench(self.pilot)["status"], "not_enabled")

	def test_enable_requires_an_active_entitlement(self):
		frappe.db.set_value("Managed Service", self.managed.name, "status", "Draft")
		with self._mint(), self.assertRaises(frappe.ValidationError):
			storage.enable_bench(self.pilot, _BUCKET)

	def test_config_before_enable_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			storage.bench_config(self.pilot)

	def test_a_name_another_tenant_holds_is_refused(self):
		with (
			patch.object(GarageDriver, "get_bucket_id", return_value="someone-elses-bucket"),
			self.assertRaises(frappe.ValidationError),
		):
			GarageDriver().create_bucket(self.backend, _BUCKET)

	def test_an_invalid_bucket_name_is_refused(self):
		for name in ("ab", "Acme-Backups", "-leading", "trailing-", "under_score"):
			with self.assertRaises(frappe.ValidationError):
				storage.enable_bench(self.pilot, name)

	def test_a_second_bucket_name_is_refused(self):
		with self._mint():
			storage.enable_bench(self.pilot, _BUCKET)
		with self._mint(), self.assertRaisesRegex(frappe.ValidationError, "already owns the bucket"):
			storage.enable_bench(self.pilot, "other-name")

	def test_enrolling_a_garage_backend_mints_its_secrets(self):
		first = self.backend.enroll()
		second = frappe.get_doc("Service Backend", self.backend.name).enroll()

		self.assertEqual(first, second)
		self.assertEqual(
			frappe.get_doc("Service Backend", self.backend.name).get_password("rpc_secret"),
			first["rpc_secret"],
		)

	def test_a_failed_mint_leaves_a_reservation_the_retry_adopts(self):
		with self._mint(), patch.object(GarageDriver, "mint_key", side_effect=RuntimeError("garage down")):
			with self.assertRaises(RuntimeError):
				storage.enable_bench(self.pilot, _BUCKET)

		reserved = frappe.get_doc("Service Credential", {"pilot_credential": self.pilot})
		self.assertEqual(reserved.status, "Provisioning")
		self.assertEqual(reserved.label, _BUCKET)

		with self._mint(existing_bucket=_BUCKET_ID):
			config = storage.enable_bench(self.pilot, _BUCKET)
			self.assertFalse(GarageDriver.create_bucket.called)

		self.assertEqual(config["credential"], reserved.name)
		self.assertEqual(config["status"], "Active")

	def test_a_bucket_this_attempt_created_is_deleted_on_failure(self):
		with (
			self._mint(),
			patch.object(GarageDriver, "mint_key", side_effect=RuntimeError("garage down")),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			self.assertRaises(RuntimeError),
		):
			storage.enable_bench(self.pilot, _BUCKET)

		self.assertEqual(delete_bucket.call_args.args[-1], _BUCKET_ID)

	def test_an_adopted_bucket_survives_a_failed_retry(self):
		with self._mint(), patch.object(GarageDriver, "mint_key", side_effect=RuntimeError("down")):
			with self.assertRaises(RuntimeError):
				storage.enable_bench(self.pilot, _BUCKET)

		with (
			self._mint(existing_bucket=_BUCKET_ID),
			patch.object(GarageDriver, "mint_key", side_effect=RuntimeError("down")),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			self.assertRaises(RuntimeError),
		):
			storage.enable_bench(self.pilot, _BUCKET)

		delete_bucket.assert_not_called()

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
			storage.enable_bench(self.pilot, _BUCKET)

		revoke.assert_called_once()
		delete_bucket.assert_called_once()
		self.assertEqual(revoke.call_args.args[-1], _KEY["access_key_id"])

	def test_disable_revokes_at_the_issuing_cluster_not_the_active_one(self):
		with self._mint():
			storage.enable_bench(self.pilot, _BUCKET)

		# A second cluster comes up and the first goes inactive; the key still lives on
		# the one that minted it.
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
			storage.disable_bench(self.pilot)

		self.assertEqual(revoke.call_args.args[0].name, self.backend.name)
		self.assertNotEqual(revoke.call_args.args[0].name, newer.name)

	def test_cluster_tokens_are_minted_once_per_region(self):
		frappe.db.delete("Service Backend", {"service": "storage", "region": "test-dc"})
		first = storage.mint_cluster_tokens("test-dc", "10.0.0.1")
		second = storage.mint_cluster_tokens("test-dc", "10.0.0.2")

		self.assertEqual(first, second)
		self.assertTrue(first["admin_token"])
		self.assertNotEqual(first["admin_token"], first["rpc_secret"])

		backend = frappe.get_doc("Service Backend", {"service": "storage", "region": "test-dc"})
		self.assertEqual(backend.get_password("control_api_secret"), first["admin_token"])
		self.assertEqual(backend.base_url, "http://10.0.0.1:3903")
