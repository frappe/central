from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.sites import claim_site, get_site, onboarding_status, terminate_site
from central.errors import AtlasResourceGone
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.site.site import on_host
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.pilot import PilotLoginPending, fetch_site_login_url
from central.integrations.servers import observe_server
from central.site_provisioning import (
	signup_offering,
	subdomain_availability,
	trial_configuration,
	trial_region_and_plan,
)
from central.www.dashboard import _onboarding_complete


class SiteOnAMachine(IntegrationTestCase):
	"""One machine running the site its Pilot image baked."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch("frappe.enqueue"))
		self.enqueue_doc = self.enterContext(patch("frappe.enqueue_doc"))
		self.enterContext(patch.object(VirtualMachine, "ensure_subscription_enabled"))
		self.enterContext(patch.object(VirtualMachine, "disable_active_subscription"))
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Trial", "owner_user": "Administrator"}
		).insert()
		region = frappe.get_doc(
			{
				"doctype": "Region",
				"region": "site-" + frappe.generate_hash(length=8),
				"base_url": "https://atlas.example.test",
				"proxy_domain": "par-2.example.test",
				"status": "Active",
			}
		).insert()
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": "server-" + frappe.generate_hash(length=8),
				"team": self.team.name,
				"cluster": region.name,
				"atlas_vm_id": "vm-00001",
				"status": "Provisioning",
			}
		).insert()
		self.client = self.enterContext(patch("central.integrations.servers.AtlasClient")).return_value
		self.client.tenant_id = self.team.tenant_id
		self.client.get_vm.return_value = {
			"id": "vm-00001",
			"tenant_id": self.team.tenant_id,
			"current_state": "running",
			"error": None,
			"compute": {"cpu_millicores": 1000, "memory_mib": 512},
			"disk": {"size_mib": 20480},
			"network": {"mesh_ipv6": "fdaa:1::1", "public_ipv4": None},
		}

	def enroll(self) -> str:
		"""Enrol a Pilot the way provisioning does, audience and all."""
		credential = "pcred-" + self.server.name
		return PilotCredential.mint(
			team=self.team.name,
			pilot_credential_id=credential,
			server=self.server.name,
			audience_id=credential,
		)

	def site(self):
		return frappe.get_doc("Site", {"server": self.server.name})


class TestSiteMirror(SiteOnAMachine):
	def test_an_enrolled_machine_carries_the_site_its_image_baked(self):
		self.enroll()
		observe_server(self.server)

		site = self.site()
		self.assertEqual(site.name, "site-1z141z4.par-2.example.test")
		self.assertEqual(site.url, "https://site-1z141z4.par-2.example.test")
		self.assertEqual(site.team, self.team.name)
		self.assertIsNone(site.subdomain)

	def test_the_site_address_and_the_admin_address_name_the_same_machine(self):
		self.enroll()
		observe_server(self.server)

		self.assertEqual(self.server.reload().gateway_url, "https://admin-vm-1z141z4.par-2.example.test")
		self.assertEqual(self.site().url, "https://site-1z141z4.par-2.example.test")

	def test_a_machine_with_no_enrolled_pilot_has_no_site(self):
		observe_server(self.server)

		self.assertFalse(frappe.db.exists("Site", {"server": self.server.name}))

	def test_a_site_reads_its_state_from_the_machine_it_is(self):
		self.enroll()
		observe_server(self.server)
		self.client.get_vm.return_value["current_state"] = "stopped"

		observe_server(self.server)

		# Nothing was written to the site: its state was never its own to write.
		self.assertEqual(self.site().status, "Stopped")
		self.assertEqual(frappe.db.count("Site", {"server": self.server.name}), 1)

	def test_a_terminated_machine_takes_its_site_with_it(self):
		self.enroll()
		observe_server(self.server)
		self.client.get_vm.side_effect = AtlasResourceGone("gone")

		self.assertEqual(observe_server(self.server), "Terminated")

		self.assertEqual(self.site().status, "Terminated")


class TestSiteRoutes(SiteOnAMachine):
	def setUp(self):
		super().setUp()
		self.enroll()
		observe_server(self.server)

	def test_a_site_is_ready_only_once_it_answers_on_its_own_address(self):
		with patch("central.api.sites.is_site_reachable", return_value=False) as reachable:
			state = get_site(self.site().name)

		reachable.assert_called_once_with("https://site-1z141z4.par-2.example.test")
		self.assertFalse(state["ready"])
		self.assertIsNone(state["login_url"])

	def test_a_reachable_site_hands_back_a_sign_in_URL(self):
		with (
			patch("central.api.sites.is_site_reachable", return_value=True),
			patch(
				"central.integrations.pilot.fetch_site_login_url",
				return_value="https://site.local/desk?sid=abc",
			) as login,
		):
			state = get_site(self.site().name)

		# Pilot is asked for the site's bench name, and the session comes back on the
		# public address the customer's browser can actually reach.
		self.assertEqual(login.call_args.args[2], "site.local")
		self.assertTrue(state["ready"])
		self.assertEqual(state["login_url"], "https://site-1z141z4.par-2.example.test/desk?sid=abc")

	def test_a_site_is_ready_before_the_machine_reports_running(self):
		"""The mirrored status still says Provisioning: only the site's own answer gates readiness."""
		self.server.db_set("status", "Provisioning")
		with (
			patch("central.api.sites.is_site_reachable", return_value=True),
			patch(
				"central.integrations.pilot.fetch_site_login_url",
				return_value="https://site.local/desk?sid=abc",
			),
		):
			state = get_site(self.site().name)

		self.assertEqual(state["status"], "Provisioning")
		self.assertTrue(state["ready"])
		self.assertEqual(state["login_url"], "https://site-1z141z4.par-2.example.test/desk?sid=abc")

	def test_a_successful_claim_returns_before_the_rename_runs(self):
		self.site().db_set("subdomain", "acme")
		with (
			patch("central.api.sites.is_site_reachable", return_value=True),
			patch(
				"central.integrations.pilot.fetch_site_login_url",
				return_value="https://site.local/desk?sid=abc",
			),
			patch("central.integrations.pilot.rename_site") as rename,
		):
			state = claim_site(self.site().name)

		self.assertTrue(state["login_url"])
		self.assertTrue(self.site().claimed_at)
		self.enqueue_doc.assert_called_once()
		rename.assert_not_called()

	def test_a_blank_login_does_not_claim_or_rename(self):
		self.site().db_set("subdomain", "acme")
		with (
			patch("central.api.sites.is_site_reachable", return_value=True),
			patch("central.integrations.pilot.fetch_site_login_url", return_value=None),
		):
			state = claim_site(self.site().name)

		self.assertIsNone(state["login_url"])
		self.assertFalse(state["login_pending"])
		self.assertIsNone(self.site().claimed_at)
		self.enqueue_doc.assert_not_called()

	def test_an_unauthorized_login_is_reported_as_pending(self):
		self.site().db_set("subdomain", "acme")
		with (
			patch("central.api.sites.is_site_reachable", return_value=True),
			patch(
				"central.integrations.pilot.fetch_site_login_url",
				side_effect=PilotLoginPending,
			),
		):
			state = claim_site(self.site().name)

		self.assertIsNone(state["login_url"])
		self.assertTrue(state["login_pending"])
		self.assertIsNone(self.site().claimed_at)
		self.enqueue_doc.assert_not_called()

	def test_terminating_a_site_terminates_the_machine_it_is(self):
		result = terminate_site(self.site().name)

		action = frappe.get_doc("Resource Action", result["action"])
		self.assertEqual(action.action, "terminate")
		self.assertEqual(action.server, self.server.name)

	def test_another_team_cannot_reach_this_site(self):
		other = frappe.get_doc(
			{"doctype": "User", "email": "outsider@example.test", "first_name": "Outsider"}
		).insert(ignore_permissions=True)
		frappe.set_user(other.name)

		with self.assertRaises(frappe.PermissionError):
			get_site(self.site().name)

	def test_onboarding_follows_only_a_site_creation(self):
		server_action = self.creation_action("Server")
		self.assertEqual(onboarding_status(self.team.name), {"site": None, "creation": None})

		site_action = self.creation_action("Site")
		state = onboarding_status(self.team.name)

		self.assertEqual(state["site"]["name"], self.site().name)
		self.assertIsNone(state["creation"])
		self.assertNotEqual(server_action, site_action)

	def test_onboarding_completes_only_after_a_working_login(self):
		with patch("central.www.dashboard.get_user_team_names", return_value=[self.team.name]):
			self.assertFalse(_onboarding_complete())
			self.site().db_set("claimed_at", frappe.utils.now_datetime())
			self.assertTrue(_onboarding_complete())

	def creation_action(self, resource_type: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Resource Action",
					"resource_type": resource_type,
					"action": "create",
					"team": self.team.name,
					"server": self.server.name,
					"resource_id": self.server.name,
					"requested_by": "Administrator",
					"correlation_id": frappe.generate_hash(length=32),
					"status": "Succeeded",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)


