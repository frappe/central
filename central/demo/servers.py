"""Dev-only demo fleet for the console's map-based server list.

On a local bench there is no Atlas, so the Asset / Atlas Instance mirrors that
normally fill from Atlas events stay empty and the servers map has nothing to
show. This module seeds a small fleet through the same write paths Atlas uses
(`Asset.mirror_vm`, the developer_setup Atlas Instance upsert) so the console
exercises the real endpoints end-to-end. When a real Atlas is wired up, run
`teardown` and delete this module — nothing else depends on it.

    bench --site central.localhost execute central.demo.servers.seed
    bench --site central.localhost execute central.demo.servers.summary
    bench --site central.localhost execute central.demo.servers.teardown

Notes:
- Never makes a network call: instances are saved with `skip_tunnel` and are
  never registered; base_urls point at an unroutable local name, so power
  actions (start/stop/terminate) fail with a connection error toast — expected.
- Idempotent: resource_ids are uuid5 of a fixed namespace, so re-running seed
  upserts the same rows and `teardown` can recompute exactly what it owns.
- Running assets mint a Subscription via `Asset.on_update`; teardown removes
  those too (Subscription Change -> Subscription -> Asset -> Atlas Instance,
  in Link-integrity order).
"""

from __future__ import annotations

import uuid
from collections import Counter

import frappe
from frappe import _
from frappe.utils import now_datetime

from central.api.developer_setup import _require_developer_mode
from central.central.doctype.asset.asset import Asset

# Fixed namespace so resource_ids are stable across runs (pure upserts) and
# teardown can derive the exact set of seed-owned rows without bookkeeping.
SEED_NAMESPACE = uuid.UUID("2f9c31d4-7b6a-4d0e-9c1f-5a8e2d4b6c80")

# region, provider, display_name, country_code, latitude, longitude, status.
# Coordinates match the FC V2 mockup catalog. Deliberate edge case: sa-jeddah
# is Draining, so list_instances hides it while its assets remain (exercises
# the console's unlisted-region fallback). A region saved without coordinates
# (0/0 = "not placed") lists but never pins — any hand-made instance covers it.
REGIONS = (
	("in-mumbai", "AWS", "Mumbai, India", "IN", 19.07, 72.87, "Active"),
	("in-navimumbai", "Frappe", "Navi Mumbai, India", "IN", 19.03, 73.03, "Active"),
	("de-falkenstein", "Hetzner", "Falkenstein, Germany", "DE", 50.48, 12.37, "Active"),
	("de-nuremberg", "Hetzner", "Nuremberg, Germany", "DE", 49.45, 11.08, "Active"),
	("us-virginia", "AWS", "N. Virginia, USA", "US", 39.04, -77.49, "Active"),
	("sg-singapore", "AWS", "Singapore", "SG", 1.35, 103.82, "Active"),
	("sa-jeddah", "OCI", "Jeddah, Saudi Arabia", "SA", 21.49, 39.19, "Draining"),
	("us-nyc", "DigitalOcean", "New York, USA", "US", 40.71, -74.01, "Active"),
)

# slug, team index (clamped to available teams), cluster, status, vcpus,
# memory_megabytes, disk_gigabytes, frappe_version. Statuses cover every console
# visual: Running (green), Pending (setting up), Stopped/Paused (gray), Failed
# (broken, red pulse) and one Terminated row that must never render.
ASSETS = (
	("web-01", 0, "in-mumbai", "Running", 4, 8192, 75, "v15"),
	("web-02", 0, "in-mumbai", "Running", 2, 4096, 40, "v15"),
	("worker-01", 0, "in-navimumbai", "Pending", 2, 4096, 40, "v16"),
	("db-01", 0, "de-falkenstein", "Running", 8, 16384, 160, "v15"),
	("cache-01", 0, "de-nuremberg", "Stopped", 2, 4096, 40, "v14"),
	("edge-01", 0, "us-virginia", "Failed", 1, 1024, 25, "nightly"),
	("batch-01", 0, "sg-singapore", "Paused", 2, 2048, 50, "v15"),
	("old-01", 0, "in-mumbai", "Terminated", 2, 4096, 40, "v14"),
	("legacy-01", 0, "sa-jeddah", "Stopped", 2, 4096, 60, "v14"),
	("t2-app-01", 1, "de-falkenstein", "Running", 4, 8192, 80, "v15"),
	("t2-app-02", 1, "us-nyc", "Running", 2, 4096, 60, "v15"),
	("t2-web-01", 1, "us-virginia", "Pending", 2, 4096, 40, "v16"),
	# Local benches usually have Administrator on the second team, so it gets
	# the same visual edge cases: a Mumbai/Navi Mumbai cluster pair, a Failed
	# pulse stacked on an occupied region, a Terminated row that must never
	# render, and sg-singapore left empty so the + spot shows.
	("t2-worker-01", 1, "in-mumbai", "Running", 2, 4096, 40, "v15"),
	("t2-cache-01", 1, "in-navimumbai", "Stopped", 2, 2048, 25, "v14"),
	("t2-edge-01", 1, "us-virginia", "Failed", 1, 1024, 25, "nightly"),
	("t2-old-01", 1, "de-nuremberg", "Terminated", 2, 4096, 40, "v15"),
)


