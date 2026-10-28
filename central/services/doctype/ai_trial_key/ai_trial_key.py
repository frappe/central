# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING, Self

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, flt, now_datetime

from central.integrations.grove import GroveClient

if TYPE_CHECKING:
	from central.infrastructure.doctype.resource_action.resource_action import ResourceAction
	from central.services.doctype.ai_settings.ai_settings import AISettings

# The one Grove Team every trial key is minted under.
TRIAL_TEAM = "Central Trial"
# One batch per run keeps the job short.
REFILL_BATCH_SIZE = 50
# A revoke or a hand-over Grove refused is tried again once the record has sat this long.
RETRY_AFTER_MINUTES = 60
# A hand-over that failed this many times is given up and the key revoked: the team mints its own.
MAX_TRANSFER_ATTEMPTS = 3
# The step a waiting status is retried with. A Conversion Failed record waits on its revoke.
RETRIED = {
	"Revoking": "revoke_at_grove",
	"Converting": "convert_at_grove",
	"Conversion Failed": "revoke_at_grove",
}


class AITrialKey(Document):
	"""One Grove key minted ahead under Central Trial and held here with its secret, until a
	free-trial server takes it in its boot config. The key carries no expiry: its life is its
	trial's. Central revokes it when that creation fails, the trial ends or the server is
	terminated, and hands it to the team when the trial converts, so the secret in the server's
	config keeps working; a hand-over that fails for good ends in a revoke too."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Password | None
		assigned_at: DF.Datetime | None
		attempts: DF.Int
		cap: DF.Currency
		gateway_url: DF.Data | None
		geography: DF.Data | None
		grove_key: DF.Data
		last_error: DF.SmallText | None
		resource_action: DF.Link | None
		revoked: DF.Check
		server: DF.Link | None
		status: DF.Literal[
			"Available", "Assigned", "Converting", "Converted", "Conversion Failed", "Revoking", "Revoked"
		]
		team: DF.Link | None
	# end: auto-generated types

	@classmethod
	def provision(cls, settings: AISettings) -> Self:
		"""Mint one key into the pool. A crash between the mint and the insert leaves a capped,
		untitled key under the trial team that no record names; Grove Desk shows it."""
		minted = GroveClient.from_settings().provision_key(
			team=TRIAL_TEAM,
			title=None,
			geography=settings.trial_key_geography,
			cap=cint(settings.trial_key_cap),
		)
		return frappe.get_doc(
			{
				"doctype": "AI Trial Key",
				"grove_key": minted["name"],
				"geography": minted["geography"],
				"gateway_url": minted["gateway_url"],
				"cap": minted["cap"],
				"api_key": minted["api_key"],
			}
		).insert()

	@classmethod
	def assign(cls, action: ResourceAction) -> Self | None:
		"""The oldest ready key for a free-trial creation; none for a paid one or an empty pool.
		A retried creation keeps its key."""
		if not action.is_free_trial:
			return None

		if name := frappe.db.get_value("AI Trial Key", {"resource_action": action.name, "status": "Assigned"}):
			return frappe.get_doc("AI Trial Key", name)

		name = frappe.db.get_value(
			"AI Trial Key",
			{"status": "Available"},
			order_by="creation asc",
			for_update=True,
			skip_locked=True,
		)
		if not name:
			return None

		key = frappe.get_doc("AI Trial Key", name)
		key.db_set(
			{
				"status": "Assigned",
				"resource_action": action.name,
				"team": action.team,
				"assigned_at": now_datetime(),
			}
		)

		return key

	def get_site_config(self) -> dict:
		"""The common_site_config entry a site's apps read a Grove key from: the shape Pilot
		writes for a team's own keys."""
		return {
			"ai_keys": [
				{
					"gateway_url": self.gateway_url,
					"api_key": self.get_password("api_key"),
				}
			]
		}

	@classmethod
	def link_server(cls, resource_action: str, server: str) -> None:
		frappe.db.set_value(
			"AI Trial Key", {"resource_action": resource_action, "status": "Assigned"}, "server", server
		)


	@classmethod
	def queue_convert(cls, server: str) -> bool:
		"""Hand the live key of `server` to its team in the background: the trial converted. False
		when it has none: a paid creation, a pool that was empty, or a key revoked when the trial
		ended."""
		name = frappe.db.get_value("AI Trial Key", {"server": server, "status": "Assigned"})
		if not name:
			return False
		frappe.db.set_value("AI Trial Key", name, "status", "Converting")
		frappe.enqueue(
			"central.services.doctype.ai_trial_key.ai_trial_key.convert_trial_key",
			name=name,
			enqueue_after_commit=True,
		)
		return True

	def convert_at_grove(self) -> None:
		"""Hand the key to the team whose trial converted: AI on for the team, which registers it at
		Grove, then Grove moves the key, titled by the site. Safe to repeat: Grove answers a key the
		team already holds as it is."""
		from central.services.ai import enable

		site = self.converted_site()
		enable(site.team)
		GroveClient.from_settings().transfer_key(TRIAL_TEAM, self.grove_key, site.team, site.name)
		self.db_set({"status": "Converted", "team": site.team, "last_error": None}, commit=True)

	def converted_site(self) -> frappe._dict:
		"""The converted trial site on this key's server: its name is the key's title at Grove."""
		return frappe.db.get_value(
			"Site", {"server": self.server, "trial_state": "Converted"}, ["name", "team"], as_dict=True
		)

	def try_at_grove(self) -> None:
		"""One try at the step the status waits on. A revoke is tried for as long as it takes (it
		must land); a hand-over is given up after MAX_TRANSFER_ATTEMPTS and the key revoked instead.
		A failed try writes the record — Grove's answer as `last_error`, and `modified`, which spaces
		the retries."""
		try:
			getattr(self, RETRIED[self.status])()
		except Exception as error:
			frappe.log_error(title=f"Trial key {self.status.lower()} failed for {self.name}")
			answer = str(error) or type(error).__name__
			if RETRIED[self.status] == "revoke_at_grove":
				self.db_set({"status": self.status, "last_error": answer})
				return
			self.note_failed_attempt(answer)

	def note_failed_attempt(self, answer: str) -> None:
		"""At the last attempt the record stops: Conversion Failed, with Grove's last answer as
		`last_error`, and the key is revoked — the trial team's no longer, never the customer's.
		`revoked` says when that landed; the status keeps the failure."""
		attempts = cint(self.attempts) + 1
		if attempts < MAX_TRANSFER_ATTEMPTS:
			self.db_set({"status": "Converting", "attempts": attempts, "last_error": answer})
			return
		self.db_set({"status": "Conversion Failed", "attempts": attempts, "last_error": answer})
		frappe.enqueue(
			"central.services.doctype.ai_trial_key.ai_trial_key.revoke_trial_key",
			name=self.name,
			enqueue_after_commit=True,
		)

	@property
	def is_revoke_pending(self) -> bool:
		return self.status == "Revoking" or (self.status == "Conversion Failed" and not self.revoked)

	@classmethod
	def queue_revoke(cls, **filters) -> None:
		"""Mark the matching ready or assigned keys Revoking and queue their revoke at Grove. A
		Converted key is the team's now; a Conversion Failed one is already on its way out."""
		for name in frappe.get_all(
			"AI Trial Key",
			filters={**filters, "status": ("in", ("Available", "Assigned"))},
			pluck="name",
		):
			frappe.db.set_value("AI Trial Key", name, "status", "Revoking")
			frappe.enqueue(
				"central.services.doctype.ai_trial_key.ai_trial_key.revoke_trial_key",
				name=name,
				enqueue_after_commit=True,
			)

	@frappe.whitelist(methods=["POST"])
	def revoke(self) -> None:
		if self.status not in ("Available", "Assigned"):
			frappe.throw(_("Only an available or assigned key can be revoked."))

		self.queue_revoke(name=self.name)

	@frappe.whitelist(methods=["POST"])
	def raise_cap(self, cap: float) -> None:
		"""Lift the cap of a running trial's key at Grove. Only an Assigned record is one: End,
		conversion and termination all move it on, and a converted key's cap is the team's to set."""
		if self.status != "Assigned":
			frappe.throw(_("Only the key of a running trial can have its cap raised."))
		if flt(cap) <= flt(self.cap):
			frappe.throw(_("The cap is {0} USD already; enter more.").format(self.cap))

		GroveClient.from_settings().update_caps(TRIAL_TEAM, {self.grove_key: flt(cap)})
		self.db_set("cap", flt(cap))

	def on_trash(self) -> None:
		# A record must outlive its live key, so that a failed revoke is retried.
		if self.status != "Revoked" and not (self.status == "Conversion Failed" and self.revoked):
			frappe.throw(_("Use Revoke Key. Only a revoked key record can be deleted."))

	def revoke_at_grove(self) -> None:
		"""Safe to repeat: Grove answers a revoked key's revoke as done. A Conversion Failed record
		keeps its status and ticks `revoked`."""
		GroveClient.from_settings().revoke_key(TRIAL_TEAM, self.grove_key)
		if self.status == "Conversion Failed":
			self.db_set({"revoked": 1, "last_error": None}, commit=True)
		else:
			self.db_set({"status": "Revoked", "last_error": None}, commit=True)


