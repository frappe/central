# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

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
    """The object-storage add-on's catalog entry. Operator-provisioned in prod, so a test
    has to stand it up before a Service Backend / Managed Service can link to it."""
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
        # A fresh id per test: the row is keyed by it, and reusing one across methods
        # would bind the second method's bench to the first method's team.
        self.pilot = f"pcred-storage-{frappe.generate_hash(length=8)}"
        PilotCredential.mint(team=self.team, pilot_credential_id=self.pilot)
        # Managed Service requires a subscription link; the entitlement is what this
        # suite exercises, not what the team is billed for, so a bare one is enough.
        subscription = frappe.get_doc({"doctype": "Subscription", "team": self.team}).insert().name

        _ensure_storage_service()
        # Frappe rolls the suite back only at class teardown, so clear our own rows
        # between methods to keep the composite-unique guard from tripping on reuse.
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
        """Garage stubbed out: `existing_bucket` is what GetBucketInfo would find, so
        None means the name is free."""
        return patch.multiple(
            GarageDriver,
            get_bucket_id=lambda *args, **kwargs: existing_bucket,
            create_bucket=lambda *args, **kwargs: _BUCKET_ID,
            mint_key=lambda *args, **kwargs: _KEY,
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
        # A bench can only enable once the team has activated the service — the
        # Central-console billing gate.
        frappe.db.set_value("Managed Service", self.managed.name, "status", "Draft")
        with self._mint(), self.assertRaises(frappe.ValidationError):
            storage.enable_bench(self.pilot, _BUCKET)

    def test_config_before_enable_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            storage.bench_config(self.pilot)

    def test_a_name_another_tenant_holds_is_refused(self):
        # Garage aliases are cluster-wide. Attaching a key to a bucket Central did not
        # create for this bench would hand it someone else's objects.
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
