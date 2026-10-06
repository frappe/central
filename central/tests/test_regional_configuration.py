import json
from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.errors import AtlasConnectionError
from central.integrations.atlas import AtlasClient
from central.patches.v0_0.reset_atlas_connection_checks import execute as reset_connection_checks
from central.sso import central_url


class TestRegionalConfiguration(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.instance = frappe.get_doc(
			{
				"doctype": "Region",
				"region": frappe.generate_hash(length=8),
				"base_url": "https://atlas.example.test",
				"atlas_region_id": "42",
				"status": "Active",
			}
		).insert()
		self.token = self.enterContext(
			patch("central.integrations.atlas.mint_atlas_token", return_value="test-token")
		)
		self.request = self.enterContext(patch("central.integrations.atlas.requests.request"))
		self.request.return_value = self.response({"items": [], "has_more": False})

	def response(self, body, status=200):
		response = requests.Response()
		response.status_code = status
		response._content = json.dumps(body).encode()
		return response

	def test_signed_connection_uses_direct_endpoint_and_explicit_tenant(self):
		AtlasClient.for_operator(self.instance).check_connection()

		arguments = self.request.call_args
		self.assertEqual(arguments.args[1], "https://atlas.example.test/api/atlas/images")
		self.assertEqual(arguments.kwargs["headers"]["Authorization"], "Bearer test-token")
		self.assertEqual(arguments.kwargs["headers"]["X-Tenant-ID"], "0")
		self.assertFalse(arguments.kwargs["allow_redirects"])
		self.token.assert_called_once_with(42)

	def test_missing_region_id_never_sends_request(self):
		self.instance.atlas_region_id = None
		with self.assertRaises(AtlasConnectionError):
			AtlasClient.for_operator(self.instance).check_connection()
		self.request.assert_not_called()

	def test_region_zero_is_valid_and_invalid_identifiers_are_rejected(self):
		self.instance.atlas_region_id = "0"
		self.assertEqual(self.instance.get_atlas_region_id(), 0)
		for value in ("-1", "65536", "42.0", "blr", "", "４２"):
			self.instance.atlas_region_id = value
			with self.subTest(value=value), self.assertRaises(AtlasConnectionError):
				self.instance.get_atlas_region_id()

	def test_disabled_region_never_sends_request(self):
		self.instance.status = "Disabled"
		with self.assertRaises(AtlasConnectionError):
			AtlasClient.for_operator(self.instance).check_connection()
		self.request.assert_not_called()

	def test_redirect_and_authentication_failures_are_not_success(self):
		for status in (302, 401, 403, 404, 503):
			self.request.return_value = self.response({}, status)
			with self.subTest(status=status), self.assertRaises(AtlasConnectionError):
				AtlasClient.for_operator(self.instance).check_connection()

	def test_ping_and_malformed_json_are_not_connection_proof(self):
		for response in (self.response({"message": "pong"}), self.response([])):
			self.request.return_value = response
			with self.assertRaises(AtlasConnectionError):
				AtlasClient.for_operator(self.instance).check_connection()

		self.request.return_value = self.response({})
		self.request.return_value._content = b"not json"
		with self.assertRaises(AtlasConnectionError):
			AtlasClient.for_operator(self.instance).check_connection()

	def test_connection_timeout_is_recorded_and_can_recover(self):
		self.request.side_effect = requests.Timeout("not exposed")
		self.assertFalse(self.instance.test_connection()["reachable"])
		self.instance.reload()
		self.assertIn("could not be reached", self.instance.connection_error)
		self.assertIsNotNone(self.instance.connection_checked_at)

		self.request.side_effect = None
		self.assertTrue(self.instance.test_connection()["reachable"])
		self.instance.reload()
		self.assertFalse(self.instance.connection_error)

	def test_migration_does_not_invent_region_id_or_keep_old_ping(self):
		self.instance.db_set({"reachable": 1, "atlas_region_id": None, "connection_checked_at": None})
		reset_connection_checks()
		reset_connection_checks()

		self.instance.reload()
		self.assertFalse(self.instance.reachable)
		self.assertIsNone(self.instance.atlas_region_id)

	def test_customer_cannot_check_global_configuration_or_use_another_team(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"regional-{frappe.generate_hash(length=8)}@example.test",
				"first_name": "Regional test",
				"send_welcome_email": 0,
				"roles": [{"role": "Central User"}],
			}
		).insert()
		own = frappe.get_doc({"doctype": "Team", "team_name": "Own", "owner_user": user.name}).insert()
		other = frappe.get_doc(
			{"doctype": "Team", "team_name": "Other", "owner_user": "Administrator"}
		).insert()
		frappe.set_user(user.name)
		self.addCleanup(frappe.set_user, "Administrator")

		client = AtlasClient.for_team(self.instance, own.name)
		self.assertEqual(client.tenant_id, own.tenant_id)
		client.check_connection()
		self.assertEqual(self.request.call_args.kwargs["headers"]["X-Tenant-ID"], str(own.tenant_id))
		for operation in (
			lambda: AtlasClient.for_team(self.instance, other.name),
			lambda: AtlasClient.for_operator(self.instance),
			self.instance.test_connection,
			self.instance.enroll_atlas,
		):
			with self.assertRaises(frappe.PermissionError):
				operation()
		self.request.assert_called_once()

	def test_insecure_remote_url_and_embedded_credentials_are_refused(self):
		for value in (
			"http://atlas.example.test",
			"https://user:password@atlas.example.test",
			"https://atlas.example.test/?token=x",
		):
			self.instance.base_url = value
			with self.subTest(value=value), self.assertRaises(AtlasConnectionError):
				AtlasClient.for_operator(self.instance).check_connection()
		self.request.assert_not_called()

	def test_local_http_requires_developer_mode(self):
		self.instance.base_url = "http://blr.atlas.localhost:8001"
		with patch.dict(frappe.conf, {"developer_mode": False}):
			with self.assertRaises(AtlasConnectionError):
				AtlasClient.for_operator(self.instance).check_connection()

		with patch.dict(frappe.conf, {"developer_mode": True}):
			AtlasClient.for_operator(self.instance).check_connection()
		self.request.assert_called_once()

	def test_missing_signing_key_is_recorded_as_a_connection_failure(self):
		self.token.side_effect = frappe.ValidationError("Initialize the Atlas signing key.")
		self.assertFalse(self.instance.test_connection()["reachable"])
		self.assertIn("signing key", self.instance.reload().connection_error)
		self.request.assert_not_called()

	def test_atlas_region_id_is_unique(self):
		"""Two Regions can't claim the same numeric Atlas region ID — that number is
		the token audience, and a shared audience would let one region's token pass
		for another's."""
		with self.assertRaises(frappe.UniqueValidationError):
			frappe.get_doc(
				{
					"doctype": "Region",
					"region": frappe.generate_hash(length=8),
					"base_url": "https://other.example.test",
					"atlas_region_id": "00042",
				}
			).insert()

	def test_migration_preserves_a_completed_signed_check(self):
		self.instance.test_connection()
		reset_connection_checks()

		self.assertTrue(self.instance.reload().reachable)

	def test_enroll_atlas_mints_and_sends_a_secret_the_first_time(self):
		self.request.return_value = self.response({"central_id": 1, "enabled": True, "webhooks": []})

		self.instance.enroll_atlas()

		arguments = self.request.call_args
		self.assertEqual(arguments.args[0], "PUT")
		self.assertEqual(arguments.args[1], "https://atlas.example.test/api/atlas/webhooks")
		payload = arguments.kwargs["json"]
		self.assertEqual(
			payload["request_url"], f"{central_url()}/api/method/central.api.state_delivery.receive"
		)
		self.assertTrue(payload["enabled"])
		self.assertEqual(payload["central_id"], 1)
		self.assertTrue(payload["webhook_secret"])

		self.assertEqual(self.instance.reload().get_password("webhook_secret"), payload["webhook_secret"])

	def test_enroll_atlas_sends_the_configured_central_id(self):
		self.request.return_value = self.response({})

		with patch("frappe.get_single_value", return_value=4):
			self.instance.enroll_atlas()

		self.assertEqual(self.request.call_args.kwargs["json"]["central_id"], 4)

	def test_enroll_atlas_reuses_an_existing_secret_on_a_repeated_call(self):
		self.request.return_value = self.response({})
		self.instance.enroll_atlas()
		first_secret = self.instance.reload().get_password("webhook_secret")

		self.instance.enroll_atlas()

		self.assertEqual(self.request.call_args.kwargs["json"]["webhook_secret"], first_secret)

	def test_enroll_atlas_raises_and_does_not_persist_a_rejected_secret(self):
		self.request.return_value = self.response({}, 403)

		with self.assertRaises(AtlasConnectionError):
			self.instance.enroll_atlas()

		self.assertIsNone(self.instance.reload().get_password("webhook_secret", raise_exception=False))

	def test_enroll_atlas_never_marks_test_connection_reachable(self):
		"""The two actions are independent: enrolling Atlas must not touch the fields
		Test Connection owns, and vice versa."""
		self.request.return_value = self.response({})
		self.instance.enroll_atlas()

		self.instance.reload()
		self.assertFalse(self.instance.reachable)
		self.assertIsNone(self.instance.connection_checked_at)


