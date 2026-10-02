# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import hashlib

import frappe
import requests
from frappe import _
from frappe.model.document import Document

PILOT_RELEASE_API = "https://api.github.com/repos/frappe/pilot/releases/tags/{tag}"

# Central's console feature flags. One Single, one Check per flag, read at page
# boot (get_context) so the SPA can hide a whole area before its routes mount.


class CentralSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		central_id: DF.Int
		enable_addons: DF.Check
		enable_email_delivery_service: DF.Check
		enable_llm_service: DF.Check
		enable_object_storage_service: DF.Check
		enable_pdf_print_service: DF.Check
		pilot_auto_release_percent: DF.Int
		pilot_release_tag: DF.Data | None
		pilot_rollout_halted: DF.Check
		pilot_rollout_percent: DF.Int
		trial_idle_shutdown_minutes: DF.Int
		wildcard_domain: DF.Data | None
	# end: auto-generated types

	def validate(self) -> None:
		if self.pilot_release_tag and self.has_value_changed("pilot_release_tag"):
			self.validate_pilot_release_tag()

	def on_update(self) -> None:
		# A new release starts a new rollout, so failures from the last one no longer count.
		if self.has_value_changed("pilot_release_tag"):
			frappe.db.set_value(
				"Pilot Credential", {"pilot_update_error": ("is", "set")}, "pilot_update_error", None
			)

	def validate_pilot_release_tag(self) -> None:
		"""A tag every pilot would fail to download must never reach them."""
		try:
			response = requests.get(PILOT_RELEASE_API.format(tag=self.pilot_release_tag), timeout=10)
		except requests.RequestException:
			frappe.throw(
				_("Could not reach GitHub to check Pilot release {0}.").format(self.pilot_release_tag)
			)

		assets = [asset.get("name") for asset in response.json().get("assets", [])] if response.ok else []
		if "pilot.tar.gz" not in assets:
			frappe.throw(
				_("{0} is not a Pilot release with a pilot.tar.gz asset.").format(self.pilot_release_tag)
			)

	def onload(self) -> None:
		self.set_onload("pilot_rollout", self.pilot_rollout_counts())

	def pilot_rollout_counts(self) -> dict[str, int] | None:
		"""How many pilots are in this release's group, how many run the tag, how many failed.
		The progress bar and the auto release both read this."""
		if not self.pilot_release_tag:
			return None

		credentials = frappe.get_all(
			"Pilot Credential",
			filters={"status": "Active"},
			fields=["pilot_credential_id", "pilot_update_channel", "pilot_version", "pilot_update_error"],
		)
		group = [
			c
			for c in credentials
			if self.in_pilot_rollout_group(c.pilot_credential_id, c.pilot_update_channel or "normal")
		]
		updated = sum(c.pilot_version == self.pilot_release_tag for c in group)
		failed = sum(bool(c.pilot_update_error) for c in group)
		return {"group": len(group), "updated": updated, "failed": failed}

	def release_pilot_to_everyone_if_ready(self) -> None:
		"""Open the tag to every pilot once enough of the first group runs it."""
		if (
			self.pilot_rollout_halted
			or not self.pilot_auto_release_percent
			or self.pilot_rollout_percent >= 100
		):
			return

		counts = self.pilot_rollout_counts()
		if (
			not counts
			or not counts["group"]
			or counts["updated"] * 100 < self.pilot_auto_release_percent * counts["group"]
		):
			return

		frappe.db.set_single_value("Central Settings", "pilot_rollout_percent", 100)
		self.add_comment(
			"Info",
			_("Released {0} to everyone: {1} of {2} servers in the first group updated, {3}% needed.").format(
				self.pilot_release_tag, counts["updated"], counts["group"], self.pilot_auto_release_percent
			),
		)

	def feature_flags(self) -> dict[str, bool]:
		"""The console's feature flags as a plain {name: bool} map for window boot.
		`addons` gates the whole area; the rest are per-service rollout switches the
		Add-ons page reads to decide which cards are live vs "coming soon"."""
		return {
			"addons": bool(self.enable_addons),
			"llm": bool(self.enable_llm_service),
			"pdf": bool(self.enable_pdf_print_service),
			"email": bool(self.enable_email_delivery_service),
			"storage": bool(self.enable_object_storage_service),
		}

	def is_pilot_release_allowed(self, pilot_credential_id: str, channel: str) -> bool:
		"""Whether this pilot may update to `pilot_release_tag`. Halting stops everyone."""
		return not self.pilot_rollout_halted and self.in_pilot_rollout_group(pilot_credential_id, channel)

	def in_pilot_rollout_group(self, pilot_credential_id: str, channel: str) -> bool:
		"""Whether this pilot is in the group the rollout percent picks.

		The tag is part of the hash, so each release picks a different first group.
		Early pilots always go first; late pilots wait for a full release."""
		if channel == "early":
			return True

		if channel == "late":
			return self.pilot_rollout_percent >= 100

		seed = f"pilot-{self.pilot_release_tag}-{pilot_credential_id}".encode()
		return int(hashlib.sha256(seed).hexdigest(), 16) % 100 < self.pilot_rollout_percent
