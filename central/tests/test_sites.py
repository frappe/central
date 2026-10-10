from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.sites import claim_site, get_site, login_site, onboarding_status, terminate_site
from central.errors import AtlasResourceGone
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.resource_action.resource_action import ResourceAction
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
from central.tests.test_iam import ensure_user
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
		self.region = frappe.get_doc(
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
				"region": self.region.name,
				"atlas_vm_id": "vm-00001",
				"status": "Provisioning",
				"has_site": 1,
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

	def record_creation(self, has_site: str) -> None:
		"""Save the creation request that built this machine from an image with this tag."""
		ResourceAction.queue(
			"create",
			self.team.name,
			self.region.name,
			self.server.name,
			server=self.server.name,
			request_key="request-" + frappe.generate_hash(length=8),
			request_payload={"image_tags": {"purpose": "pilot", "has_site": has_site}},
		)


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

	def test_the_site_is_for_the_product_its_trial_request_named(self):
		frappe.get_doc(
			{"doctype": "Product", "product_key": "raven-site", "title": "Raven", "signup_app": "raven"}
		).insert()
		ResourceAction.queue(
			"create",
			self.team.name,
			self.region.name,
			self.server.name,
			server=self.server.name,
			resource_type="Site",
			request_key="request-" + frappe.generate_hash(length=8),
			request_payload={"image_tags": {"purpose": "pilot"}, "site": {"product": "raven-site"}},
		)
		self.enroll()
		observe_server(self.server)

		self.assertEqual(self.site().product, "raven-site")

	def test_a_machine_with_no_enrolled_pilot_has_no_site(self):
		observe_server(self.server)

		self.assertFalse(frappe.db.exists("Site", {"server": self.server.name}))

	def test_a_machine_whose_image_has_no_site_has_no_site(self):
		self.server.db_set("has_site", 0)
		self.enroll()
		observe_server(self.server)

		self.assertFalse(frappe.db.exists("Site", {"server": self.server.name}))

	def test_the_patch_removes_a_site_its_machine_never_carried(self):
		from central.patches.v0_0.record_server_has_site import execute

		self.enroll()
		observe_server(self.server)
		self.server.db_set("has_site", 0)
		self.record_creation(has_site="0")

		execute()

		self.assertFalse(frappe.db.exists("Site", {"server": self.server.name}))

	def test_the_patch_keeps_a_site_when_no_request_names_the_image(self):
		from central.patches.v0_0.record_server_has_site import execute

		self.enroll()
		observe_server(self.server)
		self.server.db_set("has_site", 0)

		execute()

		self.assertTrue(frappe.db.exists("Site", {"server": self.server.name}))
		self.assertEqual(self.server.reload().has_site, 1)

	def test_the_patch_keeps_the_domain_of_a_site_it_removes(self):
		from central.patches.v0_0.record_server_has_site import execute

		self.enroll()
		observe_server(self.server)
		frappe.db.set_single_value("Central Settings", "wildcard_domain", "example.test")
		domain = frappe.get_doc(
			{
				"doctype": "Site Domain",
				"domain": "shop.example.com",
				"team": self.team.name,
				"region": self.region.name,
				"server": self.server.name,
				"site": self.site().name,
			}
		).insert()
		self.server.db_set("has_site", 0)
		self.record_creation(has_site="0")

		execute()

		self.assertFalse(frappe.db.exists("Site", {"server": self.server.name}))
		self.assertIsNone(frappe.db.get_value("Site Domain", domain.name, "site"))

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

	def test_first_successful_probe_records_and_announces_readiness(self):
		site = self.site()
		with (
			patch("central.api.sites.is_site_reachable", return_value=True),
			patch("central.notification.engine.queue_event") as queue_event,
		):
			get_site(site.name)
			get_site(site.name)

		self.assertTrue(site.reload().ready_at)
		queue_event.assert_called_once_with(
			site.team,
			"site_ready",
			reference_doctype="Site",
			reference_name=site.name,
		)

	def test_status_read_does_not_create_a_login(self):
		with (
			patch("central.api.sites.is_site_reachable", return_value=True),
			patch(
				"central.integrations.pilot.fetch_site_login_url",
				return_value="https://site.local/desk?sid=abc",
			) as login,
		):
			state = get_site(self.site().name)

		self.assertTrue(state["ready"])
		self.assertIsNone(state["login_url"])
		login.assert_not_called()

	def test_explicit_login_hands_back_a_sign_in_url(self):
		with (
			patch("central.api.sites.is_site_reachable", return_value=True),
			patch(
				"central.integrations.pilot.fetch_site_login_url",
				return_value="https://site.local/desk?sid=abc",
			) as login,
		):
			state = login_site(self.site().name)

		self.assertEqual(login.call_args.args[2], "site.local")
		self.assertEqual(state["login_url"], "https://site-1z141z4.par-2.example.test/desk?sid=abc")

	def test_a_product_site_lands_on_the_products_page(self):
		product = frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": "raven",
				"title": "Raven",
				"signup_app": "raven",
				"landing_route": "/raven",
			}
		).insert(ignore_if_duplicate=True)
		self.site().db_set("product", product.name)
		with (
			patch("central.api.sites.is_site_reachable", return_value=True),
			patch(
				"central.integrations.pilot.fetch_site_login_url",
				return_value="https://site.local/desk?sid=abc",
			),
		):
			state = login_site(self.site().name)

		self.assertEqual(state["login_url"], "https://site-1z141z4.par-2.example.test/raven?sid=abc")

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
			state = login_site(self.site().name)

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
		with self.assertRaises(frappe.PermissionError):
			login_site(self.site().name)

	def test_a_viewer_reads_a_site_but_cannot_sign_in_as_administrator(self):
		viewer = ensure_user("site.viewer@example.test")
		self.team.append("members", {"user": viewer, "role": "Viewer", "status": "Active"})
		self.team.save()
		frappe.set_user(viewer)

		with patch("central.api.sites.is_site_reachable", return_value=False):
			self.assertEqual(get_site(self.site().name)["name"], self.site().name)
		with self.assertRaises(frappe.PermissionError):
			login_site(self.site().name)
		with self.assertRaises(frappe.PermissionError):
			claim_site(self.site().name)

	def test_an_operator_opens_a_site_and_both_records_note_it(self):
		site = self.site()
		with patch.object(type(site), "get_login_url", return_value="https://site.example.test/desk?sid=x"):
			self.assertEqual(site.open_as_administrator(), "https://site.example.test/desk?sid=x")

		for doctype, name in (("Site", site.name), ("Virtual Machine", site.server)):
			self.assertTrue(
				frappe.db.exists(
					"Comment",
					{
						"reference_doctype": doctype,
						"reference_name": name,
						"content": ("like", "%as Administrator%"),
					},
				)
			)

		frappe.set_user(ensure_user("site.member@example.test"))
		with self.assertRaises(frappe.PermissionError):
			site.open_as_administrator()

	def test_an_operator_checks_readiness_and_it_is_recorded(self):
		site = self.site()
		with patch("central.integrations.pilot.is_site_reachable", return_value=True):
			self.assertTrue(site.check_readiness())
		self.assertTrue(site.reload().ready_at)

	def test_a_missing_site_and_a_foreign_site_answer_alike(self):
		frappe.set_user(ensure_user("outsider@example.test"))

		with self.assertRaises(frappe.PermissionError) as foreign:
			get_site(self.site().name)
		with self.assertRaises(frappe.PermissionError) as missing:
			get_site("no-such-site.example.test")
		self.assertEqual(str(foreign.exception), str(missing.exception))

	def test_status_is_get_and_login_is_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[get_site], ("GET", "QUERY"))
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[login_site], ("POST",))

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

	def test_another_product_does_not_resume_the_existing_site(self):
		raven = self.signup_product("raven-return")
		crm = self.signup_product("crm-return")
		self.site().db_set("product", raven)
		self.creation_action("Site", raven)

		self.assertEqual(onboarding_status(self.team.name, crm), {"site": None, "creation": None})

	def test_a_claimed_product_site_is_found_without_a_new_login(self):
		product = self.signup_product("raven-return")
		self.site().db_set({"product": product, "claimed_at": frappe.utils.now_datetime()})
		with patch("central.api.sites.is_site_reachable", return_value=False):
			state = onboarding_status(self.team.name, product)

		self.assertEqual(state["site"]["name"], self.site().name)
		self.assertTrue(state["site"]["claimed"])
		self.assertIsNone(state["site"]["login_url"])

	def test_a_product_resumes_its_pending_action_before_a_site_exists(self):
		product = self.signup_product("crm-return")
		action = self.creation_action("Site", product)
		frappe.db.set_value("Resource Action", action, {"server": None, "status": "Queued"})
		self.creation_action("Site", self.signup_product("raven-return"))

		state = onboarding_status(self.team.name, product)

		self.assertIsNone(state["site"])
		self.assertEqual(state["creation"]["action"], action)

	def test_a_plain_signup_does_not_resume_a_product_trial(self):
		self.creation_action("Site", self.signup_product("raven-return"))

		self.assertEqual(onboarding_status(self.team.name), {"site": None, "creation": None})

	def test_a_terminated_product_site_does_not_block_a_new_trial(self):
		product = self.signup_product("raven-return")
		self.site().db_set("product", product)
		self.creation_action("Site", product)
		self.server.db_set("status", "Terminated")

		self.assertEqual(onboarding_status(self.team.name, product), {"site": None, "creation": None})

	def test_another_team_cannot_resume_a_product_site(self):
		product = self.signup_product("raven-return")
		self.site().db_set("product", product)
		user = frappe.get_doc(
			{"doctype": "User", "email": "product-outsider@example.test", "first_name": "Outsider"}
		).insert()
		frappe.set_user(user.name)

		with self.assertRaises(frappe.PermissionError):
			onboarding_status(self.team.name, product)

	def test_the_patch_records_the_product_of_existing_trial_actions(self):
		from central.patches.v0_0.record_trial_action_product import execute

		product = self.signup_product("raven-return")
		action = self.creation_action("Site")
		frappe.db.set_value(
			"Resource Action", action, "request_payload", frappe.as_json({"site": {"product": product}})
		)

		execute()

		self.assertEqual(frappe.db.get_value("Resource Action", action, "product"), product)

	def signup_product(self, key: str) -> str:
		return (
			frappe.get_doc({"doctype": "Product", "product_key": key, "title": key, "signup_app": "raven"})
			.insert()
			.name
		)

	def creation_action(self, resource_type: str, product: str | None = None) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Resource Action",
					"resource_type": resource_type,
					"product": product,
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

	def test_a_login_token_names_the_user_or_administrator(self):
		from central.sso import mint_site_login

		with patch("central.sso._mint") as mint:
			mint_site_login("pilot-1", "site.local", "asha@example.test", "Asha Rao")
			mint_site_login("pilot-1", "site.local")

		self.assertEqual(
			mint.call_args_list[0].args[3],
			{"sub": "asha@example.test", "site": "site.local", "name": "Asha Rao"},
		)
		self.assertEqual(mint.call_args_list[1].args[3], {"sub": "admin", "site": "site.local"})

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
		return {
			"items": [{"id": f"image-{index}", "created_at": index, "tags": {}} for index in range(count)]
		}

	def resolve(self, page: dict, signup_app: str | None = None) -> tuple[dict, dict]:
		with (
			patch("central.site_provisioning.signup_offering", return_value="pilot"),
			patch("central.site_provisioning.trial_region_and_plan", return_value=("par-2", "plan-trial")),
			patch("central.site_provisioning.list_images", return_value=page) as list_images,
		):
			return trial_configuration("any-team", signup_app), list_images.call_args.kwargs

	def test_the_region_is_asked_for_a_site_image_on_the_signup_version(self):
		"""The tags ride the regional query, so a page of other images cannot hide a match."""
		_, asked = self.resolve(self.images(1))

		self.assertEqual(asked["extra_tags"], {"has_site": "1", "frappe_version": "develop"})

	def test_the_newest_offered_image_is_chosen(self):
		configuration, _ = self.resolve(self.images(3))

		self.assertEqual(configuration["image_id"], "image-2")

	def test_an_image_with_a_signup_app_is_never_chosen(self):
		"""The newest build can be one with an app on its site, which a trial must not get."""
		page = self.images(2)
		page["items"].append({"id": "image-erpnext", "created_at": 5, "tags": {"app": "erpnext"}})

		configuration, _ = self.resolve(page)

		self.assertEqual(configuration["image_id"], "image-1")

	def test_a_product_trial_asks_the_region_for_its_app(self):
		page = {"items": [{"id": "image-raven", "created_at": 1, "tags": {"app": "raven"}}]}

		configuration, asked = self.resolve(page, signup_app="raven")

		self.assertEqual(asked["extra_tags"], {"has_site": "1", "frappe_version": "develop", "app": "raven"})
		self.assertEqual(configuration["image_id"], "image-raven")

	def test_a_region_with_only_app_images_stops_the_trial(self):
		page = {"items": [{"id": "image-crm", "created_at": 1, "tags": {"app": "crm"}}]}

		with self.assertRaises(frappe.ValidationError):
			self.resolve(page)

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

	def test_a_renamed_site_signs_in_under_its_new_name(self):
		site = self.site()
		site.db_set("rename_task", "task-2")

		with patch(
			"central.integrations.pilot.fetch_site_login_url",
			side_effect=[None, "https://site.local/desk?sid=abc"],
		) as login:
			self.assertTrue(site.get_login_url())

		self.assertEqual([call.args[2] for call in login.call_args_list], [site.rename_target, "site.local"])

	def test_the_address_stays_ours_and_theirs_is_only_a_rename_target(self):
		site = self.site()

		self.assertEqual(site.url, "https://site-1z141z4.par-2.example.test")
		self.assertEqual(site.rename_target, "acme.par-2.example.test")

	def test_naming_renames_the_bench_onto_their_address_once(self):
		with patch("central.integrations.pilot.rename_site", return_value={"task_id": "task-1"}) as rename:
			self.site().apply_subdomain()
			self.site().apply_subdomain()

		rename.assert_called_once_with(
			self.server.name, "site.local", "acme.par-2.example.test", make_primary=True
		)
		self.assertEqual(self.site().rename_task, "task-1")

	def test_a_site_nobody_named_is_never_renamed(self):
		self.site().db_set("subdomain", None)

		with patch("central.integrations.pilot.rename_site") as rename:
			self.site().apply_subdomain()

		rename.assert_not_called()

	def test_a_failed_rename_is_traceable_and_retryable(self):
		site = self.site()
		with patch("central.integrations.pilot.rename_site", side_effect=OSError("pilot unavailable")):
			site.apply_subdomain()

		self.assertIn("Retry", site.rename_error)
		self.assertIn("pilot unavailable", frappe.db.get_value("Error Log", site.rename_error_log, "error"))

		self.enqueue_doc.reset_mock()
		site.retry_subdomain_rename()

		self.enqueue_doc.assert_called_once()
		self.assertIsNone(site.rename_error)


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

		server = self.server.reload()
		self.assertIsNone(server.admin_domain_task)
		self.assertIn("retry", server.admin_domain_error)
		self.assertIn("unreachable", frappe.db.get_value("Error Log", server.admin_domain_error_log, "error"))

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


