# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.signups import get_product
from central.notification import engine
from central.site_provisioning import create_trial_site
from central.tests.test_iam import ensure_user
from central.tests.test_sites import SiteOnAMachine

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestProduct(IntegrationTestCase):
	"""A product names the app its trial starts with, and only an enabled one takes signups."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)

	def product(self, product_key: str, enabled: int = 1):
		return frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": product_key,
				"title": "Raven",
				"subtitle": "Chat for your team",
				"signup_app": "raven",
				"enabled": enabled,
			}
		).insert()

	def start(self, product: str):
		"""Start a trial, keeping the mock that would ask the region for an image."""
		with (
			patch("central.site_provisioning.resolve_team", return_value="any-team"),
			patch("central.site_provisioning.validated_subdomain", return_value="acme"),
			patch("central.site_provisioning.trial_configuration", return_value={}) as configuration,
			patch("central.site_provisioning.submit_request"),
		):
			try:
				create_trial_site(None, "acme", "key", product)
			finally:
				self.configuration = configuration

	def test_a_product_trial_starts_with_its_app(self):
		self.product("raven-test")

		self.start("raven-test")

		team, product = self.configuration.call_args.args
		self.assertEqual((team, product.signup_app), ("any-team", "raven"))

	def test_a_disabled_or_unknown_product_is_refused_before_the_region_is_asked(self):
		self.product("raven-off", enabled=0)

		for product in ("raven-off", "no-such-product"):
			with self.subTest(product=product):
				with self.assertRaises(frappe.ValidationError):
					self.start(product)

				self.configuration.assert_not_called()

	def test_the_signup_pages_read_branding_of_an_enabled_product_only(self):
		self.product("raven-test")
		self.product("raven-off", enabled=0)

		self.assertEqual(get_product("raven-test").subtitle, "Chat for your team")
		self.assertIsNone(get_product("raven-off"))

	def test_the_operator_preview_asks_the_region_for_the_product_app_and_version(self):
		product = self.product("raven-test")
		product.db_set("frappe_version", "version-16")

		with (
			patch("central.site_provisioning.signup_offering", return_value="pilot"),
			patch("central.integrations.images.preview_images") as preview,
		):
			product.preview_images("par-2")

		preview.assert_called_once_with(
			"pilot",
			"par-2",
			0,
			extra_tags={"has_site": "1", "frappe_version": "version-16", "app": "raven"},
		)

	def test_a_new_product_runs_on_develop_and_takes_only_a_frappe_branch(self):
		product = self.product("raven-version")
		self.assertEqual(product.frappe_version, "develop")

		product.frappe_version = "version-16-hotfix"
		product.save()

		for version in ("16", "v16", "version-16.1", "version-16-beta", "main"):
			product.frappe_version = version
			with self.subTest(version=version), self.assertRaises(frappe.ValidationError):
				product.save()

		product.reload()
		product.frappe_version = "version-16-hotfix"
		product.save()

	def test_the_landing_route_is_a_path_on_the_site(self):
		product = self.product("raven-landing")

		for route in ("https://evil.example.test", "raven", "/raven?next=x"):
			product.landing_route = route
			with self.assertRaises(frappe.ValidationError):
				product.save()

	def test_a_product_key_is_a_lowercase_slug(self):
		with self.assertRaises(frappe.ValidationError):
			self.product("Raven App")


class TestProductEmailSettings(IntegrationTestCase):
	"""A product brands its emails only with a public logo, and adds one note per email."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")

	def product(self, product_key: str, **values):
		return frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": product_key,
				"title": "Raven",
				"signup_app": "raven",
				**values,
			}
		)

	def test_own_branding_needs_a_public_logo(self):
		for logo in (None, "/private/files/raven.png"):
			with self.subTest(logo=logo), self.assertRaisesRegex(frappe.ValidationError, "public logo"):
				self.product("raven-brand", use_own_email_branding=1, logo=logo).insert()

		self.product("raven-brand", use_own_email_branding=1, logo="/files/raven.png").insert()

	def test_one_note_for_each_email(self):
		notes = [{"event_type": "site_ready", "note": "One"}, {"event_type": "site_ready", "note": "Two"}]

		with self.assertRaisesRegex(frappe.ValidationError, "at most one note"):
			self.product("raven-notes", email_notes=notes).insert()

	def test_one_note_for_each_plan(self):
		notes = [{"plan": "plan-2vcpu", "note": "One"}, {"plan": "plan-2vcpu", "note": "Two"}]

		with self.assertRaisesRegex(frappe.ValidationError, "at most one note for each plan"):
			self.product("raven-plans", plan_notes=notes).insert()

	def test_the_getting_started_page_must_be_https(self):
		with self.assertRaisesRegex(frappe.ValidationError, "https://"):
			self.product("raven-start", getting_started_url="http://raven.example.test").insert()

	def operator(self) -> str:
		operator = ensure_user("product.operator@example.test")
		frappe.get_doc("User", operator).add_roles("Product Operator")
		return operator

	def test_a_product_operator_creates_and_edits_every_product_but_deletes_none(self):
		product = self.product("raven-any").insert()
		frappe.set_user(self.operator())

		self.assertTrue(frappe.has_permission("Product", "write", doc=product.name))
		self.assertTrue(frappe.has_permission("Product", "create"))
		self.assertFalse(frappe.has_permission("Product", "delete", doc=product.name))
		self.assertIn(product.name, frappe.get_list("Product", pluck="name"))

	def test_only_a_system_manager_previews_regional_images(self):
		product = self.product("raven-images").insert()
		frappe.set_user(self.operator())

		with (
			patch("central.integrations.images.preview_images") as preview,
			self.assertRaises(frappe.PermissionError),
		):
			product.preview_images("par-2")
		preview.assert_not_called()

	def test_an_operator_previews_and_sends_a_test_of_their_products_emails(self):
		mine = self.product(
			"raven-preview",
			use_own_email_branding=1,
			logo="/files/raven.png",
			getting_started_url="https://raven.example.test/start",
			email_notes=[{"event_type": "site_ready", "note": "Create a channel.\n\nInvite your team."}],
		).insert()
		frappe.set_user(self.operator())

		ready = mine.preview_email("site_ready")
		code = mine.preview_email("signup_code")
		with patch("frappe.sendmail") as sendmail:
			mine.send_test_email("site_ready")

		self.assertEqual(ready["subject"], "Your Raven site is ready")
		self.assertIn("Invite your team.", ready["html"])
		self.assertIn("https://raven.example.test/start", ready["html"])
		self.assertEqual(code["subject"], "123456 is your Raven signup code")
		self.assertEqual(sendmail.call_args.kwargs["recipients"], ["product.operator@example.test"])


