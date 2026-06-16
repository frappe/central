import frappe
from frappe.tests import IntegrationTestCase

from central.billing.gateways.registry import supported_currencies


class TestSupportedCurrencyFallback(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_falls_back_to_default_currency_when_no_gateway(self):
		# No enabled Payment Gateway is configured (fresh site): the picker must
		# still offer the site's default currency so onboarding isn't a dead end.
		if frappe.get_all("Payment Gateway", {"is_enabled": 1}, limit=1):
			self.skipTest("a gateway is configured; fallback path not exercised")
		default = frappe.db.get_default("currency")
		self.assertEqual(supported_currencies(), [default])
