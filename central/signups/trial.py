from functools import cached_property
from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	cint,
	date_diff,
	flt,
	formatdate,
	get_datetime,
	getdate,
	now_datetime,
	nowdate,
)

from central.iam import can
from central.infrastructure.doctype.resource_action.resource_action import PENDING_STATES, ResourceAction
from central.infrastructure.doctype.site.site import Site
from central.notification.engine import queue_event
from central.services.doctype.ai_trial_key.ai_trial_key import AITrialKey
from central.signups.eligibility import has_active_payment_method
from central.signups.funnel import capture_trial_event

OPEN_STATES = ("Active", "Ended")

# The states a trial may move to from each state. Converted and Deleted are final.
TRANSITIONS = {
	"": {"Active", "Converted"},
	"Active": {"Active", "Ended", "Converted", "Deleted"},
	"Ended": {"Active", "Ended", "Converted", "Deleted"},
	"Converted": set(),
	"Deleted": set(),
}


class InvalidTrialTransition(frappe.ValidationError):
	"""A trial state change that the lifecycle does not allow."""


class TrialSettings:
	"""The trial clock of one product: Central Settings, with the Product's own days when it sets them."""

	def __init__(self, product: str | None = None):
		settings = frappe.get_cached_doc("Central Settings")
		product_days = (
			frappe.db.get_value("Product", product, ["trial_days", "trial_deletion_days"], as_dict=True)
			if product
			else None
		) or frappe._dict()

		self.days = cint(product_days.trial_days) or cint(settings.trial_days)
		self.deletion_days = cint(product_days.trial_deletion_days) or cint(settings.trial_deletion_days)
		self.notice_days = cint(settings.trial_notice_days)