class TestProxyGateway(IntegrationTestCase):
	"""The bench gateway Central derives from a VM's mesh address, so that one-click Open
	needs no regional round-trip. The label is the inverse of the automatic proxy's
	decoder in `services/http-proxy/nginx/lua/http/auto_proxy.lua`."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.instance = frappe.get_doc(
			{
				"doctype": "Region",
				"region": frappe.generate_hash(length=8),
				"base_url": "https://atlas.par-2.example.test",
				"proxy_domain": "par-2.example.test",
				"status": "Active",
			}
		).insert()

	def test_mesh_address_becomes_the_admin_hostname(self):
		# fdaa:2:0:3::5 is tenant 3, VM 5: base36((5 << 32) | 3).
		self.assertEqual(
			self.instance.get_vm_gateway_url("fdaa:2:0:3::5"),
			"https://admin-vm-9v5k9vn.par-2.example.test",
		)
		self.assertEqual(
			self.instance.get_vm_gateway_url("fdaa:2:0:3:0:0:1:2a"),
			"https://admin-vm-2ru6ose8sj.par-2.example.test",
		)

	def test_no_zone_or_no_mesh_address_means_no_gateway(self):
		self.assertIsNone(self.instance.get_vm_gateway_url(None))
		self.instance.proxy_domain = None
		self.assertIsNone(self.instance.get_vm_gateway_url("fdaa:2:0:3::5"))

	def test_unusable_mesh_address_is_refused(self):
		with self.assertRaises(AtlasConnectionError):
			self.instance.get_vm_gateway_url("not-an-address")

	def test_zone_is_stored_bare(self):
		self.instance.proxy_domain = " *.PAR-2.example.test. "
		self.assertEqual(self.instance.save().proxy_domain, "par-2.example.test")

	def test_zone_rejects_a_url_or_a_bare_label(self):
		for value in ("https://par-2.example.test", "par-2.example.test/admin", "par-2:8000", "par-2"):
			self.instance.proxy_domain = value
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				self.instance.save()
