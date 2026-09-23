from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
import httpx
from atlas_proxy_client.api.domains import delete_domain, patch_domain
from atlas_proxy_client.api.sites import patch_site
from atlas_proxy_client.types import Response
from frappe.tests import IntegrationTestCase

from central.infrastructure.doctype.region.region import Region
from central.infrastructure.doctype.site_domain.site_domain import (
	MAXIMUM_ATTEMPTS,
	VERIFICATION_RECORD,
	DomainNotVerifiedError,
	SiteDomain,
	remove_server_routes,
	retry_failed,
)
from central.integrations.proxy import ProxyClient, ProxyError
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

WILDCARD = "example.test"
GET_PROXY_CLIENT = "central.infrastructure.doctype.site_domain.site_domain.Region.get_proxy_client"
RESOLVE = "central.infrastructure.doctype.site_domain.site_domain._resolve"
IS_APEX = "central.infrastructure.doctype.site_domain.site_domain.is_apex"


class TestSiteDomain(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Central Settings", "wildcard_domain", WILDCARD)
		self.suffix = frappe.generate_hash(length=8)
		self.zone = f"sd-{self.suffix}.{WILDCARD}"
		self.region = ensure_atlas_instance(f"sd-{self.suffix}", proxy_domain=self.zone)
		self.owner = ensure_user("site.domain.owner@example.test")
		self.viewer = ensure_user("site.domain.viewer@example.test")
		self.team = self._team("Site Domain A", self.viewer, "Viewer")
		self.other_team = self._team("Site Domain B", self.owner, "Owner")
		self.server = self._server("a", self.team, "2001:db8::10")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_one_label_below_the_zone_is_a_site(self):
		route = self._route(f"erp-{self.suffix}.{self.zone}")

		self.assertEqual(route.route_type, "Site")
		self.assertEqual(route.site_label, f"erp-{self.suffix}")

	def test_a_name_outside_the_zone_is_a_custom_domain(self):
		route = self._route(f"WWW.Shop-{self.suffix}.com.")

		self.assertEqual(route.route_type, "Domain")
		self.assertEqual(route.domain, f"www.shop-{self.suffix}.com")

	def test_invalid_names_are_refused(self):
		for domain in (
			self.zone,
			f"a.b.{self.zone}",
			f"proxy.{self.zone}",
			f"proxy-001.{self.zone}",
			"*.x.com",
		):
			with self.subTest(domain=domain), self.assertRaises(frappe.ValidationError):
				self._route(domain)

	def test_server_of_another_team_is_refused(self):
		other_asset = self._server("b", self.other_team, "2001:db8::11")

		with self.assertRaises(frappe.ValidationError):
			self._route(f"x-{self.suffix}.com", server=other_asset, team=self.team)

	def test_apply_routes_the_server_address(self):
		route = self._route(f"erp-{self.suffix}.{self.zone}")
		proxy = MagicMock()

		with patch(GET_PROXY_CLIENT, return_value=proxy):
			route.apply()

		proxy.set_site.assert_called_once_with(f"erp-{self.suffix}", "2001:db8::10")
		proxy.set_domain.assert_not_called()
		route.reload()
		self.assertEqual((route.status, route.attempts, route.ipv6_address), ("Active", 0, "2001:db8::10"))
		self.assertIsNone(route.failure_reason)

	def test_apply_records_the_failure_reason(self):
		route = self._route(f"fail-{self.suffix}.com")
		proxy = MagicMock()
		proxy.set_domain.side_effect = ProxyError("HTTP 503: not ready")

		with patch(GET_PROXY_CLIENT, return_value=proxy):
			route.apply()

		route.reload()
		self.assertEqual((route.status, route.attempts), ("Failed", 1))
		self.assertEqual(
			route.failure_reason,
			"Central could not update this route. It will retry automatically.",
		)
		self.assertIn("HTTP 503", frappe.db.get_value("Error Log", route.error_log, "error"))
		self.assertEqual(
			frappe.db.get_value("Error Log", route.error_log, ["reference_doctype", "reference_name"]),
			("Site Domain", route.name),
		)

	def test_apply_records_an_unreachable_proxy(self):
		route = self._route(f"down-{self.suffix}.com")
		proxy = MagicMock()
		proxy.set_domain.side_effect = httpx.ConnectError("connection refused")

		with patch(GET_PROXY_CLIENT, return_value=proxy):
			route.apply()

		route.reload()
		self.assertEqual(route.status, "Failed")
		self.assertIn("connection refused", frappe.db.get_value("Error Log", route.error_log, "error"))

	def test_apply_fails_without_a_server_address(self):
		server = self._server("c", self.team, None)
		route = self._route(f"noip-{self.suffix}.com", server=server)

		with patch(GET_PROXY_CLIENT) as get_proxy_client:
			route.apply()

		get_proxy_client.assert_not_called()
		self.assertEqual(frappe.db.get_value("Site Domain", route.name, "status"), "Failed")

	def test_scheduler_stops_at_the_attempt_limit(self):
		retried = self._route(f"retry-{self.suffix}.com")
		retried.db_set({"status": "Failed", "attempts": MAXIMUM_ATTEMPTS - 1})
		exhausted = self._route(f"done-{self.suffix}.com")
		exhausted.db_set({"status": "Failed", "attempts": MAXIMUM_ATTEMPTS})
		proxy = MagicMock()

		with patch(GET_PROXY_CLIENT, return_value=proxy), patch.object(frappe.db, "commit"):
			retry_failed()

		routed = {call.args[0] for call in proxy.set_domain.call_args_list}
		self.assertIn(retried.domain, routed)
		self.assertNotIn(exhausted.domain, routed)

	def test_delete_removes_the_route_from_the_proxy(self):
		route = self._route(f"gone-{self.suffix}.com")
		proxy = MagicMock()

		with patch(GET_PROXY_CLIENT, return_value=proxy):
			route.delete()

		proxy.delete_domain.assert_called_once_with(route.domain)
		self.assertFalse(frappe.db.exists("Site Domain", route.name))

	def test_delete_is_refused_when_the_proxy_fails(self):
		route = self._route(f"stay-{self.suffix}.com")
		proxy = MagicMock()
		proxy.delete_domain.side_effect = ProxyError("refused")

		with patch(GET_PROXY_CLIENT, return_value=proxy), self.assertRaises(ProxyError):
			route.delete()

		self.assertTrue(frappe.db.exists("Site Domain", route.name))

	def test_terminating_a_server_removes_its_routes(self):
		site = self._route(f"erp-{self.suffix}.{self.zone}")
		domain = self._route(f"shop-{self.suffix}.com")
		proxy = MagicMock()
		server = frappe.get_doc("Virtual Machine", self.server.name)
		server.status = "Terminated"

		with (
			patch(GET_PROXY_CLIENT, return_value=proxy),
			patch.object(frappe.db, "commit"),
			patch("frappe.enqueue", side_effect=_run_route_removal),
		):
			server.save(ignore_permissions=True)

		proxy.delete_site.assert_called_once_with(site.site_label)
		proxy.delete_domain.assert_called_once_with(domain.domain)
		self.assertFalse(frappe.db.exists("Site Domain", {"server": self.server.name}))

	def test_a_failed_route_removal_stays_until_a_retry_removes_it(self):
		route = self._route(f"stuck-{self.suffix}.com")
		self.server.db_set("status", "Terminated")
		proxy = MagicMock()
		proxy.delete_domain.side_effect = ProxyError("HTTP 503: not ready")

		with patch(GET_PROXY_CLIENT, return_value=proxy), patch.object(frappe.db, "commit"):
			remove_server_routes(self.server.name)

		route.reload()
		self.assertEqual((route.status, route.attempts), ("Failed", 1))
		self.assertEqual(
			route.failure_reason,
			"Central could not remove this route. It will retry automatically.",
		)
		self.assertIn("HTTP 503", frappe.db.get_value("Error Log", route.error_log, "error"))

		proxy.delete_domain.side_effect = None
		with patch(GET_PROXY_CLIENT, return_value=proxy), patch.object(frappe.db, "commit"):
			retry_failed()

		proxy.set_domain.assert_not_called()
		self.assertFalse(frappe.db.exists("Site Domain", route.name))

	def test_route_removal_runs_as_the_user_that_queued_it(self):
		"""A region report runs as Guest, and a console terminate as a team member. Neither may
		delete a route, yet the job they queue must still remove it."""
		self.server.db_set("status", "Terminated")
		proxy = MagicMock()

		for label, user in (("guest", "Guest"), ("member", self.viewer)):
			with self.subTest(user=user):
				route = self._route(f"{label}-{self.suffix}.com")
				frappe.set_user(user)
				with patch(GET_PROXY_CLIENT, return_value=proxy), patch.object(frappe.db, "commit"):
					remove_server_routes(self.server.name)

				frappe.set_user("Administrator")
				self.assertFalse(frappe.db.exists("Site Domain", route.name))

	def test_team_members_read_only_their_team_routes(self):
		own = self._route(f"own-{self.suffix}.com")
		other = self._route(
			f"other-{self.suffix}.com", server=self._server("d", self.other_team, "2001:db8::12")
		)

		frappe.set_user(self.viewer)
		names = set(frappe.get_list("Site Domain", pluck="name"))

		self.assertIn(own.name, names)
		self.assertNotIn(other.name, names)
		self.assertTrue(frappe.has_permission("Site Domain", "read", own.name))
		self.assertFalse(frappe.has_permission("Site Domain", "read", other.name))
		self.assertFalse(frappe.has_permission("Site Domain", "write", own.name))

	def test_a_site_needs_no_dns_records_and_registers_directly(self):
		credential = self._credential(self.server)
		domain = f"shop-{self.suffix}.{self.zone}"
		proxy = MagicMock()

		self.assertEqual(SiteDomain.get_dns_records(credential, domain), {})
		with patch(GET_PROXY_CLIENT, return_value=proxy):
			SiteDomain.register(credential, domain)

		proxy.set_site.assert_called_once_with(f"shop-{self.suffix}", "2001:db8::10")
		self.assertEqual(frappe.db.get_value("Site Domain", domain, "status"), "Active")

	def test_the_routed_names_of_a_server_need_no_proxy_call(self):
		"""The region answers `admin-vm-*` and `site-*` from the label itself."""
		credential = self._credential(self.server)
		proxy = MagicMock()

		for domain in self._routed_names():
			with self.subTest(domain=domain), patch(GET_PROXY_CLIENT, return_value=proxy):
				SiteDomain.register(credential, domain)
				SiteDomain.deregister(credential, domain)

			self.assertFalse(frappe.db.exists("Site Domain", domain))

		proxy.set_site.assert_not_called()
		proxy.delete_site.assert_not_called()

	def test_a_routed_name_takes_no_record(self):
		for domain in self._routed_names():
			with self.subTest(domain=domain), self.assertRaises(frappe.ValidationError):
				self._route(domain)

	def test_a_routed_name_of_another_server_is_refused(self):
		other = self._server("f", self.team, "2001:db8::20")
		domain = self._routed_names(other)[0]

		with self.assertRaises(frappe.ValidationError):
			SiteDomain.register(self._credential(self.server), domain)

		self.assertFalse(frappe.db.exists("Site Domain", domain))

	def test_a_routed_name_outside_the_zone_is_a_custom_domain(self):
		route = self._route(f"admin-vm-{self.suffix}.example.com")

		self.assertEqual(route.route_type, "Domain")
		self.assertFalse(route.is_auto_routed)

	def test_a_route_names_the_site_its_server_runs(self):
		"""A Pilot only knows its machine, so the site comes from the machine."""
		site = frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": f"site-{self.suffix}.{self.zone}",
				"team": self.team,
				"server": self.server.name,
			}
		).insert(ignore_permissions=True)

		route = SiteDomain.new_for_pilot(self._credential(self.server), f"www.own-{self.suffix}.com")

		self.assertEqual(route.site, site.name)

	def test_a_domain_registers_after_its_dns_records_match(self):
		credential = self._credential(self.server)
		domain = f"www.shop-{self.suffix}.com"
		records = SiteDomain.get_dns_records(credential, domain)["cname"]
		token = records[1]["value"]
		dns = {
			(f"{VERIFICATION_RECORD}.{domain}", "TXT"): [token],
			(domain, "CNAME"): [f"proxy.{self.zone}"],
		}

		self.assertEqual(records[0], {"type": "CNAME", "host": domain, "value": f"proxy.{self.zone}"})
		self.assertEqual(SiteDomain.get_dns_records(credential, domain)["cname"][1]["value"], token)
		with (
			patch(RESOLVE, side_effect=lambda name, record_type: dns.get((name, record_type), [])),
			patch(IS_APEX, return_value=False),
			patch(GET_PROXY_CLIENT, return_value=MagicMock()),
		):
			SiteDomain.register(credential, domain)

		self.assertEqual(frappe.db.get_value("Site Domain", domain, "status"), "Active")

	def test_a_domain_is_not_recorded_until_verified(self):
		credential = self._credential(self.server)
		domain = f"www.wait-{self.suffix}.com"

		with self.assertRaises(DomainNotVerifiedError):
			SiteDomain.register(credential, domain)

		SiteDomain.get_dns_records(credential, domain)
		with patch(RESOLVE, return_value=[]), self.assertRaises(DomainNotVerifiedError):
			SiteDomain.register(credential, domain)

		self.assertFalse(frappe.db.exists("Site Domain", domain))

	def test_an_apex_domain_skips_the_cname_check(self):
		credential = self._credential(self.server)
		domain = f"apex-{self.suffix}.com"
		token = SiteDomain.get_dns_records(credential, domain)["cname"][1]["value"]

		with (
			patch(RESOLVE, side_effect=lambda name, record_type: [token] if record_type == "TXT" else []),
			patch(IS_APEX, return_value=True),
			patch(GET_PROXY_CLIENT, return_value=MagicMock()),
		):
			SiteDomain.register(credential, domain)

		self.assertTrue(frappe.db.exists("Site Domain", domain))

	def test_a_route_of_another_server_is_refused(self):
		route = self._route(f"taken-{self.suffix}.{self.zone}")
		other = self._credential(self._server("e", self.team, "2001:db8::13"))

		with self.assertRaises(frappe.DuplicateEntryError):
			SiteDomain.register(other, route.domain)
		with self.assertRaises(frappe.PermissionError):
			SiteDomain.deregister(other, route.domain)

		self.assertTrue(frappe.db.exists("Site Domain", route.name))

	def test_deregister_removes_the_route(self):
		route = self._route(f"bye-{self.suffix}.com")
		proxy = MagicMock()

		with patch(GET_PROXY_CLIENT, return_value=proxy):
			SiteDomain.deregister(self._credential(self.server), route.domain)
			SiteDomain.deregister(self._credential(self.server), route.domain)

		proxy.delete_domain.assert_called_once_with(route.domain)
		self.assertFalse(frappe.db.exists("Site Domain", route.name))

	def _routed_names(self, server=None) -> tuple[str, str]:
		"""The admin and site hostnames the region routes to a server without a map entry."""
		server = server or self.server
		instance = frappe.get_doc("Region", self.region)
		return (
			instance.get_vm_admin_host(server.ipv6_address),
			instance.get_vm_site_host(server.ipv6_address),
		)

	def _credential(self, server):
		return SimpleNamespace(team=server.team, server=server.name, pilot_credential_id=f"pc-{server.name}")

	def _route(self, domain: str, server=None, team: str | None = None):
		server = server or self.server
		return frappe.get_doc(
			{
				"doctype": "Site Domain",
				"domain": domain,
				"team": team or server.team,
				"region": self.region,
				"server": server.name,
			}
		).insert(ignore_permissions=True)

	def _team(self, label: str, user: str, role: str) -> str:
		members = [{"user": self.owner, "role": "Owner", "status": "Active"}]
		if user != self.owner:
			members.append({"user": user, "role": role, "status": "Active"})
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": f"{label} {self.suffix}",
				"owner_user": self.owner,
				"members": members,
			}
		)
		return team.insert().name

	def _server(self, label: str, team: str, ipv6_address: str | None):
		return frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"vm-sd-{label}-{self.suffix}",
				"team": team,
				"cluster": self.region,
				"status": "Running",
				"ipv6_address": ipv6_address,
			}
		).insert(ignore_permissions=True)


