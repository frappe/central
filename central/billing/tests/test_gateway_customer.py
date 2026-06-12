# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Gateway Customer store + the provisioning patch (v11)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.patches.v11_provision_gateway_customers import (
	provision_gateway_customers as provision,
)
from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
from central.billing.tests.utils import complete_billing_profile, ensure_team

TEAM = "team-gwcust"


@contextmanager
def stub(gateway, customer_id="cus_prov"):
	"""Pin gateway resolution + a mock adapter so the patch makes no live call."""
	adapter = MagicMock()
	adapter.create_customer.return_value = customer_id
	with patch(
		"central.billing.gateways.registry.resolve_gateway_for_currency", return_value=gateway
	), patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


class TestProvisionGatewayCustomersPatch(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		self.gateway = make_razorpay_gateway("GW-Prov-INR").name
		frappe.db.delete("Gateway Customer", {"team": TEAM})
		complete_billing_profile(TEAM, "INR")

	def tearDown(self):
		frappe.db.delete("Gateway Customer", {"team": TEAM})
		frappe.db.delete("Billing Profile", {"team": TEAM})

	def _customer(self):
		return frappe.db.get_value(
			"Gateway Customer", {"team": TEAM, "gateway": self.gateway}, "gateway_customer_id"
		)

	def test_provisions_customer_for_team_with_profile(self):
		with stub(self.gateway) as adapter:
			provision.execute()
			self.assertEqual(self._customer(), "cus_prov")

			# Idempotent: a re-run reuses the stored row, no second mint.
			adapter.create_customer.reset_mock()
			provision.execute()
			adapter.create_customer.assert_not_called()
			self.assertEqual(self._customer(), "cus_prov")
