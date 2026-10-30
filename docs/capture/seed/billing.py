import frappe

from central.billing.demo import _factory as factory
from central.billing.demo import demo_scenarios as scenarios
from seed.overlay import HERO_SLUG

REGION = "bom"
# The documented team shows a settled bill, not a payment still in flight.
HERO_STATE = "partial_card"


def seed() -> None:
	"""Run the billing demo with every resource in the one documented region.

	The billing demo wipes all billing and server rows, so it only runs on a site marked `docs_demo_site`.
	"""
	_clear_overlay()
	factory.CLUSTERS = [(REGION, "India — Mumbai", "INR")]
	factory.CLUSTER_MULT = {REGION: 1.0}
	scenarios.TEAMS = [
		(
			slug,
			tier,
			currency,
			HERO_STATE if slug == HERO_SLUG else state,
			[(REGION, plan) for _cluster, plan in resources],
			resize,
		)
		for slug, tier, currency, state, resources, resize in scenarios.TEAMS
	]
	# A USD team is a customer outside India, even when its servers run in Mumbai.
	scenarios._profile = lambda team, slug, currency, cluster: factory._profile(
		team, slug, currency, cluster if currency == "INR" else "me-dubai"
	)
	scenarios.seed()
	frappe.db.commit()


def _clear_overlay() -> None:
	"""Remove what the overlay adds, so the billing demo can drop and rebuild its teams."""
	from seed.overlay import TEAM_NAME

	for doctype in (
		"Site Domain",
		"Site",
		"VM Snapshot",
		"Server SSH Key",
		"Team SSH Key",
		"Team Invitation",
	):
		frappe.db.delete(doctype)
	frappe.db.set_value("Team", {"team_name": TEAM_NAME}, "team_name", HERO_SLUG)
