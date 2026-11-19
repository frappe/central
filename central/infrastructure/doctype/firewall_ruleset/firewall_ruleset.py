from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document
from pydantic import ValidationError

from central.server_models import FirewallChange, FirewallRule


class FirewallRuleset(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		last_sync_error: DF.SmallText | None
		rules: DF.JSON
		team: DF.Link
		title: DF.Data
	# end: auto-generated types

	"""Named firewall rules owned by a Team. Every server that uses the ruleset gets its rules."""

	def validate(self) -> None:
		self.title = (self.title or "").strip()
		if not self.title:
			frappe.throw(_("Enter a name for the ruleset."))
		if frappe.db.exists(
			"Firewall Ruleset", {"team": self.team, "title": self.title, "name": ["!=", self.name]}
		):
			frappe.throw(_("The team already has a ruleset with this name."))

		self.rules = json.dumps(self.firewall_change.model_dump(exclude={"enabled"}), sort_keys=True)

	def on_update(self) -> None:
		if self.get_doc_before_save() and self.has_value_changed("rules"):
			self.queue_sync()

	def on_trash(self) -> None:
		if self.get_server_names():
			frappe.throw(_("Detach this ruleset from its servers before deleting it."))

	@property
	def firewall_change(self) -> FirewallChange:
		"""Both rule lists, validated. The firewall state stays what each server has."""
		rules = frappe.parse_json(self.rules) or {}
		try:
			return FirewallChange.model_validate(
				{"inbound": rules.get("inbound") or [], "outbound": rules.get("outbound") or []}
			)
		except ValidationError as error:
			frappe.throw(error.errors(include_input=False)[0]["msg"].removeprefix("Value error, "))

	def get_server_names(self) -> list[str]:
		return frappe.get_all(
			"Virtual Machine",
			filters=[
				["Server Firewall Ruleset", "firewall_ruleset", "=", self.name],
				["status", "!=", "Terminated"],
			],
			pluck="name",
			distinct=True,
		)

	@frappe.whitelist(methods=["POST"])
	def retry_sync(self) -> None:
		"""Operator action: send the rules to every server of this ruleset again."""
		self.check_permission("write")
		self.queue_sync()

	def queue_sync(self) -> None:
		frappe.enqueue_doc(self.doctype, self.name, "sync", queue="long", enqueue_after_commit=True)

	def sync(self) -> None:
		"""Send the rules to each server. One failed server does not stop the others."""
		failed: list[str] = []
		for name in self.get_server_names():
			try:
				frappe.get_doc("Virtual Machine", name).sync_firewall_rulesets()
			# The region refused the rules, or the server's rulesets now hold too many addresses.
			except frappe.ValidationError:
				frappe.log_error(title=f"Firewall ruleset sync failed for {name}")
				failed.append(name)

		self.last_sync_error = (
			_("Could not update {0}. Retry synchronization.").format(", ".join(failed)) if failed else None
		)
		self.save()


def get_merged_firewall(names: list[str]) -> FirewallChange:
	"""The rules of several rulesets as one firewall, with each rule once."""
	inbound: dict[tuple, FirewallRule] = {}
	outbound: dict[tuple, FirewallRule] = {}
	for name in names:
		change = frappe.get_doc("Firewall Ruleset", name).firewall_change
		for merged, rules in ((inbound, change.inbound), (outbound, change.outbound)):
			for rule in rules:
				merged.setdefault((rule.protocol, rule.ports, tuple(sorted(rule.cidrs))), rule)

	# A region refuses a firewall with more than 50 address entries.
	if sum(len(rule.cidrs) for rule in (*inbound.values(), *outbound.values())) > 50:
		frappe.throw(
			_("These rulesets hold more than 50 addresses together. Use fewer rulesets, or shorten one.")
		)

	return FirewallChange(inbound=list(inbound.values()), outbound=list(outbound.values()))


def on_doctype_update() -> None:
	frappe.db.add_unique("Firewall Ruleset", ["team", "title"])
