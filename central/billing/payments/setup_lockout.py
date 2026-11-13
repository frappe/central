# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The wait after repeated failed payment method setups and top-ups.

The lock is read from the failure Billing Events in FAILURE_EVENTS and the decline
code in their `payload`. Any retention job must keep these events, with their payload,
for at least LOOKBACK (77 days: 10 failures, each within 7 days of the next)."""

import math
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.query_builder.functions import Max

from central.billing.doctype.billing_event import billing_event
from central.billing.payments import decline
from central.billing.states import record_event

SETUP_FAILED_EVENT = "Payment Method Setup Failed"
METHOD_FAILED_EVENT = "Payment Method Failed"
TOP_UP_DECLINED_EVENT = "Top-up Order Declined"
FAILURE_EVENTS = (SETUP_FAILED_EVENT, METHOD_FAILED_EVENT, TOP_UP_DECLINED_EVENT)
ALERTED_EVENT = "Setup Lock Alerted"

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
ALERT_COOLDOWN = timedelta(hours=24)

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
	if is_person(user):
		lockouts.append(Lockout.for_user(user, team))
	waits = [wait for wait in (lockout.get_wait() for lockout in lockouts) if wait]
	return max(waits, default=None)


def is_anyone_waiting(team: str) -> bool:
	"""True while the team, or any member of it, must wait. Clear Setup Lock ends both."""
	members = frappe.get_all("Team Member", {"parenttype": "Team", "parent": team}, pluck="user")
	lockouts = [Lockout.for_team(team), *Lockout.for_users(members, team).values()]
	return any(lockout.get_wait() for lockout in lockouts)


def wait_message(wait: timedelta) -> str:
	"""The wait, said to the customer, rounded up to the minute."""
	hours, minutes = divmod(_whole_minutes(wait), 60)
	messages = {
		(0, 1): _("Too many failed attempts. Try again in 1 minute."),
		(0, 2): _("Too many failed attempts. Try again in {minutes} minutes."),
		(1, 0): _("Too many failed attempts. Try again in 1 hour."),
		(1, 1): _("Too many failed attempts. Try again in 1 hour 1 minute."),
		(1, 2): _("Too many failed attempts. Try again in 1 hour {minutes} minutes."),
		(2, 0): _("Too many failed attempts. Try again in {hours} hours."),
		(2, 1): _("Too many failed attempts. Try again in {hours} hours 1 minute."),
		(2, 2): _("Too many failed attempts. Try again in {hours} hours {minutes} minutes."),
	}
	return messages[(min(hours, 2), min(minutes, 2))].format(hours=hours, minutes=minutes)


def note_failure(team: str, user: str | None, failure_code: str | None, decline_code: str | None = None):
	"""After a bank refusal that makes the team or the user wait, close their open gateway
	setups and top-ups, and tell the operators when it starts the longest wait.

	The team's run is reported first; a user's run only when the team's has not reached it."""
	if not decline.is_bank_refusal(failure_code, decline_code):
		return
	if wait_for(team, user):
		_enqueue_close(team, user)
	if Lockout.for_team(team).get_count() == ALERT_AT:
		_enqueue_alert(team, None)
	elif is_person(user) and Lockout.for_user(user, team).get_count() == ALERT_AT:
		_enqueue_alert(team, user)


def alert_operators(team: str, user: str | None = None) -> None:
	"""Record the lock alert and send it to the billing operators once this job commits,
	once a day at most for the same team, or the same user in that team."""
	# Locked, so two failures that both reach the alert record it once.
	frappe.db.get_value("Team", team, "name", for_update=True)
	if _is_recently_alerted(team, user or team):
		return
	lockout = Lockout.for_user(user, team) if user else Lockout.for_team(team)
	record_event(_profile(team), ALERTED_EVENT, correlation=user or team, reason=user)
	# Sent only after the record commits, so a second job skips it even if the send fails.
	frappe.enqueue(
		"central.billing.payments.setup_lockout.send_alert",
		alert=lock_alert(team, user, lockout),
		enqueue_after_commit=True,
	)


def send_alert(alert: dict) -> list[str]:
	"""Send one recorded lock alert. A failed send goes to the Error Log, not to a retry."""
	from central.billing.platform.alerts import notify_operators

	try:
		return notify_operators("Billing: payment setups locked", [alert])
	except Exception:
		frappe.log_error(title="Billing setup lock alert not sent")
		return []


