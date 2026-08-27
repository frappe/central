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
			attach_alias=MagicMock(),
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
		# Refused before anything is created: the alias already resolves elsewhere.
		with self._mint(existing_bucket="someone-elses-bucket"):
			with self.assertRaisesRegex(frappe.ValidationError, "already taken"):
				storage.create_bucket(self.team, _BUCKET)
			GarageDriver.create_bucket.assert_not_called()

	def test_a_name_lost_to_a_concurrent_request_is_refused_cleanly(self):
		# Both callers passed the availability check; Garage arbitrates at attach time.
		conflict = MagicMock(ok=False, status_code=400)
		conflict.text = '{"message": "Bad request: Alias acme-backups already exists and points to different bucket: 578bd02af7bc"}'

		# attach_alias stays real — it is the code under test; only the wire is faked.
		with (
			patch.object(GarageDriver, "get_bucket_id", return_value=None),
			patch.object(GarageDriver, "create_bucket", return_value=_BUCKET_ID),
			patch.object(GarageDriver, "mint_key", return_value=_KEY),
			patch.object(GarageDriver, "_request", return_value=conflict),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			self.assertRaisesRegex(frappe.ValidationError, "already taken"),
		):
			storage.create_bucket(self.team, _BUCKET)

		# The loser's bucket goes with it, and Garage's raw text never reaches the user.
		delete_bucket.assert_called_once()
		self.assertFalse(frappe.db.exists("Service Credential", {"managed_service": self.managed.name}))

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

	def test_the_name_goes_on_only_once_the_bucket_is_usable(self):
		with self._mint():
			storage.create_bucket(self.team, _BUCKET)

			# Created unnamed, then keyed, then named: an abandoned attempt holds no name.
			GarageDriver.create_bucket.assert_called_once()
			self.assertNotIn(_BUCKET, GarageDriver.create_bucket.call_args.args)
			self.assertEqual(GarageDriver.attach_alias.call_args.args[-1], _BUCKET)

	def test_a_failed_cleanup_does_not_mask_the_original_error(self):
		with (
			self._mint(),
			patch.object(GarageDriver, "mint_key", side_effect=RuntimeError("garage down")),
			patch.object(GarageDriver, "delete_bucket", side_effect=RuntimeError("delete failed")),
			self.assertRaisesRegex(RuntimeError, "garage down"),
		):
			storage.create_bucket(self.team, _BUCKET)

	def test_the_row_is_provisioning_until_the_name_is_on(self):
		seen = {}
		with (
			self._mint(),
			patch.object(
				GarageDriver,
				"attach_alias",
				side_effect=lambda backend, bucket_id, alias: seen.update(
					status_while_naming=frappe.db.get_value(
						"Service Credential", {"provider_bucket_id": bucket_id}, "status"
					)
				),
			),
		):
			config = storage.create_bucket(self.team, _BUCKET)

		# Written down before the name goes on, and only usable once it has.
		self.assertEqual(seen["status_while_naming"], "Provisioning")
		self.assertEqual(config["status"], "Active")
		self.assertEqual(frappe.db.get_value("Service Credential", config["credential"], "status"), "Active")

	def test_the_record_is_stored_before_the_name_is_attached(self):
		order = []
		with (
			self._mint(),
			patch.object(GarageDriver, "attach_alias", side_effect=lambda *a, **k: order.append("alias")),
			patch.object(
				frappe.model.document.Document,
				"insert",
				autospec=True,
				side_effect=lambda doc, *a, **k: order.append(f"insert {doc.doctype}"),
			),
		):
			storage.create_bucket(self.team, _BUCKET)

		# A name can only sit on a bucket Central has already written down.
		self.assertEqual(order, ["insert Service Credential", "alias"])

	def test_a_bucket_named_after_the_record_lands_rolls_both_back(self):
		with (
			self._mint(),
			patch.object(GarageDriver, "attach_alias", side_effect=RuntimeError("alias lost")),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			self.assertRaises(RuntimeError),
		):
			storage.create_bucket(self.team, _BUCKET)

		# The row was committed by then, so it goes too: a record naming a deleted
		# bucket is worse than no record.
		delete_bucket.assert_called_once()
		self.assertFalse(frappe.db.exists("Service Credential", {"managed_service": self.managed.name}))

	def test_a_credential_that_cannot_be_stored_takes_the_bucket_with_it(self):
		original_insert = frappe.model.document.Document.insert

		def fail_on_activation(doc, *args, **kwargs):
			if doc.doctype == "Service Credential":
				raise RuntimeError("db gone")
			return original_insert(doc, *args, **kwargs)

		with (
			self._mint(),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			patch.object(frappe.model.document.Document, "insert", fail_on_activation),
			self.assertRaises(RuntimeError),
		):
			storage.create_bucket(self.team, _BUCKET)

		delete_bucket.assert_called_once()

	# ── Failure at each stage ──────────────────────────────────────────────────────

	def test_a_failure_creating_the_bucket_leaves_nothing(self):
		with (
			self._mint(),
			patch.object(GarageDriver, "create_bucket", side_effect=RuntimeError("garage down")),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			self.assertRaisesRegex(RuntimeError, "garage down"),
		):
			storage.create_bucket(self.team, _BUCKET)

		# Nothing was made, so nothing is undone — and no half-built row.
		delete_bucket.assert_not_called()
		self.assertFalse(frappe.db.exists("Service Credential", {"managed_service": self.managed.name}))

	def test_a_failure_minting_the_key_takes_the_bucket(self):
		with (
			self._mint(),
			patch.object(GarageDriver, "mint_key", side_effect=RuntimeError("garage down")),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			self.assertRaisesRegex(RuntimeError, "garage down"),
		):
			storage.create_bucket(self.team, _BUCKET)

		self.assertEqual(delete_bucket.call_args.args[-1], _BUCKET_ID)
		self.assertFalse(frappe.db.exists("Service Credential", {"managed_service": self.managed.name}))

	def test_a_failure_flipping_to_active_rolls_everything_back(self):
		original_db_set = frappe.model.document.Document.db_set

		def fail_on_activation(doc, fieldname, value=None, *args, **kwargs):
			if doc.doctype == "Service Credential" and fieldname == "status":
				raise RuntimeError("db gone")
			return original_db_set(doc, fieldname, value, *args, **kwargs)

		with (
			self._mint(),
			patch.object(frappe.model.document.Document, "db_set", fail_on_activation),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
			self.assertRaisesRegex(RuntimeError, "db gone"),
		):
			storage.create_bucket(self.team, _BUCKET)

		# The bucket was named by then, so it must not be left behind wearing the name.
		delete_bucket.assert_called_once()
		self.assertFalse(frappe.db.exists("Service Credential", {"managed_service": self.managed.name}))

	# ── The sweeper ───────────────────────────────────────────────────────────────

	def _stale_provisioning_row(self, bucket: str = _BUCKET) -> str:
		credential = storage.create_service_credential(self.team, bucket, self.backend)
		credential.update({"provider_bucket_id": _BUCKET_ID, "provider_ref": "GKstale"}).insert()
		frappe.db.set_value(
			"Service Credential",
			credential.name,
			"modified",
			frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-30),
			update_modified=False,
		)
		return credential.name

	def test_the_sweeper_clears_a_stale_half_made_bucket(self):
		name = self._stale_provisioning_row()

		with (
			patch.object(GarageDriver, "revoke_key") as revoke_key,
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
		):
			swept = storage.sweep_stale_provisioning()

		self.assertEqual(swept, 1)
		# The key first: deleting a bucket does not revoke keys, and a key outliving its
		# row could never be found again.
		self.assertEqual(revoke_key.call_args.args[-1], "GKstale")
		self.assertEqual(delete_bucket.call_args.args[-1], _BUCKET_ID)
		self.assertFalse(frappe.db.exists("Service Credential", name))

	def test_the_sweeper_keeps_a_row_whose_key_it_could_not_revoke(self):
		name = self._stale_provisioning_row()

		with (
			patch.object(GarageDriver, "revoke_key", side_effect=RuntimeError("garage down")),
			patch.object(GarageDriver, "delete_bucket") as delete_bucket,
		):
			self.assertEqual(storage.sweep_stale_provisioning(), 0)

		# The bucket stays too: the row is the only handle on both.
		delete_bucket.assert_not_called()
		self.assertTrue(frappe.db.exists("Service Credential", name))

	def test_the_sweeper_leaves_a_provision_still_in_flight_alone(self):
		credential = storage.create_service_credential(self.team, _BUCKET, self.backend)
		credential.update({"provider_bucket_id": _BUCKET_ID}).insert()

		with patch.object(GarageDriver, "delete_bucket") as delete_bucket:
			self.assertEqual(storage.sweep_stale_provisioning(), 0)

		delete_bucket.assert_not_called()
		self.assertTrue(frappe.db.exists("Service Credential", credential.name))

	def test_the_sweeper_never_touches_a_live_bucket(self):
		with self._mint():
			config = storage.create_bucket(self.team, _BUCKET)
		frappe.db.set_value(
			"Service Credential",
			config["credential"],
			"modified",
			frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-120),
			update_modified=False,
		)

		with patch.object(GarageDriver, "delete_bucket") as delete_bucket:
			self.assertEqual(storage.sweep_stale_provisioning(), 0)

		delete_bucket.assert_not_called()
		self.assertTrue(frappe.db.exists("Service Credential", config["credential"]))

	def test_the_sweeper_keeps_a_row_whose_bucket_it_could_not_delete(self):
		name = self._stale_provisioning_row()

		with patch.object(GarageDriver, "delete_bucket", side_effect=RuntimeError("garage down")):
			self.assertEqual(storage.sweep_stale_provisioning(), 0)

		# Still the only record of that bucket, so the next run can try again.
		self.assertTrue(frappe.db.exists("Service Credential", name))

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