def _run_route_removal(method, **kwargs):
	"""Run the route-removal job inline, as the worker would after commit."""
	if isinstance(method, str) and method.endswith("remove_server_routes"):
		remove_server_routes(kwargs["server"])


class TestRegionProxyClient(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Central Settings", "wildcard_domain", WILDCARD)
		self.region = ensure_atlas_instance(f"pc-{frappe.generate_hash(length=8)}")

	def test_service_url_uses_the_regional_zone(self):
		self.assertEqual(
			Region.get_service_url("cargo", self.region), f"https://cargo.{self.region}.{WILDCARD}"
		)

	def test_proxy_client_needs_the_region_id(self):
		with self.assertRaises(frappe.ValidationError):
			Region.get_proxy_client(self.region)

		frappe.db.set_value("Region", self.region, "atlas_region_id", "65001")
		with patch(
			"central.infrastructure.doctype.region.region.mint_proxy_token", return_value="token"
		) as mint:
			client = Region.get_proxy_client(self.region)

		mint.assert_called_once_with(65001)
		self.assertEqual(client.base_url, f"https://proxy.{self.region}.{WILDCARD}")

	def test_proxy_client_raises_when_a_site_change_is_refused(self):
		refused = Response(status_code=HTTPStatus.CONFLICT, content=b"reserved", headers={}, parsed=None)

		with patch.object(patch_site, "sync_detailed", return_value=refused):
			with self.assertRaises(ProxyError) as context:
				ProxyClient("https://proxy.test", "token").set_site("proxy", "2001:db8::1")

		self.assertIn("409", str(context.exception))

	def test_proxy_client_raises_when_a_domain_change_is_refused(self):
		refused = Response(status_code=HTTPStatus.SERVICE_UNAVAILABLE, content=b"", headers={}, parsed=None)

		with patch.object(patch_domain, "sync_detailed", return_value=refused):
			with self.assertRaises(ProxyError):
				ProxyClient("https://proxy.test", "token").set_domain("www.example.com", "2001:db8::1")

	def test_proxy_client_accepts_a_removed_domain(self):
		removed = Response(status_code=HTTPStatus.NO_CONTENT, content=b"", headers={}, parsed=None)

		with patch.object(delete_domain, "sync_detailed", return_value=removed) as endpoint:
			ProxyClient("https://proxy.test", "token").delete_domain("www.example.com")

		self.assertEqual(endpoint.call_args.args, ("www.example.com",))