def lock_alert(team: str, user: str | None, lockout: "Lockout") -> dict:
	"""The operator alert for one lock: who, how many failures, how long, and how to clear it."""
	team_name = frappe.db.get_value("Team", team, "team_name") or team
	count = lockout.get_count()
	if user:
		who = f"User {user} had {count} failed attempts in a row across their teams, the latest in team {team_name} ({team}),"
		clear_scope = " The clear lets them try again in this team only."
	else:
		who, clear_scope = f"Team {team_name} ({team}) had {count} failed attempts in a row", ""
	return {
		"alert": "setup_lockout",
		"meaning": "A team or user had too many payment method setups or top-ups refused by the bank.",
		"doctype": "Billing Profile",
		"subject": team,
		"team": team,
		"detail": (
			f"{who} and {_wait_phrase(lockout)}. "
			f"To let them try now, open the Billing Profile and click Clear Setup Lock.{clear_scope}"
		),
	}


def clear(team: str) -> None:
	"""Forget the failures so far in this team, of the team and of its members. Only an operator calls this."""
	profile = frappe.get_doc("Billing Profile", team)
	profile.db_set("setup_lock_cleared_at", frappe.utils.now_datetime())
	record_event(profile, "Setup Lock Cleared")


class Lockout:
	"""The run of bank refusals that one team, or one user, has had since the last reset.

	A run resets at the latest of: the operator's clear on the team's Billing Profile, a
	validated method, and a paid top-up. For a team, any method or top-up of the team
	counts. For a user, only a method or top-up that user made counts, in any team; so
	another member's paid top-up resets the team's run but not that user's own run."""

	def __init__(self, failures: list[datetime], now: datetime):
		self.failures = failures
		self.now = now

	@classmethod
	def for_team(cls, team: str) -> "Lockout":
		now = frappe.utils.now_datetime()
		orders = frappe.qb.DocType("Top-up Order")
		team_orders = frappe.qb.from_(orders).select(orders.name).where(orders.team == team)
		paid_at = max(_credited_at(team_orders).values(), default=None)
		since = _since(now, _cleared_at(team), _last_method({"team": team}), paid_at)
		event = frappe.qb.DocType("Billing Event")
		rows = (
			_failure_query(event).where(event.team == team).where(event.occurred_at > since).run(as_dict=True)
		)
		return cls([row.occurred_at for row in rows if _is_counted(row)], now)

	@classmethod
	def for_user(cls, user: str, team: str) -> "Lockout":
		return cls.for_users([user], team)[user]

	@classmethod
	def for_users(cls, users: list[str], team: str) -> dict[str, "Lockout"]:
		"""Each user's run, read from the methods and top-ups they own, in a fixed number of queries."""
		users = sorted({user for user in users if user})
		if not users:
			return {}
		now = frappe.utils.now_datetime()
		subjects = _OwnedSubjects(users)
		failures = subjects.get_failures(now - LOOKBACK)
		cleared_at = _cleared_at(team)
		lockouts = {}
		for user in users:
			since = _since(now, cleared_at, *subjects.get_resets(user))
			counted = [
				row.occurred_at for row in failures[user] if row.occurred_at > since and _is_counted(row)
			]
			lockouts[user] = cls(counted, now)
		return lockouts

	def get_count(self) -> int:
		"""Failures in the current run: each within seven days of the next, the newest within seven days of now."""
		count, newer = 0, self.now
		for failed_at in self.failures:
			if newer - failed_at > RESET_AFTER:
				break
			count, newer = count + 1, failed_at
		return count

	def get_ends_at(self) -> datetime | None:
		"""When the wait after the latest failure ends. None with no run."""
		count = self.get_count()
		return self.failures[0] + SCHEDULE[min(count, ALERT_AT)] if count else None

	def get_wait(self) -> timedelta | None:
		ends_at = self.get_ends_at()
		return ends_at - self.now if ends_at and ends_at > self.now else None


