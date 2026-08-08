# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Subscription(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account_standing: DF.Literal["Current", "Past Due", "Suspended"]
		asset_id: DF.Link | None
		billing_cycle: DF.Literal["Monthly", "Annual"]
		cluster: DF.ReadOnly | None
		default_payment_method: DF.Link | None
		enabled: DF.Check
		gateway: DF.Link | None
		includes: DF.Table
		plan: DF.Link | None
		pricing_mode: DF.Literal["Preset", "Composed"]
		service_subject: DF.Data | None
		start_date: DF.Date | None
		sub_category: DF.Link | None
		team: DF.Link
	# end: auto-generated types

	def validate(self):
		self.validate_duplicate_subscription()
		self.validate_duplicate_service_subject()

	def validate_duplicate_subscription(self):
		"""Block a second enabled subscription for the same team + asset.

		A team can hold at most one active subscription per asset; re-subscribing
		the same asset must go through `change_plan`/`cancel_subscription`, not a
		second Subscription doc.
		"""
		if not (self.enabled and self.team and self.asset_id):
			return

		duplicate = frappe.db.exists(
			"Subscription",
			{
				"name": ["!=", self.name],
				"team": self.team,
				"asset_id": self.asset_id,
				"enabled": 1,
			},
		)
		if duplicate:
			frappe.throw(
				_("Team {0} already has an active subscription ({1}) for asset {2}.").format(
					self.team, duplicate, self.asset_id
				),
				frappe.DuplicateEntryError,
			)

	def validate_duplicate_service_subject(self):
		"""One active subscription per synthesized service subject (ADR 0013/0015).

		The subject already encodes (team, service-plan, cluster), so this makes
		provisioning idempotent: a second subscribe of the same service on the same
		cluster must reuse the existing subject, not open a parallel one."""
		if not (self.enabled and self.service_subject):
			return

		duplicate = frappe.db.exists(
			"Subscription",
			{
				"name": ["!=", self.name],
				"service_subject": self.service_subject,
				"enabled": 1,
			},
		)
		if duplicate:
			frappe.throw(
				_("Service subject {0} already has an active subscription ({1}).").format(
					self.service_subject, duplicate
				),
				frappe.DuplicateEntryError,
			)

	def after_insert(self):
		"""Log a 'Created' Subscription Change, with a rate snapshot, on insert.

		The segment opens at the subscription's start_date (when billing begins),
		not the wall-clock insert time, so a backdated subscription bills its real
		period."""
		rate, currency = self.resolve_rate_snapshot()
		effective_at = (
			frappe.utils.get_datetime(self.start_date) if self.start_date else frappe.utils.now_datetime()
		)
		frappe.get_doc(
			{
				"doctype": "Subscription Change",
				"subscription": self.name,
				"change_type": "Created",
				"new_value": self.segment_label(),
				"locked_rate": rate,
				"currency": currency,
				"effective_at": effective_at,
				"changed_by": frappe.session.user,
			}
		).insert(ignore_permissions=True)

	def on_update(self):
		# on_update fires during the initial insert too; after_insert already logs the
		# 'Created' segment, so only open a new segment on a genuine later edit that
		# changes what is billed (the preset plan, the mode, the profile, or the
		# composition) — a payment-method or standing edit is not a price event.
		if not self.flags.in_insert and self._billing_segment_changed():
			self.log_plan_change()

	def _billing_segment_changed(self) -> bool:
		"""Whether this save opens a new billing segment (a re-lock, #82)."""
		if any(self.has_value_changed(f) for f in ("plan", "pricing_mode", "sub_category")):
			return True
		before = self.get_doc_before_save()
		if not before:
			return False
		from central.billing.catalog.composition import composition_quantities

		return composition_quantities(before.includes or []) != composition_quantities(self.includes or [])

	def log_plan_change(self):
		"""Log a 'Plan Changed' Subscription Change, with a fresh rate snapshot — the
		`changed`-event re-lock: it closes the open segment and opens a new one at
		today's rate (ADR 0010). Used by both a preset plan change and a composed
		resize / mode switch (#82)."""
		previous = self.get_doc_before_save()
		rate, currency = self.resolve_rate_snapshot()
		frappe.get_doc(
			{
				"doctype": "Subscription Change",
				"subscription": self.name,
				"change_type": "Plan Changed",
				"old_value": self._segment_label(previous) if previous else None,
				"new_value": self.segment_label(),
				"locked_rate": rate,
				"currency": currency,
				"effective_at": frappe.utils.now_datetime(),
				"changed_by": self.flags.changed_by or frappe.session.user,
			}
		).insert(ignore_permissions=True)

	def segment_label(self) -> str | None:
		"""What this subscription's current billed segment shows (see `_segment_label`)."""
		return self._segment_label(self)

	@staticmethod
	def _segment_label(doc) -> str | None:
		"""A segment's description: the Plan for a preset, the composition for a
		composed config (e.g. 'Custom: 2 vCPU · 4 GB RAM · 40 GB disk'). Stored on the
		change row's `new_value`, which the invoice line surfaces as its description."""
		if doc.pricing_mode == "Composed":
			from central.billing.catalog.composition import config_summary

			summary = config_summary(doc.includes)
			return f"Custom: {summary}" if summary else "Custom config"
		return doc.plan

	def resolve_rate_snapshot(self) -> tuple[float | None, str | None]:
		"""The rate + currency to snapshot onto a Subscription Change now.

		Billing reads this snapshot forever for the segment it opens — never the
		live catalog rate — so re-resolving it later must not change past charges. A
		preset snapshots its Plan's flat rate; a composed config snapshots the
		whole-config rate `Σ(qty × component_rate)`, frozen as one number (ADR 0010).
		"""
		currency = frappe.db.get_value("Billing Profile", self.team, "currency")
		if not currency:
			return None, None
		# A VM subscription resolves its cluster off the Asset; a team-level service
		# subject (no Asset) carries its cluster on the Subscription itself (ADR 0013).
		cluster = (
			frappe.db.get_value("Asset", self.asset_id, "cluster") if self.asset_id else None
		) or self.cluster

		if self.pricing_mode == "Composed":
			from central.billing.catalog.pricing import resolve_config_rate

			return resolve_config_rate(self.includes, currency, cluster), currency

		if not self.plan:
			return None, None
		rate = frappe.get_doc("Plan", self.plan).get_rate(currency, cluster)
		return rate, currency

	def enable(self):
		"""Mark this subscription enabled and save."""
		self.enabled = 1
		self.save(ignore_permissions=True)

	def disable(self):
		"""Mark this subscription disabled and save."""
		self.enabled = 0
		self.save(ignore_permissions=True)


def create_subscription(asset_id: str):
	"""Create an enabled Subscription for an Asset, using its team + plan."""
	asset = frappe.get_doc("Asset", asset_id)
	return frappe.get_doc(
		{
			"doctype": "Subscription",
			"team": asset.team,
			"asset_id": asset.name,
			"plan": asset.plan,
			"enabled": 1,
		}
	).insert(ignore_permissions=True)
