# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

from frappe.tests import IntegrationTestCase

from central.billing.platform.sync import push_plans_to_agent
from central.billing.tests.utils import make_plan


class TestPushPlansToAgent(IntegrationTestCase):
	def test_posts_identity_includes_and_rates_to_agent_endpoint(self):
		make_plan("bundle-test-push")

		with patch("central.billing.platform.sync.requests.post") as mock_post:
			mock_post.return_value = MagicMock(status_code=200)
			mock_post.return_value.json.return_value = {"message": {"received": ["bundle-test-push"]}}

			push_plans_to_agent(agent_url="https://agent.example", plans=["bundle-test-push"])

		self.assertEqual(mock_post.call_count, 1)
		_, kwargs = mock_post.call_args
		# Targets the Agent's receive_plans method endpoint.
		self.assertIn("press_billing_agent.sync.receive_plans", kwargs["url"])

		pushed = kwargs["json"]["plans"][0]
		self.assertEqual(pushed["plan"], "bundle-test-push")  # immutable identity
		self.assertEqual(len(pushed["includes"]), 3)  # composition, no price
		rates_by_ccy = {r["currency"]: r["rate"] for r in pushed["rates"]}
		self.assertEqual(rates_by_ccy["USD"], 40)  # full rate set, both currencies
		self.assertEqual(rates_by_ccy["INR"], 3200)
