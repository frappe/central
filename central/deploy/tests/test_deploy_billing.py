from frappe.tests import UnitTestCase

from central.deploy.billing import get_composition


class UnitTestDeployBilling(UnitTestCase):
	def test_a_vm_is_billed_by_its_shape_in_vcpu_and_gigabytes(self):
		self.assertEqual(
			get_composition({"cpu_millicores": 500, "memory_mib": 2048, "disk_mib": 20480}),
			[
				{"resource_type": "Compute", "quantity": 0.5},
				{"resource_type": "Memory", "quantity": 2.0},
				{"resource_type": "Disk", "quantity": 20.0},
			],
		)