class Trial:
	"""The free trial of one Site: its clock, its emails and its conversion to a paid site.

	Every state change goes through `move_to`, which refuses a change that `TRANSITIONS` does not allow."""

	def __init__(self, site: Site):
		self.site = site

	@classmethod
	def load(cls, site: str, for_update: bool = False) -> "Trial":
		return cls(frappe.get_doc("Site", site, for_update=for_update))

	@classmethod
	def find_open(cls, server: str) -> "Trial | None":
		"""The open trial on `server`, or None."""
		site = frappe.db.get_value("Site", {"server": server, "trial_state": ["in", OPEN_STATES]})
		return cls.load(site) if site else None

	@cached_property
	def settings(self) -> TrialSettings:
		return TrialSettings(self.site.product)

	@property
	def state(self) -> str:
		return self.site.trial_state or ""

	@property
	def is_open(self) -> bool:
		return self.state in OPEN_STATES

	@property
	def address(self) -> str:
		"""The site's address as the customer knows it, the same one the notification emails name."""
		return urlsplit(self.site.routed_url).hostname

	def move_to(self, state: str, **values) -> None:
		"""Set the trial state, with the fields that change with it. A new site is not saved yet."""
		if state not in TRANSITIONS[self.state]:
			frappe.throw(
				_("A trial in state {0} cannot move to {1}.").format(self.state or _("none"), state),
				InvalidTrialTransition,
			)

		values = {"trial_state": state, **values}
		if self.site.is_new():
			self.site.update(values)
		else:
			self.site.db_set(values)

	def start(self) -> None:
		"""Start the clock on a new trial site, before it is saved. It does not wait for the
		customer to open the site, so an abandoned trial still ends. A team that already pays has no trial."""
		if self.state or not self.site.is_trial():
			return

		if not self.site.get_creation_request().is_free_trial:
			self.move_to("Converted")
			return

		self.move_to("Active", trial_ends_on=add_days(nowdate(), self.settings.days))

	def convert_if_paid(self) -> None:
		"""Convert a new trial site whose team added a payment method before Central recorded it."""
		if self.state == "Active" and has_active_payment_method(self.site.team):
			self.convert_within_limit()

	def convert_within_limit(self) -> bool:
		"""Convert the trial when its plan fits the team's spending limit. Otherwise it stays a
		trial, and the daily job tries again."""
		from central.billing.catalog.subscriptions import remaining_headroom

		team = self.site.team
		# A converted server gets its subscription only when it starts, so its rate is held here.
		frappe.db.get_value("Team", team, "name", for_update=True)
		available = remaining_headroom(team, for_update=True) - get_starting_rate(team)
		if self.get_monthly_rate() > available:
			self.site.db_set("trial_error", _("The site's plan is above the team's spending limit."))
			return False

		self.convert()
		return True

	def keep(self) -> None:
		"""Convert an ended trial that the customer chose to keep, and start its server."""
		if self.state != "Ended":
			frappe.throw(_("Only an ended trial can be kept."))
		if not has_active_payment_method(self.site.team):
			frappe.throw(_("Add a payment method to keep this site."))
		if not self.convert_within_limit():
			frappe.throw(
				_("This site's plan is above your spending limit. Contact support to raise the limit.")
			)

	def convert(self) -> None:
		"""Start billing the site's server, keep it awake, and start it again if the trial stopped it."""
		self.move_to("Converted", trial_error=None, **self.get_cost())
		capture_trial_event(
			"trial_converted",
			self.site.team,
			self.site.product,
			days_in_trial=date_diff(nowdate(), self.site.creation),
		)
		self.notify("trial_converted", "converted")

		# A sleeping server is paid for like a running one. A stopped server gets its subscription
		# when the conversion job starts it.
		server = frappe.get_doc("Virtual Machine", self.site.server)
		if server.status in ("Running", "Paused"):
			server.ensure_subscription_enabled()

		self.enqueue_job(finish_conversion, "trial-convert")

	def finish_conversion(self) -> None:
		"""Turn idle sleep off on the converted trial's server, and start it when it is stopped.
		Safe to repeat, so the daily job runs it again after a failure."""
		from central.integrations.servers import convert_trial_server

		if self.state != "Converted":
			return

		# A resize or a power action also changes the server's power, so two jobs must not race
		# on it. The daily job runs the conversion again once that action is done.
		if frappe.db.exists(
			"Resource Action", {"resource_id": self.site.server, "status": ["in", PENDING_STATES]}
		):
			self.record_error(_("Another action is running on this server. The conversion retries tomorrow."))
			return

		is_stopped = frappe.db.get_value("Virtual Machine", self.site.server, "status") == "Stopped"
		try:
			convert_trial_server(self.site.server, start=is_stopped)
		# This worker boundary records every failure, and the daily job runs the conversion again.
		except Exception:
			frappe.db.rollback()
			self.record_error(_("Central could not start this paid site's server. It retries tomorrow."))
			return

		self.site.db_set("trial_error", None)

	def advance(self, today) -> None:
		"""Run today's step: convert, warn, end, stop or delete."""
		if self.state == "Converted":
			self.enqueue_job(finish_conversion, "trial-convert")
		elif self.is_server_terminated():
			self.delete()
		elif self.state == "Active":
			self.advance_active(today)
		else:
			self.advance_ended(today)

	def advance_active(self, today) -> None:
		if has_active_payment_method(self.site.team) and self.convert_within_limit():
			return

		days_left = date_diff(self.site.trial_ends_on, today)
		if days_left <= 0:
			self.end(today)
		elif days_left <= self.settings.notice_days:
			# A second warning goes out on the last day.
			self.notify("trial_expiring", "last day" if days_left == 1 else "ending")
		elif self.site.ready_at and not self.site.claimed_at and getdate(self.site.ready_at) < today:
			# One reminder, from the day after the site is ready, to a team that has not opened it.
			self.notify("trial_unopened", "unopened")

	def advance_ended(self, today) -> None:
		days_left = date_diff(self.site.trial_deletes_on, today)
		if days_left <= 0:
			self.delete()
		elif frappe.db.get_value("Virtual Machine", self.site.server, "status") != "Stopped":
			self.enqueue_job(stop_server, "trial-stop")

		if 0 < days_left <= self.settings.notice_days:
			self.notify("trial_deletion_soon", "deletion")

	def extend(self, days: int) -> None:
		"""Give the trial `days` more from today, or from its end date when that is later. An ended
		trial runs again and its server starts."""
		if not self.is_open:
			frappe.throw(_("Only an active or ended trial can be extended."))
		if days <= 0:
			frappe.throw(_("Enter a positive number of days."))

		was_ended = self.state == "Ended"
		ends_on = add_days(max(getdate(self.site.trial_ends_on), getdate(nowdate())), days)
		self.move_to(
			"Active", trial_ends_on=ends_on, trial_deletes_on=None, trial_last_notice=None, trial_error=None
		)
		if was_ended:
			self.queue_server_action("start")
		self.extend_key(days)

	def extend_key(self, days: int) -> None:
		"""Best effort: the trial's extension never waits on AI. A trial with no live key (a paid
		creation, an empty pool, or a key revoked when the trial ended) and a refused extend (the
		hourly sweep took the key, unseen here, or Grove unreachable) are noted on the site."""
		# ponytail: one try; a Central-side status with the hourly retry, as Revoking, if a lost
		# extend ever matters.
		try:
			extended = AITrialKey.extend_expiry(self.site.server, days)
		except Exception:
			frappe.log_error(
				"Trial AI key not extended", reference_doctype="Site", reference_name=self.site.name
			)
			self.site.add_comment("Info", _("The trial's AI key was not extended; see the Error Log."))
			return
		if not extended:
			self.site.add_comment("Info", _("The trial has no live AI key to extend."))

	def end(self, today) -> None:
		"""Stop the trial's server, revoke its AI key at Grove and set the day it is terminated. The
		stop job tells the team."""
		if self.state != "Active":
			frappe.throw(_("Only an active trial can be ended."))

		deletes_on = add_days(today, self.settings.deletion_days)
		self.move_to("Ended", trial_deletes_on=deletes_on, trial_error=None)
		AITrialKey.queue_revoke(server=self.site.server)
		capture_trial_event("trial_ended", self.site.team, self.site.product)
		self.enqueue_job(stop_server, "trial-stop")

	def stop_server(self) -> None:
		"""Stop the ended trial's server, unless the team paid in the meantime. The team hears
		that the trial ended only once the server is stopped."""
		from central.integrations.servers import hold_server_stopped

		if self.state != "Ended":
			return

		try:
			hold_server_stopped(frappe.get_doc("Virtual Machine", self.site.server))
		# This worker boundary records every failure, and the daily job sends the stop again.
		except Exception:
			frappe.db.rollback()
			self.record_error(_("Central could not stop this trial's server. It retries tomorrow."))
			return

		# The team can pay while the stop runs. Its server must then run again.
		self.site.reload()
		if self.state == "Converted":
			self.enqueue_job(finish_conversion, "trial-convert")
			return

		self.site.db_set("trial_error", None)
		self.notify("trial_ended", "ended")

	def delete(self) -> None:
		"""Close the trial once its server is terminated. Until then, ask for a terminate each day,
		so a refused terminate is not lost. A protected server is kept: only an operator can
		protect a trial server, and Atlas refuses to terminate it."""
		if not self.is_server_terminated():
			if frappe.db.get_value("Virtual Machine", self.site.server, "is_termination_protected"):
				self.record_error(
					_(
						"Termination protection is on, so this trial's server is kept. Turn it off to delete it."
					)
				)
				return
			if frappe.db.exists(
				"Resource Action",
				{
					"resource_id": self.site.server,
					"action": "terminate",
					"status": ["in", ("Failed", "Timed Out")],
				},
			):
				self.record_error(
					_("Atlas did not terminate this trial's server. Central asks again tomorrow.")
				)
			self.queue_server_action("terminate")
			return

		# A trial that the customer terminated early costs only the days it ran.
		until = min(get_datetime(self.site.trial_ends_on), now_datetime())
		self.move_to("Deleted", trial_error=None, **self.get_cost(until))
		capture_trial_event("trial_deleted", self.site.team, self.site.product)
		self.notify("trial_deleted", "deleted")

	def is_server_terminated(self) -> bool:
		return frappe.db.get_value("Virtual Machine", self.site.server, "status") == "Terminated"

	def get_status(self) -> dict:
		"""The open trial, for the console and the in-app billing panel."""
		has_payment_method = has_active_payment_method(self.site.team)
		return {
			"state": self.state,
			"can_keep": self.state == "Ended"
			and has_payment_method
			and can(frappe.session.user, self.site.team, "billing:manage"),
			"held": self.state == "Active" and has_payment_method,
			"ends_on": self.site.trial_ends_on,
			"days_left": max(date_diff(self.site.trial_ends_on, nowdate()), 0),
			"deletes_on": self.site.trial_deletes_on,
		}

	def get_summary(self) -> dict:
		"""What a new signup shows when this trial is still open."""
		return {
			"site": self.site.name,
			"server": self.site.server,
			"address": self.address,
			"url": self.site.primary_url,
			"product": self.site.product,
			**get_product_branding(self.site.product),
			"state": self.state,
			"ends_on": self.site.trial_ends_on,
			"deletes_on": self.site.trial_deletes_on,
		}

	def get_monthly_rate(self) -> float:
		request = self.site.get_creation_request()
		return flt(request.reserved_monthly_rate) if request else 0.0

	def get_cost(self, until=None) -> dict:
		"""The plan's monthly rate for the days the trial ran. The trial starts when Central records the site."""
		request = self.site.get_creation_request()
		if not request:
			return {}

		days = (
			get_datetime(until or now_datetime()) - get_datetime(self.site.creation)
		).total_seconds() / 86400
		cost = flt(request.reserved_monthly_rate) * max(days, 0) / 30
		currency = frappe.parse_json(request.request_payload or "{}").get("currency")
		return {"trial_cost": cost, "trial_currency": currency}

	def notify(self, event_type: str, notice: str) -> None:
		"""Send each email once. Trial Last Notice records the last one."""
		if self.site.trial_last_notice == notice:
			return

		queue_event(
			self.site.team,
			event_type,
			context=self.get_notice_context(),
			reference_doctype="Site",
			reference_name=self.site.name,
		)
		self.site.db_set("trial_last_notice", notice)

	def get_notice_context(self) -> dict:
		deletes_on = self.site.trial_deletes_on
		return {
			"address": self.address,
			"product": get_product_branding(self.site.product)["product_title"],
			"ends_on": formatdate(self.site.trial_ends_on),
			"deletes_on": formatdate(deletes_on) if deletes_on else "",
			"days_left": date_diff(self.site.trial_ends_on, nowdate()),
			"product_key": self.site.product,
		}

	def queue_server_action(self, action: str) -> None:
		"""Run a start or terminate on the trial's server through the normal action, as the system."""
		server = frappe.get_doc("Virtual Machine", self.site.server)
		if ResourceAction.get_pending(server.name, action):
			return

		ResourceAction.queue(
			action,
			server.team,
			server.region,
			server.title or server.name,
			server=server.name,
			remote_vm_id=server.atlas_vm_id,
			requested_by="Administrator",
		)

	def enqueue_job(self, job, prefix: str) -> None:
		frappe.enqueue(
			job,
			site=self.site.name,
			queue="long",
			enqueue_after_commit=True,
			job_id=f"{prefix}:{self.site.name}",
			deduplicate=True,
		)

	def record_error(self, reason: str) -> None:
		"""Leave the reason on the Site, where the operator looks, and the traceback in an Error Log."""
		frappe.log_error(title="Trial step failed", reference_doctype="Site", reference_name=self.site.name)
		frappe.db.set_value("Site", self.site.name, "trial_error", reason)