class TestSiteHandoff(IntegrationTestCase):
	def test_a_401_login_response_is_retryable(self):
		response = Mock(status_code=401)
		with (
			patch("central.integrations.pilot.mint_site_login", return_value="token"),
			patch("central.integrations.pilot.requests.post", return_value=response),
			self.assertRaises(PilotLoginPending),
		):
			fetch_site_login_url("https://pilot.example.test", "pilot-1", "site.local")

	def test_a_minted_session_moves_onto_the_public_address(self):
		self.assertEqual(
			on_host("http://site.local/desk?sid=abc", "site-1z1.par-2.example.test"),
			"https://site-1z1.par-2.example.test/desk?sid=abc",
		)


class TestSignupOffering(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		frappe.db.delete("Image Offering")

	def make_offering(self, title: str, available_in: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Image Offering",
					"offering_key": "offer-" + frappe.generate_hash(length=8).lower(),
					"title": title,
					"enabled": 1,
					"available_in": available_in,
					"required_tags": [{"key": "purpose", "value": "pilot"}],
				}
			)
			.insert()
			.name
		)

	def test_an_offering_kept_for_signup_wins_over_a_shared_one(self):
		self.make_offering("Alpha", "Both")
		dedicated = self.make_offering("Zulu", "Signup")

		self.assertEqual(signup_offering(), dedicated)

	def test_signup_stops_when_no_offering_is_configured(self):
		self.make_offering("Server only", "Server")

		with self.assertRaises(frappe.ValidationError):
			signup_offering()


