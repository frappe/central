# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document

# A Failure Percent of 100 would never hold, because a release is held only above it.
APP_ROLLOUT_PERCENT_LIMITS = (
	("app_rollout_start_percent", 1, 100),
	("app_rollout_step_percent", 1, 100),
	("app_rollout_max_percent", 0, 100),
	("app_rollout_failure_percent", 1, 99),
)


class CentralSettings(Document):
	"""Console feature flags, one Check each, read at page boot so the console can hide an area."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		app_rollout_failure_percent: DF.Int
		app_rollout_interval_hours: DF.Int
		app_rollout_max_percent: DF.Int
		app_rollout_minimum_servers: DF.Int
		app_rollout_start_percent: DF.Int
		app_rollout_step_percent: DF.Int
		central_id: DF.Int
		common_site_config: DF.JSON | None
		disk_iops: DF.Int
		disk_throughput_mibps: DF.Int
		enable_addons: DF.Check
		enable_email_delivery_service: DF.Check
		enable_firewall: DF.Check
		enable_llm_service: DF.Check
		enable_object_storage_service: DF.Check
		enable_pdf_print_service: DF.Check
		enable_public_ipv4: DF.Check
		enable_public_ipv6: DF.Check
		github_app_id: DF.Data | None
		github_app_slug: DF.Data | None
		github_client_id: DF.Data | None
		github_client_secret: DF.Password | None
		github_private_key: DF.Password | None
		github_webhook_secret: DF.Password | None
		invitation_expiry_days: DF.Int
		invitation_resend_cooldown_minutes: DF.Int
		invitations_per_hour: DF.Int
		private_network_throughput_mibps: DF.Int
		public_network_throughput_mibps: DF.Int
		sign_in_code_attempts: DF.Int
		sign_in_codes_per_email: DF.Int
		require_payment_method: DF.Check
		trial_days: DF.Int
		trial_deletion_days: DF.Int
		trial_idle_shutdown_minutes: DF.Int
		trial_notice_days: DF.Int
		trial_servers_per_team: DF.Int
		wildcard_domain: DF.Data | None
	# end: auto-generated types

	def validate(self) -> None:
		self.validate_limits()
		self.validate_common_site_config()
		self.validate_app_rollout()

	def on_update(self) -> None:
		from central.infrastructure.doctype.github_connection.github_connection import GitHubConnection

		if self.has_value_changed("github_app_id"):
			GitHubConnection.disable_all()

	def validate_limits(self) -> None:
		"""A zero would refuse every invitation or sign-in code, or give a new server no disk or network."""
		for fieldname in (
			"invitations_per_hour",
			"sign_in_code_attempts",
			"sign_in_codes_per_email",
			"disk_iops",
			"disk_throughput_mibps",
			"private_network_throughput_mibps",
			"public_network_throughput_mibps",
		):
			if self.get(fieldname) < 1:
				frappe.throw(_("{0} must be at least 1.").format(_(self.meta.get_label(fieldname))))

	def validate_common_site_config(self) -> None:
		from central.integrations.atlas import MAXIMUM_METADATA_BYTES

		try:
			config = self.get_common_site_config()
		except ValueError:
			config = None
		if not isinstance(config, dict):
			frappe.throw(_('Common Site Config must be a JSON object, such as {"key": "value"}.'))
		if len(json.dumps(config).encode()) > MAXIMUM_METADATA_BYTES:
			frappe.throw(_("Common Site Config must fit in {0} bytes.").format(MAXIMUM_METADATA_BYTES))

	def validate_app_rollout(self) -> None:
		for fieldname, lowest, highest in APP_ROLLOUT_PERCENT_LIMITS:
			value = self.get(fieldname)
			if not lowest <= value <= highest:
				label = _(self.meta.get_label(fieldname))
				frappe.throw(
					_("{0} must be between {1} and {2}, not {3}.").format(label, lowest, highest, value)
				)

		for fieldname in ("app_rollout_interval_hours", "app_rollout_minimum_servers"):
			value = self.get(fieldname)
			if value < 1:
				label = _(self.meta.get_label(fieldname))
				frappe.throw(_("{0} must be at least 1, not {1}.").format(label, value))

	def get_common_site_config(self) -> dict:
		return frappe.parse_json(self.common_site_config or "{}")

	def app_rollout(self) -> dict[str, int | list[str]]:
		"""The steps Pilot uses to offer a new app update to more servers over time, and the
		releases it must not offer."""
		from central.central.doctype.app_rollout_hold.app_rollout_hold import AppRolloutHold

		return {
			"start_percent": self.app_rollout_start_percent,
			"step_percent": self.app_rollout_step_percent,
			"interval_hours": self.app_rollout_interval_hours,
			"max_percent": self.app_rollout_max_percent,
			"held_commits": AppRolloutHold.get_held_commits(),
		}

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
			"public_ipv4": bool(self.enable_public_ipv4),
			"public_ipv6": bool(self.enable_public_ipv6),
			"firewall": bool(self.enable_firewall),
		}

	def require_new_server_network_options(
		self, has_public_ipv4: bool, has_public_ipv6: bool, is_firewall_enabled: bool
	) -> None:
		"""Refuse a network option that the New server page does not offer yet."""
		refusals = (
			(has_public_ipv4 and not self.enable_public_ipv4, _("A public IPv4 address")),
			(has_public_ipv6 and not self.enable_public_ipv6, _("A public IPv6 address")),
			(is_firewall_enabled and not self.enable_firewall, _("The firewall")),
		)
		for is_refused, option in refusals:
			if is_refused:
				frappe.throw(_("{0} is not available for new servers yet.").format(option))
