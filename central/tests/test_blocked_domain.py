from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.infrastructure.doctype.blocked_domain.blocked_domain import (
	BlockedDomain,
	seed_for_zone,
	seed_regional_domains,
)
from central.infrastructure.doctype.resource_action.resource_action import ResourceAction
from central.infrastructure.doctype.site_domain.site_domain import SiteDomain
from central.site_provisioning import subdomain_availability
from central.tests.test_iam import ensure_user
from central.tests.test_sites import SiteOnAMachine


def block(name: str, parent: str, mode: str = "Exact") -> BlockedDomain:
	return frappe.get_doc(
		{
			"doctype": "Blocked Domain",
			"blocked_name": name,
			"parent_domain": parent,
			"match_mode": mode,
			"enabled": 1,
		}
	).insert()


class TestBlockedDomainMatching(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.zone = f"blocked-{frappe.generate_hash(length=8)}.example.test"

	def test_exact_normalizes_case_and_trailing_dots_without_blocking_prefixes(self):
		reservation = block("  CeNtRaL. ", self.zone.upper() + ".")

		self.assertEqual(reservation.blocked_name, "central")
		self.assertEqual(reservation.parent_domain, self.zone)
		self.assertTrue(BlockedDomain.is_blocked(f"CENTRAL.{self.zone.upper()}.."))
		for domain in (f"central-app.{self.zone}", f"other.central.{self.zone}", "central.customer.test"):
			with self.subTest(domain=domain):
				self.assertFalse(BlockedDomain.is_blocked(domain))

	def test_prefix_stays_inside_the_parent_domain(self):
		block("proxy-", self.zone, "Prefix")

		self.assertTrue(BlockedDomain.is_blocked(f"proxy-001.{self.zone}"))
		for domain in (f"proxy.{self.zone}", f"my-proxy-001.{self.zone}", f"proxy-001.evil{self.zone}"):
			with self.subTest(domain=domain):
				self.assertFalse(BlockedDomain.is_blocked(domain))

	def test_disabled_reservations_stop_matching_immediately(self):
		reservation = block("central", self.zone)
		self.assertTrue(BlockedDomain.is_blocked(f"central.{self.zone}"))
		reservation.enabled = 0
		reservation.save()
		self.assertFalse(BlockedDomain.is_blocked(f"central.{self.zone}"))

	def test_invalid_configuration_is_refused(self):
		for name, parent, mode in (
			("", self.zone, "Exact"),
			("proxy-", self.zone, "Exact"),
			("proxy", "*.example.test", "Prefix"),
			("proxy", "https://example.test", "Exact"),
			("proxy", "example.test:443", "Exact"),
		):
			with self.subTest(name=name, parent=parent), self.assertRaises(frappe.ValidationError):
				block(name, parent, mode)

	def test_seed_is_repeatable_and_preserves_operator_changes(self):
		seed_for_zone(self.zone)
		count = frappe.db.count("Blocked Domain", {"parent_domain": self.zone})
		seed_for_zone(self.zone)
		self.assertEqual(frappe.db.count("Blocked Domain", {"parent_domain": self.zone}), count)
		reservation = frappe.get_doc(
			"Blocked Domain", {"parent_domain": self.zone, "blocked_name": "central"}
		)
		reservation.enabled = 0
		reservation.match_mode = "Exact"
		reservation.save()
		seed_for_zone(self.zone)
		self.assertEqual(reservation.reload().match_mode, "Exact")
		self.assertFalse(reservation.enabled)
		self.assertFalse(BlockedDomain.is_blocked(f"central-app.{self.zone}"))
		frappe.get_doc("Blocked Domain", {"blocked_name": "support", "parent_domain": self.zone}).delete()
		seed_for_zone(self.zone)
		self.assertTrue(BlockedDomain.is_blocked(f"support.{self.zone}"))

	def test_defaults_use_exact_names_and_infrastructure_prefixes(self):
		seed_for_zone(self.zone)
		for name in (
			"proxy",
			"proxy-01",
			"s3-svc-01",
			"s3-admin-svc-01",
			"cargo-pilot-01",
			"root",
			"api",
			"login",
			"mail",
			"support",
			"status",
		):
			self.assertTrue(BlockedDomain.is_blocked(f"{name}.{self.zone}"))
		self.assertFalse(BlockedDomain.is_blocked(f"support-team.{self.zone}"))

	def test_only_system_managers_can_manage_or_review_reservations(self):
		reservation = block("central", self.zone)
		user = ensure_user("blocked.domain.customer@example.test")
		frappe.set_user(user)

		frappe.get_doc(
			{"doctype": "Team", "team_name": "Blocked domain customer", "owner_user": user}
		).insert()
		self.assertTrue(BlockedDomain.is_blocked(f"central.{self.zone}"))
		self.assertFalse(frappe.has_permission("Blocked Domain", "read", doc=reservation))
		with self.assertRaises(frappe.PermissionError):
			reservation.find_conflicts()
		with self.assertRaises(frappe.PermissionError):
			block("proxy", self.zone)


class TestBlockedDomainAssignments(SiteOnAMachine):
	def test_new_regions_receive_reservations_in_both_zones(self):
		frappe.db.set_single_value("Central Settings", "wildcard_domain", "services.example.test")
		region = frappe.get_doc(
			{
				"doctype": "Region",
				"region": "blocked-" + frappe.generate_hash(length=8),
				"proxy_domain": "new-proxy.example.test",
			}
		).insert()

		self.assertTrue(BlockedDomain.is_blocked(f"central-app.{region.proxy_domain}"))
		self.assertTrue(BlockedDomain.is_blocked(f"central-app.{region.name}.services.example.test"))

	def test_signup_refuses_scoped_prefixes_and_accepts_unrelated_names(self):
		block("infrastructure-", self.region.proxy_domain, "Prefix")

		self.assertFalse(subdomain_availability("INFRASTRUCTURE-123.")["available"])
		self.assertTrue(subdomain_availability("customer-" + frappe.generate_hash(length=8))["available"])

	def test_site_creation_and_name_changes_are_validated(self):
		block("blocked", self.region.proxy_domain)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Site",
					"site_name": f"blocked.{self.region.proxy_domain}",
					"team": self.team.name,
					"server": self.server.name,
				}
			).insert()

		self.enroll()
		from central.integrations.servers import observe_server

		observe_server(self.server)
		site = self.site()
		site.subdomain = "BLOCKED."
		with self.assertRaises(frappe.ValidationError):
			site.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.rename_doc("Site", site.name, f"blocked.{self.region.proxy_domain}", force=True)

	def test_a_queued_creation_cannot_bypass_the_signup_check(self):
		block("blocked", self.region.proxy_domain)

		with self.assertRaises(frappe.ValidationError):
			ResourceAction.queue("create", self.team.name, self.region.name, "Blocked", subdomain="BLOCKED.")

	def test_a_delayed_rename_rechecks_reservations_before_calling_pilot(self):
		from central.integrations.servers import observe_server

		self.enroll()
		observe_server(self.server)
		site = self.site()
		site.subdomain = "legacy"
		site.save()
		block("legacy", self.region.proxy_domain)

		with patch("central.integrations.pilot.rename_site") as rename:
			site.apply_subdomain()
		rename.assert_not_called()
		self.assertIn("reserved. Choose another name.", site.rename_error)

	def test_custom_domain_registration_is_refused_before_dns_or_proxy_calls(self):
		zone = f"customer-{frappe.generate_hash(length=8)}.test"
		block("central", zone, "Prefix")
		credential = SimpleNamespace(server=self.server.name, team=self.team.name)
		with (
			patch.object(SiteDomain, "verify_ownership") as verify,
			patch.object(SiteDomain, "apply") as apply,
		):
			for operation in (SiteDomain.get_dns_records, SiteDomain.register):
				with self.subTest(operation=operation), self.assertRaises(frappe.ValidationError):
					operation(credential, f"CENTRAL-APP.{zone}.")
		verify.assert_not_called()
		apply.assert_not_called()
		self.assertFalse(frappe.db.exists("Site Domain", f"central-app.{zone}"))

	def test_direct_domain_assignment_and_changes_cannot_bypass_registration(self):
		frappe.db.set_single_value("Central Settings", "wildcard_domain", "example.test")
		zone = f"customer-{frappe.generate_hash(length=8)}.test"
		block("blocked", zone)
		credential = SimpleNamespace(server=self.server.name, team=self.team.name)
		with self.assertRaises(frappe.ValidationError):
			SiteDomain.new_for_pilot(credential, f"blocked.{zone}").insert()

		route = SiteDomain.new_for_pilot(credential, f"permitted.{zone}").insert()
		route.domain = f"blocked.{zone}"
		with self.assertRaises(frappe.ValidationError):
			route.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.rename_doc("Site Domain", route.name, f"blocked.{zone}", force=True)

	def test_operator_review_includes_sites_and_pending_requests_across_teams(self):
		from central.integrations.servers import observe_server

		self.enroll()
		observe_server(self.server)
		site = self.site()
		site.subdomain = "legacy"
		site.save()
		other_team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Other blocked domain team", "owner_user": "Administrator"}
		).insert()
		action = ResourceAction.queue(
			"create", other_team.name, self.region.name, "Legacy", subdomain="legacy"
		)
		reservation = block("legacy", self.region.proxy_domain)
		conflicts = reservation.find_conflicts()

		self.assertEqual({row["team"] for row in conflicts}, {self.team.name, other_team.name})
		self.assertEqual({row["name"] for row in conflicts}, {site.name, action.name})
		site.save()
		action.save()

	def test_conflicts_are_reported_without_removing_or_breaking_saved_routes(self):
		frappe.db.set_single_value("Central Settings", "wildcard_domain", "example.test")
		zone = f"customer-{frappe.generate_hash(length=8)}.test"
		route = frappe.get_doc(
			{
				"doctype": "Site Domain",
				"domain": f"central.{zone}",
				"team": self.team.name,
				"region": self.region.name,
				"server": self.server.name,
			}
		).insert()
		reservation = block("central", zone)
		conflicts = reservation.find_conflicts()
		self.assertIn(
			{"doctype": "Site Domain", "name": route.name, "domain": route.domain, "team": self.team.name},
			conflicts,
		)
		route.save()
		self.server.db_set("ipv6_address", "2001:db8::10")
		credential = SimpleNamespace(server=self.server.name, team=self.team.name, pilot_credential_id="test")
		proxy = MagicMock()
		with patch(
			"central.infrastructure.doctype.site_domain.site_domain.Region.get_proxy_client",
			return_value=proxy,
		):
			SiteDomain.register(credential, route.domain)
			SiteDomain.deregister(credential, route.domain)
		proxy.set_domain.assert_called_once_with(route.domain, "2001:db8::10")
		proxy.delete_domain.assert_called_once_with(route.domain)

	def test_migration_reserves_existing_service_and_proxy_zones(self):
		frappe.db.set_single_value("Central Settings", "wildcard_domain", "services.example.test")
		seed_regional_domains()

		for zone in (
			self.region.proxy_domain,
			f"{self.region.name}.services.example.test",
		):
			self.assertTrue(BlockedDomain.is_blocked(f"cargo-pilot-01.{zone}"))