class TestTrialRegion(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)

	def test_a_region_with_no_proxy_zone_cannot_serve_trials(self):
		"""A site's address is built from the zone, so without one there is no site."""
		frappe.db.set_value("Region", {"status": "Active"}, "proxy_domain", None)

		with self.assertRaises(frappe.ValidationError):
			trial_region_and_plan("any-team")


class TestTrialImage(IntegrationTestCase):
	"""A trial is the site the image carries, so the region is asked for that image alone."""

	def images(self, count: int) -> dict:
		return {"items": [{"id": f"image-{index}", "created_at": index} for index in range(count)]}

	def resolve(self, page: dict) -> tuple[dict, dict]:
		with (
			patch("central.site_provisioning.signup_offering", return_value="pilot"),
			patch("central.site_provisioning.trial_region_and_plan", return_value=("par-2", "plan-trial")),
			patch("central.site_provisioning.list_images", return_value=page) as list_images,
		):
			return trial_configuration("any-team"), list_images.call_args.kwargs

	def test_the_region_is_asked_for_a_site_image_on_the_signup_version(self):
		"""The tags ride the regional query, so a page of other images cannot hide a match."""
		_, asked = self.resolve(self.images(1))

		self.assertEqual(asked["extra_tags"], {"has_site": "1", "frappe_version": "develop"})

	def test_the_newest_offered_image_is_chosen(self):
		configuration, _ = self.resolve(self.images(3))

		self.assertEqual(configuration["image_id"], "image-2")

	def test_a_region_that_offers_none_stops_the_trial(self):
		with self.assertRaises(frappe.ValidationError):
			self.resolve(self.images(0))


class TestSiteNaming(SiteOnAMachine):
	"""The address the region derives stays ours; the customer's name is renamed onto it."""

	def setUp(self):
		super().setUp()
		self.enroll()
		observe_server(self.server)
		self.site().db_set("subdomain", "acme")

	def test_the_address_stays_ours_and_theirs_is_only_a_rename_target(self):
		site = self.site()

		self.assertEqual(site.url, "https://site-1z141z4.par-2.example.test")
		self.assertEqual(site.rename_target, "acme.par-2.example.test")

	def test_naming_renames_the_bench_onto_their_address_once(self):
		with patch("central.integrations.pilot.rename_site", return_value={"task_id": "task-1"}) as rename:
			self.site().apply_subdomain()
			self.site().apply_subdomain()

		rename.assert_called_once_with(self.server.name, "site.local", "acme.par-2.example.test")
		self.assertEqual(self.site().rename_task, "task-1")

	def test_a_site_nobody_named_is_never_renamed(self):
		self.site().db_set("subdomain", None)

		with patch("central.integrations.pilot.rename_site") as rename:
			self.site().apply_subdomain()

		rename.assert_not_called()


