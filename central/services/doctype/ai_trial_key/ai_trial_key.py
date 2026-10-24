# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING, Self

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, now_datetime

from central.integrations.grove import GroveClient

if TYPE_CHECKING:
	from central.infrastructure.doctype.resource_action.resource_action import ResourceAction
	from central.services.doctype.ai_settings.ai_settings import AISettings

# The one Grove Team every trial key is minted under.
TRIAL_TEAM = "Central Trial"
# One batch per run keeps the job short.
REFILL_BATCH_SIZE = 50
# A revoke Grove refused is tried again once the record has sat this long.
RETRY_AFTER_MINUTES = 60


class AITrialKey(Document):
	"""One Grove key minted ahead under Central Trial and held here with its secret, until a
	free-trial server takes it in its boot config. Central revokes it when that creation fails or
	the server is terminated; Grove retires it on its own, Trial Key Expiry after its first use."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Password | None
		assigned_at: DF.Datetime | None
		gateway_url: DF.Data | None
		geography: DF.Data | None
		grove_key: DF.Data
		resource_action: DF.Link | None
		server: DF.Link | None
		status: DF.Literal["Available", "Assigned", "Revoking", "Revoked"]
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
			model_group=settings.trial_model_group or None,
			cap=cint(settings.trial_key_cap),
			expiry=settings.trial_key_expiry,
			# A key waits in the pool before anyone can use it: its clock starts at its first request.
			expiry_from_first_use=True,
		)
		# The refill job inserts it; no customer makes a trial key.
		return frappe.get_doc(
			{
				"doctype": "AI Trial Key",
				"grove_key": minted["name"],
				"geography": minted["geography"],
				"gateway_url": minted["gateway_url"],
				"api_key": minted["api_key"],
			}
		).insert(ignore_permissions=True)

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
					"name": self.grove_key,
					"title": None,
					"geography": self.geography,
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
	def extend_expiry(cls, server: str, days: int) -> bool:
		"""`days` more on the live key of `server`. False when it has none: a paid creation, a pool
		that was empty, or a key revoked when the trial ended."""
		grove_key = frappe.db.get_value("AI Trial Key", {"server": server, "status": "Assigned"}, "grove_key")
		if not grove_key:
			return False
		GroveClient.from_settings().extend_key(TRIAL_TEAM, grove_key, days)
		return True

	@classmethod
	def queue_revoke(cls, **filters) -> None:
		"""Mark the matching ready or assigned keys Revoking and queue their revoke at Grove."""
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
		self.check_permission("write")
		if self.status not in ("Available", "Assigned"):
			frappe.throw(_("Only an available or assigned key can be revoked."))

		self.queue_revoke(name=self.name)

	def on_trash(self) -> None:
		# A record must outlive its live key, so that a failed revoke is retried.
		if self.status != "Revoked":
			frappe.throw(_("Use Revoke Key. Only a revoked key record can be deleted."))

	def revoke_at_grove(self) -> None:
		"""Safe to repeat: Grove answers a revoked key's revoke as done."""
		GroveClient.from_settings().revoke_key(TRIAL_TEAM, self.grove_key)
		self.db_set("status", "Revoked", commit=True)


def revoke_trial_key(name: str) -> None:
	key = frappe.get_doc("AI Trial Key", name)
	if key.status == "Revoking":
		key.revoke_at_grove()


def refill_trial_keys() -> None:
	"""Scheduler, every 5 minutes: try the revokes Grove refused again, then mint the keys the
	pool is missing, up to one batch. Nothing while Central is not enrolled or the pool is off."""
	settings = frappe.get_cached_doc("AI Settings")
	if not settings.is_enrolled or not settings.trial_pool_size:
		return

	retry_revokes()
	missing = settings.trial_pool_size - frappe.db.count("AI Trial Key", {"status": "Available"})
	# The team is the operator's to make at Grove, with its cap window, which is fixed at the
	# insert: until then every mint is refused and logged.
	for _attempt in range(min(missing, REFILL_BATCH_SIZE)):
		try:
			AITrialKey.provision(settings)
		except Exception:
			frappe.log_error(title="Trial key mint failed")
			break


def retry_revokes() -> None:
	"""A Revoking record left alone for an hour is tried again. Why Grove refused is Grove's to say;
	each attempt writes the record, so `modified` spaces the attempts."""
	stale = add_to_date(now_datetime(), minutes=-RETRY_AFTER_MINUTES)
	for name in frappe.get_all(
		"AI Trial Key", filters={"status": "Revoking", "modified": ("<", stale)}, pluck="name"
	):
		key = frappe.get_doc("AI Trial Key", name)
		try:
			key.revoke_at_grove()
		except Exception:
			key.db_set("status", "Revoking")
			frappe.log_error(title=f"Trial key revoke failed for {name}")
