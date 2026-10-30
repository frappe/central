from typing import TYPE_CHECKING

import frappe

from central.iam import can

if TYPE_CHECKING:
	from central.signups.trial import Trial


def is_free_trial_creation(team: str, product: str | None) -> bool:
	"""Whether a creation request opens a free trial: a product's signup site, for a team that has
	no payment method and has never paid. A direct Central signup buys its servers."""
	return bool(product) and not has_active_payment_method(team) and not has_paid_before(team)


def has_paid_before(team: str) -> bool:
	"""Whether the team ever had a subscription or a bill. Such a team buys its sites, even after
	its payment method lapses."""
	return bool(
		frappe.db.exists("Subscription", {"team": team})
		or frappe.db.exists("Invoice", {"team": team, "status": ["not in", ("Draft", "Cancelled")]})
	)


def has_active_payment_method(team: str) -> bool:
	return bool(frappe.db.exists("Payment Method", {"team": team, "status": "Active"}))


def get_owner_team_names(team: str) -> list[str]:
	"""Every team of the team's owner. Trials are counted per owner, so a new team gives no new trials."""
	owner = frappe.db.get_value("Team", team, "owner_user")
	return frappe.get_all("Team", filters={"owner_user": owner}, pluck="name") if owner else [team]


def get_open_trial_of_owner(team: str) -> "Trial | None":
	"""The oldest open trial across every team of the team's owner, or None."""
	from central.signups.trial import OPEN_STATES, Trial

	site = frappe.db.get_value(
		"Site",
		{"team": ["in", get_owner_team_names(team)], "trial_state": ["in", OPEN_STATES]},
		order_by="creation asc",
	)
	return Trial.load(site) if site else None


def get_open_trial_summary(team: str) -> dict | None:
	"""The owner's open trial for the signup page, also one whose site is still being set up.
	A caller who cannot view the trial's team gets its state only, not its site."""
	from central.signups.trial import get_product_branding

	if trial := get_open_trial_of_owner(team):
		summary = trial.get_summary()
		if can(frappe.session.user, trial.site.team, "server:view"):
			return summary
		return {key: summary[key] for key in ("state", "product", "product_title", "product_logo")}

	creation = get_unrecorded_trial_creation(team)
	if not creation:
		return None

	return {"state": "Setting up", "product": creation.product, **get_product_branding(creation.product)}


def get_team_open_trial(team: str) -> dict | None:
	"""The team's own oldest open trial for the billing pages, because a payment method converts
	only this team's trials. The server is left out for a caller who cannot view it."""
	from central.signups.trial import OPEN_STATES, Trial, get_product_branding

	name = frappe.db.get_value(
		"Site", {"team": team, "trial_state": ["in", OPEN_STATES]}, order_by="creation asc"
	)
	if not name:
		return None

	trial = Trial.load(name)
	return {
		"state": trial.state,
		"server": trial.site.server if can(frappe.session.user, team, "server:view") else None,
		"product": trial.site.product,
		"product_title": get_product_branding(trial.site.product)["product_title"],
		"plan": trial.get_plan(),
	}


def get_unrecorded_trial_creation(team: str) -> frappe._dict | None:
	"""The owner's oldest free trial creation whose site Central has not recorded yet: still
	pending, or with a live server that has not reported its site."""
	action = frappe.qb.DocType("Resource Action")
	site = frappe.qb.DocType("Site")
	machine = frappe.qb.DocType("Virtual Machine")
	rows = (
		frappe.qb.from_(action)
		.left_join(site)
		.on(site.server == action.server)
		.left_join(machine)
		.on(machine.name == action.server)
		.select(action.name, action.product)
		.where(
			action.team.isin(get_owner_team_names(team))
			& (action.action == "create")
			& (action.is_free_trial == 1)
			& action.status.notin(("Failed", "Timed Out"))
			& site.name.isnull()
			& (machine.status.isnull() | (machine.status != "Terminated"))
		)
		.orderby(action.creation)
		.limit(1)
	).run(as_dict=True)
	return rows[0] if rows else None
