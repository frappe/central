import inspect
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.pilot import datum_token

# Below the whitelist and the credential check, which the tests replace with frappe.local.pilot_credential.
token_for_credential = inspect.unwrap(datum_token)


class TestPilotDatumToken(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.mint = self.enterContext(patch("central.sso.mint_datum_token", return_value="datum-token"))
		self.enterContext(patch("central.api.pilot.get_pilot_region", return_value="region-a"))
		self.enterContext(patch("central.api.pilot.region_id_of", return_value=60117))
		self.enterContext(patch("central.api.pilot.get_telemetry_base_url", return_value="https://datum"))
		frappe.local.pilot_credential = SimpleNamespace(server="server-a")
		self.addCleanup(setattr, frappe.local, "pilot_credential", None)

	def call(self, atlas_vm_id: str | None) -> dict:
		with patch("central.api.pilot.frappe.db.get_value", return_value=atlas_vm_id) as get_value:
			result = token_for_credential()
		get_value.assert_called_once_with("Virtual Machine", "server-a", "atlas_vm_id")
		return result

	def test_a_pilot_sends_as_the_atlas_name_of_its_virtual_machine(self):
		result = self.call("vm-7-0042")

		self.assertEqual(result["resource_id"], "vm-7-0042")
		self.mint.assert_called_once_with(60117, "vm-7-0042")

	def test_a_pilot_whose_virtual_machine_atlas_has_not_bound_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.call(None)

		self.mint.assert_not_called()
