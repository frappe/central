import json
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
import requests

from central.integrations.object_storage import (
	ObjectStorageClient,
	ObjectStorageNotFound,
	ObjectStorageRejected,
	ObjectStorageRequestUncertain,
)


class TestObjectStorageClient(TestCase):
	def response(self, status: int, body) -> requests.Response:
		response = requests.Response()
		response.status_code = status
		response._content = json.dumps(body).encode()
		return response

	def region(self) -> Mock:
		region = Mock(cargo_base_url="https://cargo.par-2.example.test")
		region.name = "par-2"
		region.get_atlas_region_id.return_value = 7
		return region

	def client(self) -> ObjectStorageClient:
		return ObjectStorageClient(self.region())

	def test_create_bucket_uses_the_cargo_method_contract(self):
		response = Mock(status_code=200)
		response.json.return_value = {
			"message": {
				"name": "pilot-action-1",
				"region": "par-2",
				"credentials": {"access_key": "access", "secret_access_key": "secret"},
			}
		}

		with (
			patch("central.integrations.object_storage.mint_cargo_token", return_value="cargo-token"),
			patch("central.integrations.object_storage.requests.post", return_value=response) as post,
		):
			result = self.client().create_bucket("pilot-action-1")

		self.assertEqual(
			result,
			{
				"name": "pilot-action-1",
				"region": "par-2",
				"credentials": {"access_key": "access", "secret_access_key": "secret"},
			},
		)
		post.assert_called_once_with(
			"https://cargo.par-2.example.test/api/method/cargo.object_storage.api.bucket.create_bucket",
			json={"name": "pilot-action-1", "region": "par-2"},
			headers={"X-Cargo-Access-Token": "cargo-token"},
			timeout=(5, 20),
			allow_redirects=False,
		)

	def test_delete_and_rotate_use_the_named_cargo_methods(self):
		for operation, method in (
			("delete_bucket", "delete_bucket"),
			("rotate_credentials", "rotate_credentials"),
		):
			with self.subTest(operation=operation):
				response = Mock(status_code=200)
				message = {"name": "pilot-action-1", "region": "par-2"}
				if operation == "rotate_credentials":
					message["credentials"] = {"access_key": "access", "secret_access_key": "secret"}
				response.json.return_value = {"message": message}
				with (
					patch("central.integrations.object_storage.mint_cargo_token", return_value="cargo-token"),
					patch("central.integrations.object_storage.requests.post", return_value=response) as post,
				):
					result = getattr(self.client(), operation)("pilot-action-1")

				self.assertEqual(result, message)
				self.assertEqual(
					post.call_args.args[0],
					f"https://cargo.par-2.example.test/api/method/cargo.object_storage.api.bucket.{method}",
				)

	def test_from_region_reads_the_cargo_url_of_a_region_with_available_storage(self):
		with (
			patch("central.integrations.object_storage.frappe.db.exists", return_value=True) as exists,
			patch(
				"central.integrations.object_storage.frappe.get_doc", return_value=self.region()
			) as get_doc,
		):
			client = ObjectStorageClient.from_region("par-2")

		get_doc.assert_called_once_with("Region", "par-2")
		exists.assert_called_once_with(
			"Service Detail",
			{"service": "storage", "region": "par-2", "status": "Available"},
			cache=False,
		)
		self.assertEqual(client.cargo_endpoint, "https://cargo.par-2.example.test")
		self.assertEqual(client.region, "par-2")
		self.assertEqual(client.region_id, 7)

	def test_from_region_requires_available_storage(self):
		with (
			patch("central.integrations.object_storage.frappe.db.exists", return_value=False),
			patch("central.integrations.object_storage.frappe.get_doc", return_value=self.region()),
			self.assertRaisesRegex(frappe.ValidationError, "No available storage service"),
		):
			ObjectStorageClient.from_region("par-2")

	def test_lost_reply_is_uncertain_and_is_not_retried(self):
		with (
			patch("central.integrations.object_storage.mint_cargo_token", return_value="cargo-token"),
			patch("central.integrations.object_storage.requests.post", side_effect=requests.Timeout) as post,
			self.assertRaises(ObjectStorageRequestUncertain) as caught,
		):
			self.client().create_bucket("pilot-action-1")

		self.assertEqual(
			str(caught.exception),
			"Could not confirm the object storage operation. Do not retry automatically.",
		)
		self.assertEqual(post.call_count, 1)

	def test_server_error_is_an_uncertain_mutation(self):
		with (
			patch("central.integrations.object_storage.mint_cargo_token", return_value="cargo-token"),
			patch("central.integrations.object_storage.frappe.logger") as logger,
			patch(
				"central.integrations.object_storage.requests.post",
				return_value=self.response(503, {"exception": "unavailable"}),
			),
			self.assertRaises(ObjectStorageRequestUncertain) as caught,
		):
			self.client().create_bucket("pilot-action-1")

		self.assertEqual(
			str(caught.exception),
			"Could not confirm the object storage operation. Do not retry automatically.",
		)
		logger.return_value.warning.assert_called_once_with(
			"Cargo object-storage request returned HTTP %s.", 503
		)

	def test_explicit_client_error_is_a_rejection(self):
		with (
			patch("central.integrations.object_storage.mint_cargo_token", return_value="cargo-token"),
			patch("central.integrations.object_storage.frappe.logger") as logger,
			patch(
				"central.integrations.object_storage.requests.post",
				return_value=self.response(409, {"exception": "bucket exists"}),
			),
			self.assertRaises(ObjectStorageRejected) as caught,
		):
			self.client().create_bucket("pilot-action-1")

		self.assertEqual(str(caught.exception), "Object storage request was rejected.")
		logger.return_value.warning.assert_called_once_with(
			"Cargo object-storage request returned HTTP %s.", 409
		)

	def test_a_missing_bucket_is_reported_as_such(self):
		with (
			patch("central.integrations.object_storage.mint_cargo_token", return_value="cargo-token"),
			patch("central.integrations.object_storage.frappe.logger"),
			patch(
				"central.integrations.object_storage.requests.post",
				return_value=self.response(404, {"exception": "no such bucket"}),
			),
			self.assertRaises(ObjectStorageNotFound) as caught,
		):
			self.client().rotate_credentials("pilot-action-1")

		self.assertEqual(str(caught.exception), "The bucket does not exist.")

	def test_malformed_success_receipt_is_uncertain(self):
		for body in ({}, {"message": []}):
			with self.subTest(body=body):
				with (
					patch("central.integrations.object_storage.mint_cargo_token", return_value="cargo-token"),
					patch(
						"central.integrations.object_storage.requests.post",
						return_value=self.response(200, body),
					),
					self.assertRaises(ObjectStorageRequestUncertain),
				):
					self.client().create_bucket("pilot-action-1")

	def test_receipt_must_match_the_requested_bucket_and_region(self):
		for message in (
			{"name": "another-bucket", "region": "par-2", "credentials": self.credentials()},
			{"name": "pilot-action-1", "region": "another-region", "credentials": self.credentials()},
		):
			with self.subTest(message=message):
				with (
					patch("central.integrations.object_storage.mint_cargo_token", return_value="cargo-token"),
					patch(
						"central.integrations.object_storage.requests.post",
						return_value=self.response(200, {"message": message}),
					),
					self.assertRaises(ObjectStorageRequestUncertain),
				):
					self.client().create_bucket("pilot-action-1")

	def test_credential_receipts_require_non_empty_keys(self):
		for credentials in ({}, {"access_key": "access"}, {"access_key": "", "secret_access_key": "secret"}):
			with self.subTest(credentials=credentials):
				message = {"name": "pilot-action-1", "region": "par-2", "credentials": credentials}
				with (
					patch("central.integrations.object_storage.mint_cargo_token", return_value="cargo-token"),
					patch(
						"central.integrations.object_storage.requests.post",
						return_value=self.response(200, {"message": message}),
					),
					self.assertRaises(ObjectStorageRequestUncertain),
				):
					self.client().rotate_credentials("pilot-action-1")

	@staticmethod
	def credentials() -> dict:
		return {"access_key": "access", "secret_access_key": "secret"}
