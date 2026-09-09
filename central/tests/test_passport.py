from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase

from central.api.passport import _members, registration
from central.integrations.passport import PassportError, on_site_update, site_id

ISSUER = "https://passport.example"
OPERATOR = "central.integrations.passport.PassportOperator._call"


class PassportProvisioningTestCase(IntegrationTestCase):
	"""Fixtures: a team, a bench credential and a running site Central provisioned."""

	def setUp(self):
		super().setUp()
		frappe.db.delete("Passport Registration")
		self.enable_passport()
		self.cluster = self.make_cluster()
		self.team = self.make_team()
		self.credential = self.make_credential(self.team)
		self.site = self.make_site(self.team, self.credential)
		# The endpoint resolves its caller from the X-Pilot-Token header, which needs a request.
		self.acting = frappe.get_doc("Pilot Credential", self.credential)
		self.enterContext(patch("frappe.get_request_header", return_value="pilot-token"))
		self.enterContext(
			patch("central.api.pilot.PilotCredential.verify", side_effect=lambda token: self.acting)
		)

	def enable_passport(self):
		settings = frappe.get_single("Central Passport Settings")
		settings.update({"enabled": 1, "issuer": ISSUER, "api_key": "key", "api_secret": "secret"})
		settings.save()
		frappe.clear_document_cache("Central Passport Settings", "Central Passport Settings")

	def make_team(self, user: str | None = None) -> str:
		user = user or self.make_user()
		team = frappe.get_doc(
			doctype="Team",
			team_name=f"Team {uuid4().hex[:6]}",
			owner_user=user,
			status="Active",
			members=[{"user": user, "role": "Owner", "resource_type": "*", "status": "Active"}],
		).insert(ignore_permissions=True)
		return team.name

	def make_user(self) -> str:
		return (
			frappe.get_doc(
				doctype="User", email=f"{uuid4()}@example.com", first_name="Member", send_welcome_email=0
			)
			.insert()
			.name
		)

	def make_credential(self, team: str) -> str:
		return (
			frappe.get_doc(
				doctype="Pilot Credential",
				pilot_credential_id=str(uuid4()),
				team=team,
				token_hash=uuid4().hex,
				status="Active",
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_cluster(self) -> str:
		region = f"test-{uuid4().hex[:6]}"
		frappe.get_doc(doctype="Region", region=region, display_name=region).insert(ignore_permissions=True)
		frappe.get_doc(
			doctype="Atlas Instance",
			region=region,
			base_url="https://atlas.example",
			status="Active",
			api_key="key",
			api_secret="secret",
		).insert(ignore_permissions=True)
		return region

	def make_site(self, team: str, credential: str, *, url: str | None = None) -> str:
		name = f"{uuid4().hex[:8]}.example.com"
		frappe.get_doc(
			doctype="Site",
			site_name=name,
			subdomain=name.split(".")[0],
			team=team,
			cluster=self.cluster,
			status="Running",
			url=url or f"https://{name}",
			pilot_credential_id=credential,
		).insert(ignore_permissions=True)
		return name

	def owner(self) -> str:
		return frappe.db.get_value("Team", self.team, "owner_user")

	def credentials(self, **overrides) -> dict:
		return {
			"site_id": site_id(self.site),
			"client_id": str(uuid4()),
			"client_secret": "site-secret",
			**overrides,
		}


class TestPassportProvisioning(PassportProvisioningTestCase):
	"""Central registers the sites it hands out, and hands each one only its own."""

	def test_first_ask_registers_the_site_and_names_its_members(self):
		with patch(OPERATOR, return_value=self.credentials()) as call:
			result = registration(self.site)

		self.assertEqual(call.call_args.args[0], "passport.registration.register_site")
		self.assertEqual(result["issuer"], ISSUER)
		self.assertEqual(result["origin"], f"https://{self.site}")
		self.assertEqual([member["email"] for member in result["members"]], [self.owner()])
		record = frappe.get_doc("Passport Registration", self.site)
		self.assertEqual(record.client_id, result["client_id"])
		self.assertTrue(record.enabled)

	def test_repeating_the_ask_does_not_re_register(self):
		with patch(OPERATOR, return_value=self.credentials()):
			first = registration(self.site)
		with patch(OPERATOR, return_value=self.credentials(client_id=first["client_id"])) as call:
			again = registration(self.site)

		self.assertEqual(again["client_id"], first["client_id"])
		self.assertEqual(call.call_args.args[0], "passport.registration.register_site")
		self.assertEqual(frappe.db.count("Passport Registration", {"site": self.site}), 1)

	def test_a_moved_site_is_re_addressed_and_given_a_fresh_secret(self):
		with patch(OPERATOR, return_value=self.credentials()):
			first = registration(self.site)

		frappe.db.set_value("Site", self.site, "url", "https://moved.example.com")
		rotated = self.credentials(client_id=first["client_id"], client_secret="rotated")

		with patch(OPERATOR, return_value=rotated) as call:
			moved = registration(self.site)

		methods = [args.args[0] for args in call.call_args_list]
		self.assertEqual(
			methods, ["passport.registration.update_site", "passport.registration.rotate_secret"]
		)
		self.assertEqual(moved["client_secret"], "rotated")
		self.assertEqual(moved["origin"], "https://moved.example.com")
		self.assertEqual(frappe.db.get_value("Passport Registration", self.site, "origin"), moved["origin"])

	def test_a_bench_cannot_fetch_another_teams_site(self):
		other_team = self.make_team()
		other_site = self.make_site(other_team, self.make_credential(other_team))

		with self.assertRaises(frappe.PermissionError):
			registration(other_site)

	def test_a_bench_cannot_fetch_a_site_on_another_bench(self):
		sibling = self.make_site(self.team, self.make_credential(self.team))

		with self.assertRaises(frappe.PermissionError):
			registration(sibling)

	def test_a_site_that_is_not_running_gets_nothing(self):
		frappe.db.set_value("Site", self.site, "status", "Provisioning")

		with self.assertRaises(PassportError):
			registration(self.site)

	def test_members_cover_team_wide_and_site_scoped_entitlements(self):
		team_wide = self.owner()
		this_site = self.make_user()
		other_site = self.make_user()
		team = frappe.get_doc("Team", self.team)
		for user, resource in ((this_site, self.site), (other_site, "elsewhere")):
			team.append(
				"members",
				{
					"user": user,
					"role": "Admin",
					"resource_type": "Site",
					"resource_name": resource,
					"status": "Active",
				},
			)
		team.save(ignore_permissions=True)

		site = frappe.db.get_value("Site", self.site, ["name", "team"], as_dict=True)
		entitled = {member["email"] for member in _members(site)}

		self.assertEqual(entitled, {team_wide, this_site})

	def test_terminating_a_site_queues_its_registration_for_removal(self):
		with patch(OPERATOR, return_value=self.credentials()):
			registration(self.site)

		document = frappe.get_doc("Site", self.site)
		document.status = "Terminated"

		with patch("frappe.enqueue") as enqueue:
			on_site_update(document)

		self.assertEqual(enqueue.call_args.kwargs["site_name"], self.site)


class TestRegistrationPayload(PassportProvisioningTestCase):
	"""Passport requires a site to declare both of its own endpoints."""

	def test_registration_names_where_sign_in_starts_and_sign_out_arrives(self):
		with patch(OPERATOR, return_value=self.credentials()) as call:
			registration(self.site)

		sent = call.call_args.args[1]
		origin = f"https://{self.site}"

		self.assertEqual(sent["origin"], origin)
		self.assertTrue(sent["login_uri"].startswith(origin + "/api/method/"))
		self.assertIn("provider=Passport", sent["login_uri"])
		self.assertEqual(
			sent["backchannel_logout_uri"],
			origin + "/api/method/frappe.integrations.openid_connect.logout.receive",
		)

	def test_re_addressing_carries_the_moved_endpoints(self):
		with patch(OPERATOR, return_value=self.credentials()):
			registration(self.site)

		moved = f"https://moved-{uuid4().hex[:6]}.example.com"
		frappe.db.set_value("Site", self.site, "url", moved)

		with patch(OPERATOR, return_value=self.credentials()) as call:
			registration(self.site)

		readdress = next(
			args for args, _ in call.call_args_list if args[0] == "passport.registration.update_site"
		)
		self.assertTrue(readdress[1]["login_uri"].startswith(moved + "/api/method/"))
		self.assertEqual(readdress[1]["origin"], moved)


class TestReconcile(PassportProvisioningTestCase):
	"""The backstop for a Terminated event that never arrived."""

	def test_a_registration_for_a_site_that_stopped_running_is_withdrawn(self):
		from central.integrations.passport import reconcile

		with patch(OPERATOR, return_value=self.credentials()):
			registration(self.site)

		# Bypass the doc event, so only reconcile can be what withdraws it.
		frappe.db.set_value("Site", self.site, "status", "Suspended")

		with patch(OPERATOR, return_value={}):
			reconcile()

		self.assertEqual(frappe.db.get_value("Passport Registration", self.site, "enabled"), 0)

	def test_a_running_site_keeps_its_registration(self):
		from central.integrations.passport import reconcile

		with patch(OPERATOR, return_value=self.credentials()):
			registration(self.site)

		with patch(OPERATOR, return_value={}) as call:
			reconcile()

		self.assertEqual(call.call_count, 0)
		self.assertEqual(frappe.db.get_value("Passport Registration", self.site, "enabled"), 1)


class TestSettings(IntegrationTestCase):
	"""The local demo needs an http issuer; production must not get one by accident."""

	def settings(self, **values):
		settings = frappe.get_single("Central Passport Settings")
		settings.update({"enabled": 1, "api_key": "key", "api_secret": "secret", **values})

		return settings

	def tearDown(self):
		frappe.db.rollback()

	def test_a_local_http_issuer_is_refused_by_default(self):
		with self.assertRaises(frappe.ValidationError):
			self.settings(issuer="http://passport.localhost:8001", allow_local_http=0).save()

	def test_a_local_http_issuer_is_allowed_when_opted_into(self):
		self.settings(issuer="http://passport.localhost:8001", allow_local_http=1).save()

		self.assertEqual(
			frappe.db.get_single_value("Central Passport Settings", "issuer"),
			"http://passport.localhost:8001",
		)

	def test_the_opt_in_does_not_permit_plain_http_generally(self):
		with self.assertRaises(frappe.ValidationError):
			self.settings(issuer="http://passport.example", allow_local_http=1).save()

	def test_an_issuer_with_a_path_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.settings(issuer="https://passport.example/id", allow_local_http=0).save()


class TestCentralAsAClient(PassportProvisioningTestCase):
	"""Central signs its own users in with Frappe identities, like any other site."""

	def test_connecting_installs_centrals_own_registration(self):
		from central.integrations import passport

		with (
			patch(OPERATOR, return_value=self.credentials()),
			patch("central.sso.central_url", return_value="https://cloud.example"),
			patch(
				"frappe.integrations.frappe_providers.cloud_passport_enrollment.configure",
				return_value="Passport",
			) as configure,
		):
			result = passport.connect_central()

		self.assertEqual(result["provider"], "Passport")
		self.assertEqual(configure.call_args.kwargs["origin"], "https://cloud.example")

	def test_connecting_as_administrator_links_nobody(self):
		"""Administrator can never hold a Frappe identity, so the operator still has to
		name who may sign in."""
		from central.integrations import passport

		with (
			patch(OPERATOR, return_value=self.credentials()),
			patch("central.sso.central_url", return_value="https://cloud.example"),
			patch(
				"frappe.integrations.frappe_providers.cloud_passport_enrollment.configure",
				return_value="Passport",
			),
		):
			result = passport.connect_central()

		self.assertEqual(result["linked"], [])
		self.assertEqual(result["pending"], [])

	def test_a_named_user_is_linked_so_they_can_sign_in(self):
		from central.integrations.passport import link_cloud_users

		user = self.make_user()
		email = frappe.db.get_value("User", user, "email")

		with patch(
			"frappe.integrations.frappe_providers.cloud_passport_memberships.link_users",
			return_value=([email], []),
		) as link:
			linked, pending = link_cloud_users([email])

		self.assertEqual(link.call_args.args[0], {email: user})
		self.assertEqual(linked, [email])
		self.assertEqual(pending, [])

	def test_linking_skips_addresses_central_does_not_know(self):
		from central.integrations.passport import link_cloud_users

		# No local user, so there is nothing to link and no call to the provider.
		self.assertEqual(link_cloud_users([f"{uuid4()}@example.com"]), ([], []))

	def test_linking_never_targets_a_system_account(self):
		from central.integrations.passport import link_cloud_users

		administrator = frappe.db.get_value("User", "Administrator", "email")

		self.assertEqual(link_cloud_users([administrator, "guest@example.com"]), ([], []))

	def test_a_disabled_user_is_not_linked(self):
		from central.integrations.passport import link_cloud_users

		user = self.make_user()
		email = frappe.db.get_value("User", user, "email")
		frappe.db.set_value("User", user, "enabled", 0)

		self.assertEqual(link_cloud_users([email]), ([], []))


class TestTeamMembershipLinking(PassportProvisioningTestCase):
	"""Entitlement follows team membership: joining a team should let you sign in."""

	LINK = "frappe.integrations.frappe_providers.cloud_passport_memberships.link_users"

	def setUp(self):
		super().setUp()
		frappe.db.delete("OpenID Connect Provider")
		frappe.get_doc(
			doctype="OpenID Connect Provider",
			provider_name="Passport",
			issuer=ISSUER,
			client_id=str(uuid4()),
			client_secret="secret",
			redirect_uri="https://cloud.example/api/method/x",
			enabled=1,
		).insert(ignore_permissions=True)

	def test_a_teams_active_members_are_linked(self):
		from central.integrations.passport import link_team_members

		owner_email = frappe.db.get_value("User", self.owner(), "email")

		with patch(self.LINK, return_value=([owner_email], [])) as link:
			linked, pending = link_team_members(self.team)

		self.assertEqual(link.call_args.args[0], {owner_email: self.owner()})
		self.assertEqual(linked, [owner_email])
		self.assertEqual(pending, [])

	def test_someone_without_a_frappe_identity_waits_rather_than_failing(self):
		from central.integrations.passport import link_team_members

		owner_email = frappe.db.get_value("User", self.owner(), "email")

		with patch(self.LINK, return_value=([], [owner_email])):
			linked, pending = link_team_members(self.team)

		self.assertEqual(linked, [])
		self.assertEqual(pending, [owner_email])

	def test_the_reconcile_links_someone_who_has_since_signed_in(self):
		"""The team event is the fast path; this is what rescues an earlier pending."""
		from central.integrations.passport import link_unlinked_members

		owner_email = frappe.db.get_value("User", self.owner(), "email")

		with patch(self.LINK, return_value=([owner_email], [])):
			self.assertIn(owner_email, link_unlinked_members())

	def test_a_team_change_never_links_inline(self):
		"""Accepting an invitation must not fail when the identity service is unreachable,
		so the handler only ever queues work — never calls out itself."""
		from central.integrations.passport import on_team_update

		with patch(self.LINK, side_effect=AssertionError("must not be called inline")):
			on_team_update(frappe.get_doc("Team", self.team))

	def test_nothing_is_queued_when_frappe_sign_in_is_off(self):
		from central.integrations.passport import on_team_update

		frappe.db.delete("OpenID Connect Provider")

		with patch("frappe.enqueue") as enqueue:
			on_team_update(frappe.get_doc("Team", self.team))

		self.assertEqual(enqueue.call_count, 0)
