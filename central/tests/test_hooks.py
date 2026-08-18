import frappe
from frappe.tests import IntegrationTestCase


class TestSchedulerHooks(IntegrationTestCase):
	def test_every_scheduler_target_resolves(self):
		"""Every scheduler_events target must import to a callable. A dangling or
		classmethod-only path only surfaces as a `bench migrate` warning, so the
		stale job silently never runs (e.g. resource_action.sweep_stale)."""
		events = frappe.get_hooks("scheduler_events", app_name="central")
		targets = []
		for value in events.values():
			if isinstance(value, dict):
				for methods in value.values():
					targets.extend(methods)
			else:
				targets.extend(value)

		for dotted_path in targets:
			with self.subTest(target=dotted_path):
				self.assertTrue(callable(frappe.get_attr(dotted_path)), dotted_path)