class _OwnedSubjects:
	"""The Payment Methods and Top-up Orders some users own, and their failure and reset events."""

	def __init__(self, users: list[str]):
		self.users = users
		self.methods = frappe.get_all(
			"Payment Method", {"owner": ["in", users]}, ["name", "owner", "validated_at"]
		)
		self.orders = frappe.get_all("Top-up Order", {"owner": ["in", users]}, ["name", "owner"])
		self.owner_of = {
			**{("Payment Method", row.name): row.owner for row in self.methods},
			**{("Top-up Order", row.name): row.owner for row in self.orders},
		}
		self.paid_at = _credited_at([row.name for row in self.orders]) if self.orders else {}

	def get_failures(self, since: datetime) -> dict[str, list]:
		"""Each user's failure events after `since`, newest first."""
		failures = {user: [] for user in self.users}
		if not self.owner_of:
			return failures
		event = frappe.qb.DocType("Billing Event")
		query = _failure_query(event).select(event.subject_doctype, event.subject)
		rows = query.where(self._is_owned(event)).where(event.occurred_at > since).run(as_dict=True)
		for row in rows:
			failures[self.owner_of[(row.subject_doctype, row.subject)]].append(row)
		return failures

	def get_resets(self, user: str) -> tuple:
		"""When the user's newest method was proven, and their newest top-up was paid."""
		validated = [row.validated_at for row in self.methods if row.owner == user and row.validated_at]
		paid = [
			self.paid_at[row.name] for row in self.orders if row.owner == user and row.name in self.paid_at
		]
		return max(validated, default=None), max(paid, default=None)

	def _is_owned(self, event):
		condition = None
		for doctype, rows in (("Payment Method", self.methods), ("Top-up Order", self.orders)):
			if rows:
				part = (event.subject_doctype == doctype) & event.subject.isin([row.name for row in rows])
				condition = part if condition is None else condition | part
		return condition


def _enqueue_close(team: str, user: str | None) -> None:
	# After commit, so the gateway is called only once the failure is on record.
	frappe.enqueue(
		"central.billing.payments.setup_lockout_cancel.close_open",
		team=team,
		user=user,
		enqueue_after_commit=True,
	)


def _enqueue_alert(team: str, user: str | None) -> None:
	frappe.enqueue(
		"central.billing.payments.setup_lockout.alert_operators",
		team=team,
		user=user,
		enqueue_after_commit=True,
	)


def _is_recently_alerted(team: str, party: str) -> bool:
	"""A locking read, so it sees an alert another job committed after this one began."""
	since = frappe.utils.now_datetime() - ALERT_COOLDOWN
	filters = {"team": team, "event_type": ALERTED_EVENT, "correlation": party, "occurred_at": [">", since]}
	return bool(frappe.db.get_value("Billing Event", filters, "name", for_update=True))


def _profile(team: str):
	return frappe._dict(doctype="Billing Profile", name=team, team=team)


def _failure_query(event):
	return (
		frappe.qb.from_(event)
		.select(event.occurred_at, event.reason, event.payload)
		.where(event.event_type.isin(FAILURE_EVENTS))
		.where(event.outcome == billing_event.FAILED)
		.orderby(event.occurred_at, order=Order.desc)
	)


def is_person(user: str | None) -> bool:
	return bool(user) and user not in _UNATTRIBUTED_USERS


def _since(now: datetime, *resets) -> datetime:
	"""The oldest failure time that can still count: the latest reset, or the lookback."""
	return max([now - LOOKBACK, *(frappe.utils.get_datetime(r) for r in resets if r)])


def _cleared_at(team: str):
	return frappe.db.get_value("Billing Profile", team, "setup_lock_cleared_at")


def _last_method(filters: dict):
	"""When the newest method these filters match was proven to work."""
	return frappe.db.get_value(
		"Payment Method",
		{**filters, "validated_at": ["is", "set"]},
		"validated_at",
		order_by="validated_at desc",
	)


def _credited_at(orders) -> dict:
	"""When each of these top-ups (names, or a query of names) was paid: its move to Credited."""
	event = frappe.qb.DocType("Billing Event")
	query = (
		frappe.qb.from_(event)
		.select(event.subject, Max(event.occurred_at))
		.where(event.subject_doctype == "Top-up Order")
		.where(event.subject.isin(orders))
		.where(event.to_state == "Credited")
		.groupby(event.subject)
	)
	return dict(query.run())


def _is_counted(row) -> bool:
	payload = frappe.parse_json(row.payload) if row.payload else {}
	return decline.is_bank_refusal(row.reason, (payload or {}).get("decline_code"))


def _wait_phrase(lockout: "Lockout") -> str:
	ends_at = lockout.get_ends_at()
	if not ends_at or ends_at <= lockout.now:
		return "need not wait now"
	timezone = frappe.utils.get_system_timezone()
	return f"must wait {_duration(ends_at - lockout.now)}, until {ends_at:%d %b %Y %H:%M} {timezone}"


def _whole_minutes(wait: timedelta) -> int:
	return max(1, math.ceil(wait.total_seconds() / 60))


def _duration(wait: timedelta) -> str:
	"""The wait in plain English for operators, such as "1 hour 5 minutes"."""
	hours, minutes = divmod(_whole_minutes(wait), 60)
	parts = [f"{n} {unit}{'' if n == 1 else 's'}" for n, unit in ((hours, "hour"), (minutes, "minute")) if n]
	return " ".join(parts)