def finish_conversion(site: str) -> None:
	"""Background job: see `Trial.finish_conversion`."""
	Trial.load(site).finish_conversion()


def stop_server(site: str) -> None:
	"""Background job: see `Trial.stop_server`."""
	Trial.load(site).stop_server()


def run_trials() -> None:
	"""Daily job: run each open trial's step, and finish a conversion that failed."""
	today = getdate(nowdate())
	open_trials = frappe.get_all(
		"Site", filters={"trial_state": ["in", OPEN_STATES]}, pluck="name", order_by="creation asc"
	)
	failed_conversions = frappe.get_all(
		"Site", filters={"trial_state": "Converted", "trial_error": ["is", "set"]}, pluck="name"
	)
	for name in open_trials + failed_conversions:
		try:
			Trial.load(name, for_update=True).advance(today)
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- keep each site's step if a later one fails
		except Exception:
			frappe.db.rollback()
			Trial.load(name).record_error(_("The daily trial job failed. It retries tomorrow."))
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- leave the reason where the operator looks


def convert_team(team: str) -> None:
	"""Turn the team's active trials into paid sites, oldest first. An ended trial stays stopped
	until the customer keeps it."""
	for name in frappe.get_all(
		"Site", filters={"team": team, "trial_state": "Active"}, pluck="name", order_by="creation asc"
	):
		Trial.load(name, for_update=True).convert_within_limit()