class TestTrialCreationIsQueued(IntegrationTestCase):
	"""A trial returns durable intent while the regional operation runs after commit."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)

	def start(self):
		from central.site_provisioning import create_trial_site

		with (
			patch("central.site_provisioning.validated_subdomain", return_value="acme"),
			patch("central.site_provisioning.trial_configuration", return_value={}),
			patch("central.site_provisioning.submit_request") as submit,
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
			submit.return_value = action.customer_status()
			self.action = action
			return create_trial_site(None, "acme", "key-" + frappe.generate_hash(length=8))

	def test_creation_returns_the_queued_action(self):
		status = self.start()

		self.assertEqual(status["status"], "Queued")
		self.assertEqual(status["action"], self.action.name)

	def test_site_and_server_requests_use_the_same_queue(self):
		team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Queued", "owner_user": "Administrator"}
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

		self.assertEqual(enqueue.call_count, 2)


class TestTrialFunnelEvents(SiteOnAMachine):
	"""A trial's create request sends its funnel step once, with the product it named."""

	def queue(self, resource_type: str):
		return ResourceAction.queue(
			"create",
			self.team.name,
			self.region.name,
			self.server.name,
			resource_type=resource_type,
			request_key="request-" + frappe.generate_hash(length=8),
			request_payload={"image_tags": {"purpose": "pilot"}, "site": {"product": "raven"}},
		)

	def test_a_trial_request_is_sent_once_with_its_product(self):
		with patch("frappe.utils.telemetry.capture") as capture:
			self.queue("Site")

		capture.assert_called_once()
		self.assertEqual(capture.call_args.args[0], "trial_requested")
		self.assertEqual(capture.call_args.kwargs["properties"]["product"], "raven")

	def test_a_server_request_sends_no_trial_event(self):
		with patch("frappe.utils.telemetry.capture") as capture:
			self.queue("Server")

		capture.assert_not_called()


class TestTrialSignIn(SiteOnAMachine):
	"""A member of the team signs in to their trial site as themselves."""

	def setUp(self):
		super().setUp()
		ResourceAction.queue(
			"create",
			self.team.name,
			self.region.name,
			self.server.name,
			server=self.server.name,
			resource_type="Site",
			request_key="request-" + frappe.generate_hash(length=8),
			request_payload={"image_tags": {"purpose": "pilot"}, "site": {"product": None}},
		)
		self.enroll()
		observe_server(self.server)

	def test_a_team_member_signs_in_as_themselves_and_an_outsider_as_administrator(self):
		site = self.site()

		self.assertEqual(site.get_login_user("Administrator")[0], "Administrator")
		self.assertEqual(site.get_login_user("outsider@example.test"), (None, None))

	def test_a_site_that_is_not_a_trial_keeps_administrator(self):
		frappe.db.delete("Resource Action", {"server": self.server.name})

		self.assertEqual(self.site().get_login_user("Administrator"), (None, None))
