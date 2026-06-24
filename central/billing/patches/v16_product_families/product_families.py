# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Seed the non-VM product families on the ADR 0007 taxonomy (#77).

The seed itself lives in `taxonomy_setup.ensure_catalog_masters` (shared with the
install/migrate/test hooks, since patches are skipped on fresh installs). This patch
just re-asserts it for existing databases migrating past v15. Idempotent.
"""

from central.billing.catalog.taxonomy_setup import ensure_catalog_masters


def execute():
	ensure_catalog_masters()
