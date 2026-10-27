from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

import frappe

from central.billing.api import billing_api
from central.infrastructure.doctype.resource_action.resource_action import ResourceAction
from central.infrastructure.doctype.site.plan_change import PlanChange
from central.integrations.servers import observe_server
from central.tests.test_sites import SiteOnAMachine

SHAPE = {"vcpus": 2.0, "memory_megabytes": 4096, "disk_gigabytes": 40}


class PlanChangeCase(SiteOnAMachine):
	"""A site whose server has a resize queued."""

	def setUp(self):
		super().setUp()
		ResourceAction.queue(
			"create",
			self.team.name,
			self.region.name,
			self.server.name,
			server=self.server.name,
			resource_type="Site",
			request_key="request-" + frappe.generate_hash(length=8),
			request_payload={"image_tags": {"purpose": "pilot"}, "site": {"product": None}},
		)
		self.enroll()
		self.enterContext(
			patch("central.integrations.pilot.rename_admin_domain", return_value={"task_id": "task-1"})
		)
		observe_server(self.server)

	def resize(self, server: str | None = None) -> ResourceAction:
		return ResourceAction.queue(
			"resize",
			self.team.name,
			self.region.name,
			self.server.name,
			server=server or self.server.name,
			request_payload={"subscription": "subscription-1", "shape": SHAPE},
		)

	def open_link(self, url: str) -> PlanChange:
		query = dict(parse_qsl(urlsplit(url).query))
		return PlanChange.from_signed_link(query["action"], query["site"], query["_signature"])


class TestPlanChange(PlanChangeCase):
	def test_a_signed_link_opens_its_plan_change(self):
		action = self.resize()

		change = self.open_link(PlanChange(self.site(), action).url)

		self.assertEqual(change.action.name, action.name)
		self.assertEqual(change.site.name, self.site().name)

	def test_a_changed_signature_is_refused(self):
		action = self.resize()

		with self.assertRaises(frappe.PermissionError):
			PlanChange.from_signed_link(action.name, self.site().name, "0" * 128)

	def test_a_link_to_another_servers_resize_is_refused(self):
		action = self.resize(server=self.server.name)
		action.db_set("resource_id", "server-other")

		with self.assertRaises(frappe.PermissionError):
			self.open_link(PlanChange(self.site(), action).url)

	def test_a_reopened_link_keeps_the_size_before_the_resize(self):
		"""The server reports its new size once the resize lands; the page still shows the old one."""
		action = self.resize()
		payload = frappe.parse_json(action.request_payload)
		payload["from_shape"] = {"vcpus": 1.0, "memory_megabytes": 2048, "disk_gigabytes": 25}
		action.db_set({"status": "Succeeded", "request_payload": frappe.as_json(payload)})
		self.server.db_set({"vcpus": 2, "memory_megabytes": 4096, "disk_gigabytes": 40})

		with patch("central.infrastructure.doctype.site.plan_change.is_site_reachable", return_value=False):
			progress = PlanChange(self.site(), action).get_progress()

		self.assertEqual(progress["current_shape"]["vcpus"], 1.0)
		self.assertEqual(progress["shape"]["vcpus"], 2.0)

	def test_the_site_is_ready_only_once_it_answers(self):
		action = self.resize()
		action.db_set("status", "Succeeded")
		change = PlanChange(self.site(), action)

		with patch("central.infrastructure.doctype.site.plan_change.is_site_reachable", return_value=False):
			self.assertEqual(change.get_progress()["step"], "starting")
		with patch("central.infrastructure.doctype.site.plan_change.is_site_reachable", return_value=True):
			self.assertEqual(change.get_progress()["step"], "ready")

	def test_the_page_opens_the_chosen_name_on_the_products_page(self):
		"""The chosen name answers once its route is active, before a sign-in records the rename."""
		product = frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": "raven",
				"title": "Raven",
				"signup_app": "raven",
				"landing_route": "/raven",
			}
		).insert(ignore_if_duplicate=True)
		site = self.site()
		site.db_set({"subdomain": "acme", "product": product.name})
		with patch(
			"central.infrastructure.doctype.region.region.Region.get_zone",
			return_value=self.region.proxy_domain,
		):
			site.route_subdomain()
		frappe.db.set_value("Site Domain", site.rename_target, "status", "Active")

		with patch("central.infrastructure.doctype.site.plan_change.is_site_reachable", return_value=False):
			progress = PlanChange(self.site(), self.resize()).get_progress()

		self.assertEqual(progress["site"], site.rename_target)
		self.assertEqual(progress["site_url"], f"https://{site.rename_target}/raven")


class TestPilotPlanChange(PlanChangeCase):
	def setUp(self):
		super().setUp()
		self.enterContext(patch.object(billing_api, "_server", return_value=self.server.name))
		self.enterContext(patch.object(billing_api, "_team", return_value=self.team.name))
		# The Pilot token check is the endpoint's edge; the server and team above come from it.
		self.enterContext(patch("central.api.pilot.frappe.get_request_header", return_value="token"))
		self.enterContext(
			patch("central.api.pilot.PilotCredential.verify", return_value=frappe._dict(name="credential"))
		)

	def test_a_trial_site_keeps_the_plan_it_moves_to_and_resizes_nothing(self):
		self.site().db_set(
			{"trial_state": "Active", "trial_ends_on": frappe.utils.add_days(frappe.utils.nowdate(), 5)}
		)
		choices = [{"name": "plan-2vcpu"}]

		with patch("central.signups.trial.Trial.get_plan_choices", return_value=choices):
			result = billing_api.change_plan(plan="plan-2vcpu")
			with self.assertRaisesRegex(frappe.ValidationError, "not available for this site"):
				billing_api.change_plan(plan="plan-8vcpu")

		self.assertFalse(result["queued"])
		self.assertEqual(self.site().conversion_plan, "plan-2vcpu")
		self.assertFalse(
			frappe.db.exists("Resource Action", {"server": self.server.name, "action": "resize"})
		)

	def test_a_queued_change_returns_its_progress_page(self):
		action = self.resize()
		frappe.get_doc(
			{
				"doctype": "Subscription",
				"name": "subscription-1",
				"team": self.team.name,
				"server_id": self.server.name,
				"enabled": 1,
			}
		).db_insert()

		with patch(
			"central.billing.catalog.subscriptions.begin_resize",
			return_value={"queued": True, "resized": True, **action.customer_status()},
		):
			result = billing_api.change_plan(plan="plan-2vcpu")

		self.assertIn("/upgrading?", result["progress_url"])

	def test_plans_with_a_smaller_disk_are_not_offered(self):
		"""A plan change takes the plan's own disk, and a server's disk can't shrink."""
		self.server.db_set({"disk_gigabytes": 25, "plan": None})
		menu = {
			"currency": "USD",
			"plans": {
				"general": [
					{
						"plan": f"plan-{disk}gb",
						"title": f"{disk} GB",
						"rate": 10,
						"includes": [{"resource_type": "Disk", "quantity": disk, "unit": "GB"}],
					}
					for disk in (20, 25, 50)
				]
			},
		}

		with patch("central.billing.api.dashboard.catalog.get_eligible_plans", return_value=menu):
			options = billing_api.get_plan_options()

		self.assertEqual([plan["name"] for plan in options["plans"]], ["plan-25gb", "plan-50gb"])