def get_trial_status(server: str, site: str | None = None) -> dict | None:
	"""The open trial of the site on `server`, for the in-app billing panel, or None. A server
	with several sites must name one."""
	filters = {"server": server, "name": site} if site else {"server": server}
	sites = frappe.get_all("Site", filters=filters, pluck="name")
	if len(sites) > 1:
		frappe.throw(_("This server has several sites. Name the site whose trial to show."))
	if not sites:
		return None

	trial = Trial.load(sites[0])
	return trial.get_status() if trial.is_open else None


def get_product_branding(product: str | None) -> dict:
	"""The Product's title and logo as the customer sees them. A plain trial is Frappe Cloud's."""
	branding = frappe.db.get_value("Product", product, ["title", "logo"], as_dict=True) if product else None
	branding = branding or frappe._dict()
	return {"product_title": branding.title or "Frappe Cloud", "product_logo": branding.logo}


def get_server_trial_state(server: str) -> str | None:
	"""The trial state of the server's site. Before Central records the site, a free trial's
	creation request makes it Pending. None for a server with no trial."""
	state = frappe.db.get_value("Site", {"server": server, "trial_state": ["is", "set"]}, "trial_state")
	if state:
		return state

	is_free_trial = frappe.db.get_value(
		"Resource Action", {"server": server, "action": "create"}, "is_free_trial"
	)
	return "Pending" if is_free_trial else None