class TestAdminHostname(SiteOnAMachine):
	def test_a_running_pilot_machine_claims_its_admin_hostname_once(self):
		"""Every Pilot machine needs it, and TLS stays off behind the regional proxy."""
		self.enroll()

		with patch(
			"central.integrations.pilot.rename_admin_domain", return_value={"task_id": "task-2"}
		) as rename:
			observe_server(self.server)
			observe_server(self.server)

		rename.assert_called_once_with(self.server.name, tls=False)
		self.assertEqual(self.server.reload().admin_domain_task, "task-2")

	def test_a_failure_leaves_it_to_the_next_report(self):
		self.enroll()

		with patch("central.integrations.pilot.rename_admin_domain", side_effect=OSError("unreachable")):
			observe_server(self.server)

		self.assertIsNone(self.server.reload().admin_domain_task)

	def test_a_response_without_a_task_leaves_it_to_the_next_report(self):
		self.enroll()

		with patch("central.integrations.pilot.rename_admin_domain", return_value={}) as rename:
			observe_server(self.server)
			observe_server(self.server)

		self.assertEqual(rename.call_count, 2)
		self.assertIsNone(self.server.reload().admin_domain_task)

	def test_a_stopped_machine_does_not_rename_its_admin_domain(self):
		self.enroll()
		self.client.get_vm.return_value["current_state"] = "stopped"

		with patch("central.integrations.pilot.rename_admin_domain") as rename:
			observe_server(self.server)

		rename.assert_not_called()


class TestSubdomainAvailability(SiteOnAMachine):
	def test_a_name_already_taken_is_refused(self):
		self.enroll()
		observe_server(self.server)
		self.site().db_set("subdomain", "acme")

		self.assertFalse(subdomain_availability("acme")["available"])
		self.assertTrue(subdomain_availability("acme-two")["available"])

	def test_a_malformed_or_reserved_name_is_refused(self):
		for name in ("", "-acme", "acme.two", "proxy", "admin"):
			with self.subTest(name=name):
				self.assertFalse(subdomain_availability(name)["available"])

	def test_a_name_typed_in_capitals_is_taken_as_written(self):
		# A unique base keeps the availability check independent of subdomains a shared
		# site already holds, while still exercising the trim-and-lowercase normalization.
		unique = "acme" + frappe.generate_hash(length=6).lower()
		answer = subdomain_availability(f"  {unique.upper()}  ")

		self.assertTrue(answer["available"])
		self.assertEqual(answer["subdomain"], unique)


class TestTrialCreationIsSentInTheRequest(IntegrationTestCase):
	"""A trial is one call out and one read back, so the customer is shown the outcome."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)

	def start(self, drive):
		from central.site_provisioning import create_trial_site

		with (
			patch("central.site_provisioning.validated_subdomain", return_value="acme"),
			patch("central.site_provisioning.trial_configuration", return_value={}),
			patch("central.site_provisioning.submit_request") as submit,
			patch("central.integrations.server_provisioning.process_request", side_effect=drive),
		):
			action = frappe.get_doc(
				{
					"doctype": "Resource Action",
					"resource_type": "Site",
					"action": "create",
					"team": frappe.get_doc(
						{"doctype": "Team", "team_name": "Inline", "owner_user": "Administrator"}
					)
					.insert()
					.name,
					"requested_by": "Administrator",
					"correlation_id": frappe.generate_hash(length=32),
					"status": "Queued",
				}
			).insert(ignore_permissions=True)
			submit.return_value = {"action": action.name}
			self.action = action
			return create_trial_site(None, "acme", "key-" + frappe.generate_hash(length=8))

	def test_a_refusal_comes_back_to_the_caller(self):
		def refuse(name):
			frappe.db.set_value(
				"Resource Action", name, {"status": "Failed", "error_code": "CREATE_NOT_ACCEPTED"}
			)

		status = self.start(refuse)

		self.assertEqual(status["status"], "Failed")
		self.assertEqual(status["error"]["code"], "CREATE_NOT_ACCEPTED")

	def test_a_machine_that_started_comes_back_without_an_error(self):
		def accept(name):
			frappe.db.set_value("Resource Action", name, "status", "In Progress")

		status = self.start(accept)

		self.assertEqual(status["status"], "In Progress")
		self.assertIsNone(status["error"])

	def test_a_site_request_is_never_put_on_a_queue(self):
		"""The customer is waiting on the answer, so nothing defers it to a worker."""
		team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Unqueued", "owner_user": "Administrator"}
		).insert()

		with patch("frappe.enqueue") as enqueue:
			for resource_type in ("Site", "Server"):
				frappe.get_doc(
					{
						"doctype": "Resource Action",
						"resource_type": resource_type,
						"action": "create",
						"team": team.name,
						"requested_by": "Administrator",
						"correlation_id": frappe.generate_hash(length=32),
						"status": "Queued",
					}
				).insert(ignore_permissions=True)

		# Only the server was queued.
		self.assertEqual(enqueue.call_count, 1)
