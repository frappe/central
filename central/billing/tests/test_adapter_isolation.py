# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import pathlib
import re

from central import billing
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

SDK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(stripe|razorpay|paypalrestsdk)\b", re.M)


class TestAdapterIsolation(IntegrationTestCase):
	def test_core_billing_never_imports_a_gateway_sdk(self):
		"""Only modules under gateways/ may import a gateway SDK."""
		root = pathlib.Path(billing.__file__).parent
		offenders = []
		for path in root.rglob("*.py"):
			if "gateways" in path.parts or "tests" in path.parts:
				continue
			if SDK_IMPORT.search(path.read_text()):
				offenders.append(str(path.relative_to(root)))

		self.assertEqual(offenders, [], f"gateway SDK imported outside gateways/: {offenders}")
