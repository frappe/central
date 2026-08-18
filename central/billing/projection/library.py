# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A shelf of named questions, applicable to any real team in one click.

The training tool. Billing has a dozen behaviours that are correct, deliberate and
invisible until they surprise somebody — the ₹15,000 silent-debit ceiling, hourly
billing after a same-day resize, a suspension that leaves the resource running until its
token expires, a late run that costs the customer no grace. Reading about them does not
stick. Watching one happen to a team you know does.

Each entry is declarative: overrides, events, and a sentence saying what to look for.
Adding one needs no engine change, which is the property that decides whether a
catalogue like this stays current or rots.

The last entry matters most, because its correct answer is *"nothing bad happens"*.
Being able to show that is worth more than asserting it.
"""

import frappe
from frappe import _

SCENARIOS = {
	"over-the-inr-threshold": {
		"title": "An INR bill over the silent-debit ceiling",
		"question": "What happens when an auto-charged INR bill crosses ₹15,000?",
		"look_for": (
			"The outcome is Action Required, not a failed charge. Nothing is auto-debited "
			"above the ceiling by design, and dunning escalates without retrying — the "
			"customer has to act."
		),
		"overrides": {},
		"events": [],
		"requires": {"collection_mode": "Auto Charge"},
	},
	"no-way-to-pay": {
		"title": "No payment method and no credits",
		"question": "What does a team with nothing to charge look like before the 1st?",
		"look_for": (
			"A derived finding rather than a guess, and a suspension date that follows "
			"from the ladder. Nothing here is a prediction."
		),
		"overrides": {},
		"events": [],
	},
	"resized-twice-in-a-day": {
		"title": "Two resizes inside 24 hours",
		"question": "Why did one day of the bill itemise by the hour?",
		"look_for": (
			"That date leaves daily billing entirely and bills the real hours each config "
			"ran. Open the line: the drill names every config that shared the date."
		),
		"overrides": {},
		"events": [
			{"event_type": "Resize", "offset_days": 14, "at": "09:00:00", "rate_multiple": 2.0},
			{"event_type": "Resize", "offset_days": 14, "at": "18:00:00", "rate_multiple": 1.0},
		],
	},
	"wallet-runs-dry": {
		"title": "A credits-only team whose wallet runs out",
		"question": "When does prepaid credit stop covering the bill?",
		"look_for": (
			"The month the shortfall appears, and the suspension that follows it. A "
			"single-month projection cannot show this; the balance carries."
		),
		"overrides": {},
		"events": [],
		"months": 6,
	},
	"rescued-by-a-top-up": {
		"title": "A top-up arrives just in time",
		"question": "Does money added mid-month reach the bill it is meant to cover?",
		"look_for": "The shortfall closing in the month the top-up lands, not the one after.",
		"overrides": {},
		"events": [{"event_type": "Top up", "offset_days": 20, "amount": 25000}],
		"months": 3,
	},
	"harsher-dunning": {
		"title": "Suspend a week sooner",
		"question": "What would tightening the ladder do to the teams already behind?",
		"look_for": (
			"Every date on the unpaid branch moving left. Billing Settings are untouched — "
			"this is read instead of them, for one projection."
		),
		"overrides": {"suspend_after_days": 7, "terminate_after_days": 30},
		"events": [],
	},
	"a-price-rise": {
		"title": "Raise prices 20%",
		"question": "What does a catalog price rise do to next month's revenue?",
		"look_for": (
			"Almost certainly nothing. Existing resources bill at the rate locked when "
			"they were provisioned; a catalog change reaches new provisions and resizes. "
			"The split says how much could move at all."
		),
		"overrides": {},
		"events": [],
		"rate_percent": 20,
	},
	"a-late-billing-run": {
		"title": "The run was three days late",
		"question": "Does our own delay cost the customer their grace period?",
		"look_for": (
			"No. The escalation clock is pushed forward by the same window a fresh invoice "
			"gets, while the due date stays put — what was owed and when is an accounting "
			"fact. This is the scenario whose right answer is that nothing bad happens."
		),
		"overrides": {},
		"events": [],
		"illustrates": "deferred_clock",
	},
}


def catalogue() -> list[dict]:
	"""Every scenario on the shelf, for a picker."""
	return [
		{
			"key": key,
			"title": entry["title"],
			"question": entry["question"],
			"look_for": entry["look_for"],
			"months": entry.get("months", 1),
		}
		for key, entry in SCENARIOS.items()
	]


def applicable(key: str, team: str) -> tuple[bool, str | None]:
	"""Whether this scenario can say anything true about this team.

	Where it cannot, it says why rather than projecting something misleading — a
	threshold scenario applied to a card team would demonstrate nothing and imply
	plenty.
	"""
	entry = SCENARIOS.get(key)
	if not entry:
		return False, f"No scenario called {key}."

	requires = entry.get("requires") or {}
	if "collection_mode" in requires:
		mode = frappe.db.get_value("Billing Profile", team, "collection_mode")
		if mode != requires["collection_mode"]:
			return False, (
				f"This one needs a team on {requires['collection_mode']}; "
				f"{team} is on {mode or 'no configured mode'}."
			)
	return True, None


def build(key: str, team: str, period_start=None, today=None):
	"""Turn a catalogue entry into a Billing Scenario for this team.

	Built, not saved: the shelf is a way of asking, and an operator who wants to keep
	one saves it themselves.
	"""
	entry = SCENARIOS.get(key)
	if not entry:
		frappe.throw(_("No scenario called {0}.").format(key), frappe.ValidationError)

	ok, reason = applicable(key, team)
	if not ok:
		frappe.throw(reason, frappe.ValidationError)

	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	period_start = frappe.utils.get_first_day(period_start or today)

	doc = frappe.new_doc("Billing Scenario")
	doc.scenario_name = f"{entry['title']} — {team}"
	doc.team = team
	doc.period_start = period_start
	doc.months = entry.get("months", 1)
	doc.outcome_mode = "Derived"
	for field, value in (entry.get("overrides") or {}).items():
		doc.set(field, value)

	for event in entry.get("events") or []:
		doc.append("events", _event_row(event, team, period_start))

	if entry.get("rate_percent"):
		for plan in _plans_for(team):
			doc.append(
				"rate_overrides",
				{
					"priced_doctype": "Plan",
					"priced_for": plan,
					"percent": entry["rate_percent"],
					"effective_from": period_start,
				},
			)
	return doc


def _event_row(event: dict, team: str, period_start) -> dict:
	"""A catalogue event is relative — it has to land inside whatever month is projected."""
	on_date = frappe.utils.add_days(period_start, frappe.utils.cint(event.get("offset_days")))
	row = {
		"event_type": event["event_type"],
		"on_date": f"{on_date} {event.get('at', '00:00:00')}",
	}
	if event["event_type"] in ("Resize", "Provision"):
		subscription = _subscription_for(team)
		row["subscription"] = subscription
		row["plan"] = frappe.db.get_value("Subscription", subscription, "plan") if subscription else None
		row["rate"] = _current_rate(subscription) * frappe.utils.flt(event.get("rate_multiple") or 1)
	if event["event_type"] == "Top up":
		row["amount"] = event.get("amount")
		row["currency"] = frappe.db.get_value("Billing Profile", team, "currency")
	return row


def _subscription_for(team: str) -> str | None:
	names = frappe.get_all(
		"Subscription", filters={"team": team}, pluck="name", order_by="creation asc", limit=1
	)
	return names[0] if names else None


def _current_rate(subscription: str | None) -> float:
	"""The rate the subscription is running at, so a "double it" event doubles something."""
	if not subscription:
		return 0.0
	rows = frappe.get_all(
		"Subscription Change",
		filters={"subscription": subscription, "locked_rate": ["is", "set"]},
		fields=["locked_rate"],
		order_by="effective_at desc",
		limit=1,
	)
	return frappe.utils.flt(rows[0].locked_rate) if rows else 0.0


def _plans_for(team: str) -> list[str]:
	return list({p for p in frappe.get_all("Subscription", filters={"team": team}, pluck="plan") if p})