def seed() -> dict:
	"""Upsert the demo regions and fleet. Safe to re-run."""
	_require_developer_mode()

	teams = _demo_teams()
	synced_at = now_datetime()
	# Region first — Atlas Instance.region links it (one Atlas = one Region).
	for region in REGIONS:
		_upsert_region(region)
	for region in REGIONS:
		_upsert_instance(region)
	for index, asset in enumerate(ASSETS):
		_mirror_asset(index, asset, teams, synced_at)

	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- command-style local seed persists demo rows.
	return summary()


def summary() -> dict:
	"""Counts of seed-owned rows, for a quick sanity check."""
	resource_ids = _seed_resource_ids()
	regions = [region for region, *_ in REGIONS]
	return {
		"regions": frappe.db.count("Region", {"name": ["in", regions]}),
		"atlas_instances": frappe.db.count("Atlas Instance", {"name": ["in", regions]}),
		"assets": frappe.db.count("Asset", {"name": ["in", resource_ids]}),
		"assets_by_status": dict(
			Counter(frappe.get_all("Asset", filters={"name": ["in", resource_ids]}, pluck="status"))
		),
		"subscriptions": frappe.db.count("Subscription", {"asset_id": ["in", resource_ids]}),
	}


def teardown() -> dict:
	"""Delete everything seed() created, in Link-integrity order. Safe to re-run."""
	_require_developer_mode()

	resource_ids = _seed_resource_ids()
	subscriptions = frappe.get_all("Subscription", filters={"asset_id": ["in", resource_ids]}, pluck="name")
	changes = frappe.get_all(
		"Subscription Change", filters={"subscription": ["in", subscriptions]}, pluck="name"
	)
	removed = {
		"subscription_changes": _delete_all("Subscription Change", changes),
		"subscriptions": _delete_all("Subscription", subscriptions),
		"assets": _delete_all("Asset", [r for r in resource_ids if frappe.db.exists("Asset", r)]),
		"atlas_instances": _delete_all(
			"Atlas Instance",
			[region for region, *_ in REGIONS if frappe.db.exists("Atlas Instance", region)],
		),
		# After the instances that link them.
		"regions": _delete_all(
			"Region",
			[region for region, *_ in REGIONS if frappe.db.exists("Region", region)],
		),
	}
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- command-style local teardown persists deletions.
	return removed


def _demo_teams() -> list[str]:
	teams = frappe.get_all(
		"Team", filters={"status": "Active"}, order_by="creation asc", pluck="name", limit=2
	)
	if not teams:
		frappe.throw(_("No Active Team found — sign up a user first, then re-run the seed."))
	return teams


def _upsert_region(region_row: tuple) -> None:
	region, provider, display_name, country_code, latitude, longitude, _status = region_row
	doc = frappe.get_doc("Region", region) if frappe.db.exists("Region", region) else frappe.new_doc("Region")
	doc.region = region
	doc.display_name = display_name
	doc.provider = provider
	doc.country_code = country_code
	doc.latitude = latitude
	doc.longitude = longitude
	doc.save(ignore_permissions=True)


def _upsert_instance(region_row: tuple) -> None:
	region, *_, status = region_row
	if frappe.db.exists("Atlas Instance", region):
		instance = frappe.get_doc("Atlas Instance", region)
	else:
		instance = frappe.new_doc("Atlas Instance")
		instance.region = region
	# Unroutable on purpose; the seed never registers a tunnel, so no call
	# ever leaves this machine. The dummy secret is a placeholder, not a credential.
	instance.base_url = f"http://{region}.atlas.localhost:9999"
	instance.api_key = "dev-seed-key"
	instance.api_secret = "dev-seed-secret"
	instance.skip_tunnel = 1
	instance.status = status
	instance.save(ignore_permissions=True)


def _mirror_asset(index: int, asset_row: tuple, teams: list[str], synced_at) -> None:
	slug, team_index, cluster, status, vcpus, memory_megabytes, disk_gigabytes, frappe_version = asset_row
	# mirror_vm is the mirror's sole sanctioned writer — same path Atlas events take.
	Asset.mirror_vm(
		cluster,
		{
			"name": _resource_id(slug),
			"team": teams[min(team_index, len(teams) - 1)],
			"title": slug,
			"status": status,
			"vcpus": vcpus,
			"memory_megabytes": memory_megabytes,
			"disk_gigabytes": disk_gigabytes,
			"frappe_version": frappe_version,
			"public_ipv4": f"192.0.2.{10 + index}",  # TEST-NET-1, never routable
			"ipv6_address": f"2001:db8::{10 + index:x}",  # documentation range
		},
		synced_at=synced_at,
	)


def _resource_id(slug: str) -> str:
	return str(uuid.uuid5(SEED_NAMESPACE, f"central-dev-seed:{slug}"))


def _seed_resource_ids() -> list[str]:
	return [_resource_id(slug) for slug, *_ in ASSETS]


def _delete_all(doctype: str, names: list[str]) -> int:
	for name in names:
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
	return len(names)
