import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings
from central.infrastructure.doctype.virtual_machine import template
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.pilot import METADATA_VALUE_BYTES
from central.integrations.resource_actions import TEMPLATE_METADATA_KEY, _create_payload
from central.sso import central_url, mint_bootstrap_token, verify_template_ready_token
from central.tests.test_server_network import creation_request

WILDCARD = "example.test"


@patch("central.integrations.resource_actions.idle_shutdown_seconds", return_value=0)
class TestTemplateMetadata(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		self.addCleanup(frappe.db.rollback)
		CentralSSOSettings.instance().initialize_signing_key("pilot")

	def test_a_template_server_gets_a_token_for_its_own_creation(self, _idle) -> None:
		value = _create_payload(creation_request("one-click"))["metadata"][TEMPLATE_METADATA_KEY]
		bootstrap = json.loads(value)

		self.assertLessEqual(len(value.encode()), METADATA_VALUE_BYTES)
		self.assertEqual(bootstrap["endpoint"], central_url())
		self.assertEqual(verify_template_ready_token(bootstrap["token"]), "action-1")

	def test_any_other_server_gets_no_token(self, _idle) -> None:
		self.assertNotIn(TEMPLATE_METADATA_KEY, _create_payload(creation_request())["metadata"])

	def test_a_token_of_another_scope_is_refused(self, _idle) -> None:
		with self.assertRaises(frappe.AuthenticationError):
			verify_template_ready_token(mint_bootstrap_token("team-a", "pilot-action-1"))


class TestTemplateServer(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch.object(VirtualMachine, "ensure_subscription_enabled"))
		frappe.db.set_single_value("Central Settings", "wildcard_domain", WILDCARD)
		suffix = frappe.generate_hash(length=8)
		self.region = f"tpl-{suffix}"
		frappe.get_doc(
			{
				"doctype": "Region",
				"region": self.region,
				"base_url": "https://atlas.example.test",
				"status": "Active",
				"proxy_domain": f"{self.region}.{WILDCARD}",
			}
		).insert()
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": f"Templates {suffix}", "owner_user": "Administrator"}
		).insert()
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"server-{suffix}",
				"team": self.team.name,
				"region": self.region,
				"status": "Running",
				"ipv6_address": "fdaa:2::264",
			}
		).insert(ignore_permissions=True)
		self.action = frappe.get_doc(
			{
				"doctype": "Resource Action",
				"resource_type": "Server",
				"action": "create",
				"team": self.team.name,
				"region": self.region,
				"server": self.server.name,
				"subdomain": f"app-{suffix}",
				"requested_by": "Administrator",
				"correlation_id": frappe.generate_hash(length=32),
				"status": "Succeeded",
			}
		).insert(ignore_permissions=True)
		self.domain = f"app-{suffix}.{self.region}.{WILDCARD}"

	def test_the_first_report_marks_the_server_ready(self) -> None:
		with patch.object(template, "verify_template_ready_token", return_value=self.action.name):
			template.record_ready("token")
			first = frappe.db.get_value("Virtual Machine", self.server.name, "app_ready_at")
			with patch.object(template, "now_datetime", return_value=add_to_date(now_datetime(), hours=1)):
				template.record_ready("token")

		self.assertIsNotNone(first)
		self.assertEqual(frappe.db.get_value("Virtual Machine", self.server.name, "app_ready_at"), first)

	def test_a_report_before_the_server_is_recorded_is_refused(self) -> None:
		self.action.db_set("server", None)

		with patch.object(template, "verify_template_ready_token", return_value=self.action.name):
			with self.assertRaises(frappe.DoesNotExistError):
				template.record_ready("token")

	def test_the_chosen_name_is_routed_once_the_server_has_an_address(self) -> None:
		with patch.object(frappe, "enqueue") as enqueue:
			template.route_chosen_name(self.server.name)
		self.assertEqual(enqueue.call_args.kwargs["server"], self.server.name)

		with patch.object(frappe, "enqueue"):
			template.insert_route(self.server.name)
		route = frappe.get_doc("Site Domain", self.domain)
		self.assertEqual(
			(route.route_type, route.server, route.team), ("Site", self.server.name, self.team.name)
		)

		with patch.object(frappe, "enqueue") as enqueue:
			template.route_chosen_name(self.server.name)
		enqueue.assert_not_called()

	def test_ready_waits_for_the_report_and_the_route(self) -> None:
		self.assertEqual(template.get_journey(self.action.name)["phase"], "app")

		self.server.db_set("app_ready_at", now_datetime())
		self.assertEqual(template.get_journey(self.action.name)["phase"], "app")

		with patch.object(frappe, "enqueue"):
			template.insert_route(self.server.name)
		frappe.db.set_value("Site Domain", self.domain, "status", "Active")
		journey = template.get_journey(self.action.name)

		self.assertEqual(journey["phase"], "ready")
		self.assertEqual(journey["url"], f"https://{self.domain}")
		self.assertEqual(journey["domain"], f"{self.region}.{WILDCARD}")

	def test_a_server_without_a_name_is_ready_on_its_report(self) -> None:
		self.action.db_set("subdomain", None)
		self.server.db_set("app_ready_at", now_datetime())
		journey = template.get_journey(self.action.name)

		self.assertEqual((journey["phase"], journey["url"]), ("ready", None))
