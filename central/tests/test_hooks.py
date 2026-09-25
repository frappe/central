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


class TestDeskScripts(IntegrationTestCase):
	def test_every_document_call_passes_the_document(self):
		"""`frm.call({ method })` without `doc` resolves `method` as a module function, so a
		controller method fails with "Failed to get method for command"."""
		import re
		from pathlib import Path

		root = Path(frappe.get_app_path("central"))
		for script in root.glob("**/doctype/*/*.js"):
			source = script.read_text()
			for match in re.finditer(r"frm\.call\(\{", source):
				depth, end = 0, match.end() - 1
				for end in range(match.end() - 1, len(source)):
					depth += {"{": 1, "}": -1}.get(source[end], 0)
					if depth == 0:
						break
				options = source[match.end() : end]
				method = re.search(r"method:\s*[\"']([^\"']+)", options)
				with self.subTest(script=script.name, method=method and method.group(1)):
					self.assertTrue("doc:" in options or (method and "." in method.group(1)))
