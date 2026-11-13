# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.query_builder import Order

from central.billing.doctype.billing_event import billing_event
from central.billing.payments import decline
from central.billing.states import record_event

SETUP_FAILED_EVENT = "Payment Method Setup Failed"
METHOD_FAILED_EVENT = "Payment Method Failed"
TOP_UP_DECLINED_EVENT = "Top-up Order Declined"
FAILURE_EVENTS = (SETUP_FAILED_EVENT, METHOD_FAILED_EVENT, TOP_UP_DECLINED_EVENT)

# The wait after the nth failure, by n. The last entry holds for every failure after it.
SCHEDULE = (
	timedelta(0),
	timedelta(0),
	timedelta(0),
	timedelta(0),
	timedelta(0),
	timedelta(minutes=10),
	timedelta(minutes=10),
	timedelta(minutes=30),
	timedelta(hours=2),
	timedelta(hours=6),
	timedelta(hours=24),
)
ALERT_AT = len(SCHEDULE) - 1
RESET_AFTER = timedelta(days=7)
# The oldest failure that can still be in a run of ALERT_AT failures.
LOOKBACK = RESET_AFTER * (ALERT_AT + 1)

# Sessions that are not a person: a pilot call, or the system.
_UNATTRIBUTED_USERS = ("Guest", "Administrator")


class TooManyFailedSetups(frappe.ValidationError):
	"""The team or the user failed too many setups or top-ups in a row."""


def check(team: str, user: str | None = None) -> None:
	"""Refuse a new setup or top-up while the team or the user must wait."""
	wait = wait_for(team, user)
	if wait:
		frappe.throw(wait_message(wait), TooManyFailedSetups)


def wait_for(team: str, user: str | None = None) -> timedelta | None:
	"""How long the team, or the user, must still wait. None when they need not."""
	lockouts = [Lockout.for_team(team)]
	if _is_person(user):
		lockouts.append(Lockout.for_user(user, team))
	waits = [wait for wait in (lockout.get_wait() for lockout in lockouts) if wait]
	return max(waits, default=None)


def wait_message(wait: timedelta) -> str:
	"""The wait, said to the customer."""
	minutes = max(1, -(-int(wait.total_seconds()) // 60))
	if minutes < 60:
		duration = _("1 minute") if minutes == 1 else _("{0} minutes").format(minutes)
	else:
		hours = -(-minutes // 60)
		duration = _("1 hour") if hours == 1 else _("{0} hours").format(hours)
	return _("Too many failed attempts. Try again in {0}.").format(duration)


def note_failure(team: str, user: str | None, failure_code: str | None, decline_code: str | None = None):
	"""Tell the operators once, when a bank refusal is the one that starts the longest wait."""
	if not decline.is_bank_refusal(failure_code, decline_code):
		return
	user = user if _is_person(user) else None
	is_team_locked = Lockout.for_team(team).get_count() == ALERT_AT
	if is_team_locked or (user and Lockout.for_user(user, team).get_count() == ALERT_AT):
		frappe.enqueue(
			"central.billing.payments.setup_lockout.alert_operators",
			team=team,
			user=user,
			enqueue_after_commit=True,
		)


def alert_operators(team: str, user: str | None = None) -> list[str]:
	"""Send the lock to the billing operators' alert channel."""
	from central.billing.platform.alerts import notify_operators

	alert = {
		"alert": "setup_lockout",
		"meaning": "A team or user had too many payment method setups or top-ups refused by the bank.",
		"doctype": "Billing Profile",
		"subject": team,
		"team": team,
		"detail": f"{ALERT_AT} bank refusals in a row for the team or for {user or 'its users'}; 24 hour wait.",
	}
	return notify_operators("Billing: payment setups locked", [alert])


def clear(team: str) -> None:
	"""Forget the team's failures so far. Only an operator calls this."""
	profile = frappe.get_doc("Billing Profile", team)
	profile.db_set("setup_lock_cleared_at", frappe.utils.now_datetime())
	record_event(profile, "Setup Lock Cleared")


class Lockout:
	"""The run of bank refusals that one team, or one user, has had since the last reset."""

	def __init__(self, failures: list[datetime], now: datetime):
		self.failures = failures
		self.now = now

	@classmethod
	def for_team(cls, team: str) -> "Lockout":
		event = frappe.qb.DocType("Billing Event")
		query = _failure_query(event).where(event.team == team)
		return cls._from_rows(query, _cleared_at(team), _last_success({"team": team}))

	@classmethod
	def for_user(cls, user: str, team: str) -> "Lockout":
		event = frappe.qb.DocType("Billing Event")
		method = frappe.qb.DocType("Payment Method")
		order = frappe.qb.DocType("Top-up Order")
		query = (
			_failure_query(event)
			.left_join(method)
			.on((event.subject_doctype == "Payment Method") & (event.subject == method.name))
			.left_join(order)
			.on((event.subject_doctype == "Top-up Order") & (event.subject == order.name))
			.where((method.owner == user) | (order.owner == user))
		)
		return cls._from_rows(query, _cleared_at(team), _last_success({"owner": user}))

	@classmethod
	def _from_rows(cls, query, *resets) -> "Lockout":
		now = frappe.utils.now_datetime()
		since = max([now - LOOKBACK, *(frappe.utils.get_datetime(r) for r in resets if r)])
		event = frappe.qb.DocType("Billing Event")
		rows = query.where(event.occurred_at > since).run(as_dict=True)
		return cls([row.occurred_at for row in rows if _is_counted(row)], now)

	def get_count(self) -> int:
		"""Failures in the current run: each within seven days of the next, the newest within seven days of now."""
		count, newer = 0, self.now
		for failed_at in self.failures:
			if newer - failed_at > RESET_AFTER:
				break
			count, newer = count + 1, failed_at
		return count

	def get_wait(self) -> timedelta | None:
		count = self.get_count()
		if not count:
			return None
		remaining = self.failures[0] + SCHEDULE[min(count, ALERT_AT)] - self.now
		return remaining if remaining > timedelta(0) else None


def _failure_query(event):
	return (
		frappe.qb.from_(event)
		.select(event.occurred_at, event.reason, event.payload)
		.where(event.event_type.isin(FAILURE_EVENTS))
		.where(event.outcome == billing_event.FAILED)
		.orderby(event.occurred_at, order=Order.desc)
	)


def _is_person(user: str | None) -> bool:
	return bool(user) and user not in _UNATTRIBUTED_USERS


def _cleared_at(team: str):
	return frappe.db.get_value("Billing Profile", team, "setup_lock_cleared_at")


def _last_success(filters: dict):
	"""When the newest method these filters match was proven to work."""
	return frappe.db.get_value(
		"Payment Method",
		{**filters, "validated_at": ["is", "set"]},
		"validated_at",
		order_by="validated_at desc",
	)


def _is_counted(row) -> bool:
	payload = frappe.parse_json(row.payload) if row.payload else {}
	return decline.is_bank_refusal(row.reason, (payload or {}).get("decline_code"))
