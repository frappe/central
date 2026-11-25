# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""A team deleting its bucket leaves a record of the subscription that billed it."""

from unittest.mock import patch

import frappe

from central.integrations.object_storage import ObjectStorageNotFound, ObjectStorageRejected
from central.services.api import storage as api
from central.services.doctype.deleted_bucket import deleted_bucket
from central.services.doctype.deleted_bucket.deleted_bucket import prune_deleted_buckets
from central.tests.test_object_storage_api import ObjectStorageTestCase


class TestDeletedBucket(ObjectStorageTestCase):
	def setUp(self):
		super().setUp()
		# Rows stay between tests of a class, so a shared subscription would never be released.
		self.subscription = f"sub-{self.suffix}"
		self.subscribe.return_value = {"subscription": self.subscription}

	def recorded(self, bucket: str) -> list:
		return frappe.get_all(
			"Deleted Bucket",
			filters={"external_id": bucket},
			fields=["external_id", "team", "subscription", "region", "deleted_at"],
		)

	def test_deleting_a_bucket_records_it_then_deletes_and_releases_as_before(self):
		bucket = self._create()
		name = frappe.db.get_value("Team Service", bucket["name"], "bucket_name")

		api.delete_bucket(self.team, bucket["name"])

		[row] = self.recorded(name)
		self.assertEqual(
			(row.external_id, row.team, row.subscription, row.region),
			(name, self.team, self.subscription, self.region),
		)
		self.assertTrue(row.deleted_at)
		self.cargo.delete_bucket.assert_called_once_with(name)
		self.end_subscription.assert_called_once_with(self.subscription)
		self.assertFalse(frappe.db.exists("Team Service", bucket["name"]))

	def test_a_bucket_cargo_already_lost_is_still_recorded(self):
		bucket = self._create()
		name = frappe.db.get_value("Team Service", bucket["name"], "bucket_name")
		self.cargo.delete_bucket.side_effect = ObjectStorageNotFound("gone")

		api.delete_bucket(self.team, bucket["name"])

		self.assertEqual(len(self.recorded(name)), 1)

	def test_a_refused_delete_records_nothing(self):
		bucket = self._create()
		name = frappe.db.get_value("Team Service", bucket["name"], "bucket_name")
		self.cargo.delete_bucket.side_effect = ObjectStorageRejected("not empty")
		frappe.db.savepoint("refused_delete")

		with self.assertRaises(ObjectStorageRejected):
			frappe.delete_doc("Team Service", bucket["name"], ignore_permissions=True)
		frappe.db.rollback(save_point="refused_delete")

		self.assertFalse(self.recorded(name))
		self.assertTrue(frappe.db.exists("Team Service", bucket["name"]))

	def test_a_bucket_without_a_subscription_records_nothing(self):
		bucket = self._create()
		name = frappe.db.get_value("Team Service", bucket["name"], "bucket_name")
		frappe.db.set_value("Team Service", bucket["name"], {"status": "Suspended", "subscription": None})

		frappe.delete_doc("Team Service", bucket["name"], ignore_permissions=True)

		self.assertFalse(self.recorded(name))

	def test_the_prune_drops_rows_older_than_a_month(self):
		for bucket, deleted_at in (
			("old-bucket", "2026-05-01 10:00:00"),
			("new-bucket", "2026-05-20 10:00:00"),
		):
			with patch("frappe.utils.now_datetime", return_value=frappe.utils.get_datetime(deleted_at)):
				deleted_bucket.record_deleted_bucket(
					frappe._dict(external_id=bucket, team=self.team, region=self.region)
				)

		prune_deleted_buckets(now="2026-06-10 10:00:00")

		self.assertFalse(self.recorded("old-bucket"))
		self.assertEqual(len(self.recorded("new-bucket")), 1)