class TestProductLifecycleEmails(SiteOnAMachine):
	"""An email about a product's site carries the product's note, and its branding when set."""

	def setUp(self):
		super().setUp()
		self.enroll()
		with patch("central.integrations.pilot.rename_admin_domain", return_value={"task_id": "task-1"}):
			from central.integrations.servers import observe_server

			observe_server(self.server)
		self.event = engine.get_event_type("site_ready")

	def email_for(self, product, team=None) -> str:
		self.site().db_set("product", product.name)
		sample = {"product": "Raven", "address": "acme", "ends_on": "1 Nov", "deletes_on": "15 Nov"}
		context = engine._resolve_context(
			team or self.team.name, self.event.name, sample, self.site().name, "Site"
		)
		context["server"] = self.site().server or ""
		return engine._notification_email(self.event, {**context, "reference_title": "acme"})[1]

	def product(self, **values):
		return frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": "raven-" + frappe.generate_hash(length=6).lower(),
				"title": "Raven & Co",
				"signup_app": "raven",
				"email_notes": [{"event_type": "site_ready", "note": "Create a <b>channel</b> first."}],
				**values,
			}
		).insert()

	def test_the_note_is_added_escaped_under_frappe_cloud_branding(self):
		html = self.email_for(self.product())

		self.assertIn("Create a &lt;b&gt;channel&lt;/b&gt; first.", html)
		self.assertIn("Frappe Cloud", html)

	def test_own_branding_shows_the_product_logo_and_title(self):
		html = self.email_for(self.product(use_own_email_branding=1, logo="/files/raven.png"))

		self.assertIn("/files/raven.png", html)
		self.assertIn("Raven &amp; Co", html)
		self.assertNotIn(">Frappe Cloud</span>", html)

	def test_only_the_welcome_emails_link_the_getting_started_page(self):
		product = self.product(getting_started_url="https://raven.example.test/start")

		html = self.email_for(product)
		self.event = engine.get_event_type("trial_expiring")
		expiring = self.email_for(product)

		self.assertIn("https://raven.example.test/start", html)
		self.assertNotIn("https://raven.example.test/start", expiring)

	def test_get_started_opens_the_site_and_the_docs_are_the_second_button(self):
		product = self.product(landing_route="/raven", getting_started_url="https://raven.example.test/start")

		html = self.email_for(product)

		self.assertIn(f'fc-btn-primary" href="{self.site().url}/raven"', html)
		self.assertIn('fc-btn-secondary" href="https://raven.example.test/start"', html)
		self.assertLess(html.index("Get started"), html.index("View docs"))

	def test_welcome_emails_link_the_created_site_and_product_landing_route(self):
		product = self.product(landing_route="/raven")
		for event_type in ("site_ready", "trial_unopened"):
			with self.subTest(event_type=event_type):
				self.event = engine.get_event_type(event_type)
				html = self.email_for(product)
				self.assertIn(f'href="{self.site().url}/raven"', html)

	def test_plain_site_ready_email_links_the_created_site(self):
		context = engine._resolve_context(self.team.name, "site_ready", {}, self.site().name, "Site")
		_, html = engine._notification_email(self.event, context)
		self.assertIn(f'href="{self.site().url}"', html)

	def test_site_emails_name_and_link_the_chosen_name(self):
		"""Every Site email names the address its button opens, the trial emails included."""
		from central.signups.trial import Trial

		site = self.site()
		site.db_set("subdomain", "acme")
		with patch(
			"central.infrastructure.doctype.region.region.Region.get_zone",
			return_value=self.region.proxy_domain,
		):
			site.route_subdomain()
		frappe.db.set_value("Site Domain", site.rename_target, "status", "Active")

		context = engine._resolve_context(self.team.name, "site_ready", None, site.name, "Site")
		context["reference_title"] = engine._get_reference_title(self.team.name, "Site", site.name)
		subject, html = engine._notification_email(self.event, context)

		self.assertEqual(subject, f"Site ready: {site.rename_target}")
		self.assertIn(f"Site {site.rename_target} is ready.", html)
		self.assertIn(f'href="https://{site.rename_target}"', html)
		self.assertEqual(Trial(self.site()).address, site.rename_target)

	def test_billing_emails_link_central_and_deleted_email_has_no_site_link(self):
		product = self.product(landing_route="/raven")
		upgrade = f'href="https://central.example.test/dashboard/servers/{self.site().server}?action=resize"'
		billing = 'href="https://central.example.test/dashboard/billing"'
		with patch("central.notification.engine.central_url", return_value="https://central.example.test"):
			for event_type in ("trial_expiring", "trial_ended", "trial_deletion_soon"):
				with self.subTest(event_type=event_type):
					self.event = engine.get_event_type(event_type)
					html = self.email_for(product)
					self.assertIn(upgrade, html)
					self.assertNotIn(f'href="{self.site().url}', html)
					self.assertIn(
						"/dashboard/servers/acme?action=resize", product.preview_email(event_type)["html"]
					)
			self.event = engine.get_event_type("trial_converted")
			html = self.email_for(product)
			self.assertIn(billing, html)
			self.assertNotIn(f'href="{self.site().url}', html)
		self.event = engine.get_event_type("trial_deleted")
		self.assertNotIn(f'href="{self.site().url}', self.email_for(product))

	def test_welcome_email_preview_uses_sample_site_and_product_landing_route(self):
		product = self.product(landing_route="/raven")
		address = product.get_preview_context()["context"]["address"]
		for event_type in ("site_ready", "trial_unopened"):
			with self.subTest(event_type=event_type):
				html = product.preview_email(event_type)["html"]
				self.assertIn(f'href="https://{address}/raven"', html)

	def test_a_pilot_message_is_escaped_in_the_email(self):
		self.event = engine.get_event_type("site_ready")
		context = engine._resolve_context(self.team.name, "site_ready", {"product": "<i>Raven</i>"}, "", "")
		_, html = engine.render_notification_email(self.event, context, {})

		self.assertIn("&lt;i&gt;Raven&lt;/i&gt;", html)

	def test_another_teams_site_adds_nothing(self):
		other = frappe.get_doc(
			{"doctype": "Team", "team_name": "Other", "owner_user": "Administrator"}
		).insert()

		html = self.email_for(
			self.product(use_own_email_branding=1, logo="/files/raven.png"), team=other.name
		)

		self.assertNotIn("channel", html)
		self.assertNotIn("/files/raven.png", html)
		self.assertNotIn(f'href="{self.site().url}', html)
