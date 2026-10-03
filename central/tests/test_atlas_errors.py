import json
from unittest.mock import Mock, patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.errors import (
	AtlasConnectionError,
	AtlasRejected,
	AtlasRequestUncertain,
	AtlasResourceGone,
	to_error_response,
)
from central.integrations.atlas import AtlasClient


class TestAtlasErrors(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.client = AtlasClient(Mock(), 0)

	def response(self, status, body):
		response = requests.Response()
		response.status_code = status
		response._content = json.dumps(body).encode()
		return response

	def test_mutation_server_error_is_uncertain_not_retriable(self):
		with self.assertRaises(AtlasRequestUncertain) as caught:
			self.client._read_response(self.response(503, {}), "POST")
		self.assertEqual(to_error_response(caught.exception)["code"], "OUTCOME_UNKNOWN")
		self.assertFalse(to_error_response(caught.exception)["retriable"])

	def test_successful_mutation_with_bad_receipt_is_uncertain(self):
		for body in ([], "not an object"):
			with self.subTest(body=body), self.assertRaises(AtlasRequestUncertain):
				self.client._read_response(self.response(201, body), "POST")
		response = self.response(201, {})
		response._content = b"not JSON"
		with self.assertRaises(AtlasRequestUncertain):
			self.client._read_response(response, "POST")

	def test_explicit_rejection_hides_regional_detail(self):
		with self.assertRaises(AtlasRejected) as caught:
			self.client._read_response(
				self.response(409, {"error": {"message": "No host has capacity."}}), "POST"
			)
		self.assertNotIn("host", to_error_response(caught.exception)["message"])

	def test_capacity_503_is_a_definite_refusal(self):
		"""A 503 that names why (out_of_capacity) is Atlas refusing the shape, not an
		uncertain outcome."""
		with self.assertRaises(AtlasRejected) as caught:
			self.client._read_response(
				self.response(
					503, {"error": {"code": "out_of_capacity", "message": "No host has capacity."}}
				),
				"POST",
			)
		self.assertEqual(to_error_response(caught.exception)["code"], "ATLAS_REJECTED")
		self.assertNotIn("host", to_error_response(caught.exception)["message"])

	def test_read_failure_does_not_claim_mutation_acceptance(self):
		with self.assertRaises(AtlasConnectionError) as caught:
			self.client._read_response(self.response(503, {}))
		self.assertNotIsInstance(caught.exception, AtlasRequestUncertain)

	def test_not_found_has_a_specific_outcome(self):
		with self.assertRaises(AtlasResourceGone):
			self.client._read_response(self.response(404, {}))

	def test_lost_mutation_reply_never_retries(self):
		with (
			patch.object(self.client, "_configuration", return_value=("https://atlas.example.test", 1)),
			patch("central.integrations.atlas.mint_atlas_token", return_value="test-token"),
			patch("central.integrations.atlas.requests.request", side_effect=requests.Timeout) as request,
		):
			with self.assertRaises(AtlasRequestUncertain):
				self.client.create_vm({"image_id": "pilot"})
		request.assert_called_once()

	def test_metadata_the_host_would_refuse_is_never_sent(self):
		"""Metal refuses it only after Atlas saved a draft machine, so Central stops it first."""
		oversized = {
			"too many entries": {f"key-{index}": "value" for index in range(65)},
			"key too long": {"k" * 129: "value"},
			"value too long": {"pilot-central": "v" * 1025},
		}
		for case, metadata in oversized.items():
			with (
				self.subTest(case=case),
				patch("central.integrations.atlas.requests.request") as request,
				self.assertRaises(frappe.ValidationError),
			):
				self.client.create_vm({"image_id": "pilot", "metadata": metadata})
			request.assert_not_called()

	def test_metadata_at_the_limits_is_sent(self):
		metadata = {f"key-{index}": "value" for index in range(63)} | {"k" * 128: "v" * 1024}
		with (
			patch.object(self.client, "_configuration", return_value=("https://atlas.example.test", 1)),
			patch("central.integrations.atlas.mint_atlas_token", return_value="test-token"),
			patch(
				"central.integrations.atlas.requests.request", return_value=self.response(202, {})
			) as request,
		):
			self.client.create_vm({"image_id": "pilot", "metadata": metadata})
		request.assert_called_once()

	def test_unknown_error_does_not_claim_nothing_changed(self):
		with patch("central.errors.frappe.log_error"):
			error = to_error_response(RuntimeError("private internal detail"))
		self.assertNotIn("nothing was changed", error["message"])
		self.assertNotIn("private", error["message"])
		self.assertFalse(error["retriable"])
