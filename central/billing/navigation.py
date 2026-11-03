# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Install the app-level Workspace Sidebar fixtures.

Frappe v17 builds the desk sidebar from a Workspace Sidebar doc rather than from the
workspace's own links. Ours is authored at `central/workspace_sidebar/billing.json`,
and the framework picks app-level fixture folders up during `bench migrate` — but a
fresh install does not reliably reach that path, so a brand-new site (and the CI test
site built from one) can come up with no sidebar at all. When that happens Frappe
auto-generates one from the workspace shortcuts, which is precisely what this fixture
exists to replace.

Same reasoning as the catalog masters and the money constraints: navigation is a
property of the app, not of a site's history, so it runs on install, on migrate, and
before tests rather than living in a patch.
"""

import os

import frappe
from frappe.modules.import_file import import_file_by_path

SIDEBAR_FOLDER = "workspace_sidebar"
# The Billing workspace embeds this block. It has no module, so the doctype sync skips it.
CUSTOM_BLOCK_FOLDER = "billing/custom_html_block"


def ensure_workspace_sidebars():
	"""Import every sidebar and workspace block fixture the app ships.

	Idempotent: `import_file_by_path` compares the file's `modified` against the row's
	and skips the write when they already match, so a migrate on an up-to-date site
	does no work.
	"""
	for relative_folder in (CUSTOM_BLOCK_FOLDER, SIDEBAR_FOLDER):
		_import_folder(frappe.get_app_path("central", relative_folder))


def _import_folder(folder: str) -> None:
	if not os.path.isdir(folder):
		return

	for filename in sorted(os.listdir(folder)):
		if filename.endswith(".json"):
			import_file_by_path(os.path.join(folder, filename), ignore_version=True)
