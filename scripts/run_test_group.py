import sys
from pathlib import Path

import frappe
from frappe.commands.testing import main

APP_ROOT = Path(__file__).resolve().parent.parent
GROUPS = ("billing", "core")


def get_modules(group: str) -> list[str]:
	"""Test modules under central/billing for the billing group, all others for core."""
	paths = sorted((APP_ROOT / "central").rglob("test_*.py"))
	modules = [".".join(path.relative_to(APP_ROOT).with_suffix("").parts) for path in paths]
	return [module for module in modules if module.startswith("central.billing.") == (group == "billing")]


if __name__ == "__main__":
	site, group = sys.argv[1], sys.argv[2]
	if group not in GROUPS:
		sys.exit(f"Unknown test group {group!r}, expected one of {GROUPS}")

	frappe.init(site)
	# run-tests takes one module, so call the function it wraps to run the whole group in one process
	main(site, "central", get_modules(group))