def is_billing_deferred(server: str) -> bool:
	"""Whether the server runs a free trial site, so it has no subscription yet."""
	return get_server_trial_state(server) in (*OPEN_STATES, "Deleted", "Pending")


def is_conversion_starting(server: str) -> bool:
	"""Whether the server's trial converted but its server has no subscription yet, because the
	conversion job is still starting it."""
	team = frappe.db.get_value("Site", {"server": server, "trial_state": "Converted"}, "team")
	return bool(team) and not frappe.db.exists("Subscription", {"server_id": server, "team": team})


def get_starting_rate(team: str) -> float:
	"""The monthly rate of the team's converted trials whose live servers have no subscription yet."""
	from frappe.query_builder.functions import Sum

	site = frappe.qb.DocType("Site")
	machine = frappe.qb.DocType("Virtual Machine")
	request = frappe.qb.DocType("Resource Action")
	subscription = frappe.qb.DocType("Subscription")
	rate = (
		frappe.qb.from_(site)
		.join(machine)
		.on(machine.name == site.server)
		.join(request)
		.on((request.server == site.server) & (request.action == "create"))
		.left_join(subscription)
		.on((subscription.server_id == site.server) & (subscription.team == site.team))
		.select(Sum(request.reserved_monthly_rate))
		.where(
			(site.team == team)
			& (site.trial_state == "Converted")
			& (machine.status != "Terminated")
			& subscription.name.isnull()
		)
	).run()
	return flt(rate[0][0])
