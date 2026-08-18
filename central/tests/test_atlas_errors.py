"""Atlas failures must reach the caller as Atlas's own sentence, not a raw traceback.

`FrappeClient` raises `FrappeException` carrying the ENTIRE remote traceback as one
string, so before `AtlasClient._post` an Atlas-side `frappe.throw` ("region full",
"image not on any host") surfaced in the console as "FrappeException" over a wall of
Atlas internals — the actionable sentence buried in the last line.
"""

from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.frappeclient import FrappeException
from frappe.tests import IntegrationTestCase

from central.integrations.atlas import (
	AtlasClient,
	AtlasError,
	AtlasResourceGone,
	_remote_error_message,
)

# A verbatim capture of what FrappeClient raised for a create that hit a full region.
CONSOLIDATION_TRACEBACK = """FrappeClient Request Failed

Traceback (most recent call last):
  File "apps/frappe/frappe/app.py", line 121, in application
    response = frappe.api.handle(request)
  File "apps/atlas/atlas/atlas/api/provision.py", line 97, in create_vm
    pilot.insert(ignore_permissions=True)
  File "apps/atlas/atlas/atlas/placement.py", line 452, in _raise_no_capacity
    frappe.throw(
  File "apps/frappe/frappe/utils/messages.py", line 59, in _raise_exception
    raise exc
atlas.atlas.placement.ConsolidationInProgressError: Capacity is being freed by \
migrating small VMs — retry shortly."""


class TestRemoteErrorMessage(IntegrationTestCase):
	def test_lifts_the_message_off_the_last_traceback_line(self):
		self.assertEqual(
			_remote_error_message(FrappeException(CONSOLIDATION_TRACEBACK)),
			"Capacity is being freed by migrating small VMs — retry shortly.",
		)

	def test_handles_a_bare_exception_line(self):
		self.assertEqual(
			_remote_error_message(FrappeException("atlas.placement.NoCapacityError: Region full.")),
			"Region full.",
		)

	def test_returns_none_when_there_is_no_remote_traceback(self):
		# A connection error carries no "ExcType: message" line, so there is nothing
		# truthful to show — the caller falls back to its own wording.
		self.assertIsNone(_remote_error_message(FrappeException("")))
		self.assertIsNone(_remote_error_message(FrappeException("connection aborted")))


class TestAtlasClientPost(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.client = AtlasClient(
			frappe._dict(region="blr-err", status="Active", tunnel_status=None, tunnel_url=None)
		)

	def test_remote_throw_becomes_atlas_error_with_only_the_message(self):
		with patch.object(AtlasClient, "client") as client, patch.object(frappe, "log_error"):
			client.return_value.post_api.side_effect = FrappeException(CONSOLIDATION_TRACEBACK)
			with self.assertRaises(AtlasError) as caught:
				self.client._post("atlas.api.provision.create_vm", {}, action="create this server")
		rendered = str(caught.exception)
		self.assertIn("retry shortly", rendered)
		# The tenant must never see Atlas's frames or file paths.
		self.assertNotIn("Traceback", rendered)
		self.assertNotIn("apps/atlas", rendered)
		self.assertNotIn("FrappeClient Request Failed", rendered)

	def test_unreachable_atlas_falls_back_to_a_generic_message(self):
		with patch.object(AtlasClient, "client") as client, patch.object(frappe, "log_error"):
			client.return_value.post_api.side_effect = FrappeException("connection aborted")
			with self.assertRaises(AtlasError) as caught:
				self.client._post("atlas.api.provision.create_vm", {}, action="create this server")
		self.assertIn("create this server", str(caught.exception))

	def test_the_full_traceback_still_reaches_the_error_log(self):
		with patch.object(AtlasClient, "client") as client, patch.object(frappe, "log_error") as log_error:
			client.return_value.post_api.side_effect = FrappeException(CONSOLIDATION_TRACEBACK)
			with self.assertRaises(AtlasError):
				self.client._post("atlas.api.provision.create_vm", {}, action="create this server")
		self.assertTrue(log_error.called)
		self.assertIn("apps/atlas", log_error.call_args.kwargs["message"])

	def test_a_successful_post_is_returned_unchanged(self):
		with patch.object(AtlasClient, "client") as client:
			client.return_value.post_api.return_value = {"name": "vm-1"}
			self.assertEqual(
				self.client._post("atlas.api.provision.create_vm", {}, action="create this server"),
				{"name": "vm-1"},
			)


class TestRunDocMethod(IntegrationTestCase):
	"""The lifecycle path reads the real HTTP status, so a missing doc (404) is told apart
	from an unreachable region — the fix for terminate mislabelling a gone resource."""

	def _client(self):
		instance = frappe._dict(
			region="blr-rdm",
			status="Active",
			tunnel_status=None,
			tunnel_url=None,
			base_url="https://atlas.example.test",
			api_key="k",
		)
		instance.get_password = lambda field, *a, **k: "s"
		return AtlasClient(instance)

	def test_404_raises_resource_gone(self):
		response = MagicMock(ok=False, status_code=404, text="{}")
		with patch("central.integrations.atlas.requests.post", return_value=response):
			with self.assertRaises(AtlasResourceGone):
				self._client()._run_doc_method("Site", "x", "terminate", None, action="terminate this site")

	def test_connection_error_reads_as_region_unavailable(self):
		with patch("central.integrations.atlas.requests.post", side_effect=requests.ConnectionError()):
			with self.assertRaises(AtlasError) as caught:
				self._client()._run_doc_method("Site", "x", "terminate", None, action="terminate this site")
		self.assertNotIsInstance(caught.exception, AtlasResourceGone)
		self.assertIn("terminate this site", str(caught.exception))

	def test_remote_sentence_surfaces_on_other_error(self):
		body = {"_server_messages": frappe.as_json([frappe.as_json({"message": "No capacity here."})])}
		response = MagicMock(ok=False, status_code=417, text=frappe.as_json(body))
		response.json.return_value = body
		with patch("central.integrations.atlas.requests.post", return_value=response):
			with self.assertRaises(AtlasError) as caught:
				self._client()._run_doc_method(
					"Virtual Machine", "x", "start", None, action="start this server"
				)
		self.assertNotIsInstance(caught.exception, AtlasResourceGone)
		self.assertIn("No capacity here.", str(caught.exception))

	def test_success_returns_the_message(self):
		response = MagicMock(ok=True)
		response.json.return_value = {"message": "task-9"}
		with patch("central.integrations.atlas.requests.post", return_value=response):
			out = self._client()._run_doc_method(
				"Virtual Machine", "x", "start", None, action="start this server"
			)
		self.assertEqual(out, "task-9")