def revoke_trial_key(name: str) -> None:
	key = frappe.get_doc("AI Trial Key", name)
	if key.is_revoke_pending:
		key.revoke_at_grove()


def convert_trial_key(name: str) -> None:
	key = frappe.get_doc("AI Trial Key", name)
	if key.status == "Converting":
		key.try_at_grove()


def refill_trial_keys() -> None:
	"""Scheduler, every 5 minutes: try the revokes and hand-overs Grove refused again, then mint
	the keys the pool is missing, up to one batch. Nothing while Central is not enrolled; the
	retries run with the pool off too, the mint does not."""
	settings = frappe.get_cached_doc("AI Settings")
	if not settings.is_enrolled:
		return

	retry_stale()
	if not settings.trial_pool_size:
		return
	missing = settings.trial_pool_size - frappe.db.count("AI Trial Key", {"status": "Available"})
	# The team is the operator's to make at Grove, with its cap window, which is fixed at the
	# insert: until then every mint is refused and logged.
	for _attempt in range(min(missing, REFILL_BATCH_SIZE)):
		try:
			AITrialKey.provision(settings)
		except Exception:
			frappe.log_error(title="Trial key mint failed")
			break


def retry_stale() -> None:
	"""A Revoking, Converting or unrevoked Conversion Failed record left alone for an hour is tried
	again. Why Grove refused is Grove's to say; each attempt writes the record, so `modified` spaces
	the attempts."""
	stale = add_to_date(now_datetime(), minutes=-RETRY_AFTER_MINUTES)
	waiting = frappe.get_all(
		"AI Trial Key",
		filters={"status": ("in", ("Revoking", "Converting")), "modified": ("<", stale)},
		pluck="name",
	)
	failed = frappe.get_all(
		"AI Trial Key",
		filters={"status": "Conversion Failed", "revoked": 0, "modified": ("<", stale)},
		pluck="name",
	)
	for name in waiting + failed:
		frappe.get_doc("AI Trial Key", name).try_at_grove()
