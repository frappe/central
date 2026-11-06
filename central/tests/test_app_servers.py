from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe
import yaml

from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.images import get_app_subdomain, get_minimum_shape, is_shape_enough
from central.resource_actions import _get_user_data, _validate_app_size

SHAPE = {"cpu_millicores": 1000, "memory_mib": 1024, "disk_mib": 10240}
APP_IMAGE = {"tags": {"purpose": "one-click", "application": "redis"}, "rootfs_size_mib": 4096}
UBUNTU_IMAGE = {"tags": {"purpose": "base"}, "rootfs_size_mib": 4096}


APP_INPUTS = [
	{"name": "domain", "label": "Domain", "type": "domain", "required": False},
	{"name": "admin_email", "label": "Admin email", "type": "email", "required": True},
	{"name": "admin_password", "label": "Admin password", "type": "password"},
]
EMAIL = {"admin_email": "me@example.com"}


def requirements(inputs: list[dict] | None = None, **minimum: int) -> dict:
	return {
		"inputs": inputs or [],
		"minimum_size": {"cpu_millicores": 500, "memory_mib": 512, "disk_mib": 5120, **minimum},
		"ports": [],
	}


def server_input(**values) -> SimpleNamespace:
	return SimpleNamespace(**{"region": "region-a", "user_data": "", "app_inputs": {}, **values})


class TestAppSize(TestCase):
	def test_a_big_enough_server_passes(self) -> None:
		_validate_app_size(APP_IMAGE, requirements(), SHAPE)

	def test_a_server_smaller_than_the_app_is_refused(self) -> None:
		for minimum in ({"cpu_millicores": 2000}, {"memory_mib": 2048}, {"disk_mib": 20480}):
			with self.subTest(minimum=minimum), self.assertRaises(frappe.ValidationError):
				_validate_app_size(APP_IMAGE, requirements(**minimum), SHAPE)

	def test_a_server_without_app_requirements_is_not_checked(self) -> None:
		_validate_app_size(UBUNTU_IMAGE, None, {**SHAPE, "cpu_millicores": 100})

	def test_a_plan_must_reach_the_app_minimum(self) -> None:
		minimum = get_minimum_shape(APP_IMAGE, requirements())

		self.assertEqual(minimum, {"cpu_millicores": 500, "memory_mib": 512, "disk_mib": 5120})
		self.assertTrue(is_shape_enough({"Compute": 0.5, "Memory": 0.5, "Disk": 5}, minimum))
		self.assertFalse(is_shape_enough({"Compute": 0.25, "Memory": 1, "Disk": 10}, minimum))

	def test_the_image_disk_counts_when_it_is_bigger(self) -> None:
		image = {**APP_IMAGE, "rootfs_size_mib": 8192}

		self.assertEqual(get_minimum_shape(image, requirements())["disk_mib"], 8192)


class TestAppUserData(TestCase):
	def test_answers_are_written_to_inputs_env_shell_quoted(self) -> None:
		password = "it's $(reboot) #1"
		answers = {"admin_password": password, "admin_email": "me@example.com", "domain": "app.example.com"}

		user_data = _get_user_data(server_input(app_inputs=answers), requirements(APP_INPUTS))

		self.assertTrue(user_data.startswith("#cloud-config\n"))
		[file] = yaml.safe_load(user_data)["write_files"]
		self.assertEqual((file["path"], file["permissions"]), ("/etc/one-click/inputs.env", "0600"))
		self.assertEqual(
			file["content"],
			"DOMAIN=app.example.com\nADMIN_EMAIL=me@example.com\nADMIN_PASSWORD='it'\"'\"'s $(reboot) #1'\n",
		)

	def test_a_routed_app_gets_its_full_site_domain(self) -> None:
		inputs = [{"name": "site_name", "label": "Site name", "required": True}]
		with patch("central.resource_actions.Region.get_zone", return_value="region-a.example.com"):
			user_data = _get_user_data(
				server_input(app_inputs={"site_name": "metrics"}), requirements(inputs), "metrics"
			)

		self.assertEqual(
			yaml.safe_load(user_data)["write_files"][0]["content"],
			"SITE_NAME=metrics\nSITE_DOMAIN=metrics.region-a.example.com\n",
		)

	def test_a_blank_answer_is_left_for_the_server(self) -> None:
		user_data = _get_user_data(
			server_input(app_inputs={**EMAIL, "admin_password": "  "}), requirements(APP_INPUTS)
		)

		self.assertEqual(
			yaml.safe_load(user_data)["write_files"][0]["content"], "ADMIN_EMAIL=me@example.com\n"
		)

	def test_an_app_without_answers_takes_no_user_data(self) -> None:
		self.assertEqual(_get_user_data(server_input(), requirements()), "")

	def test_invalid_answers_are_refused(self) -> None:
		for answers, message in (
			({}, "Admin email is required"),
			({"admin_email": "not an email"}, "not a valid Email Address"),
			({**EMAIL, "domain": "not a domain"}, "Domain must be a domain name"),
			({**EMAIL, "domain": "a" * 300 + ".com"}, "Domain must be at most 255 characters"),
			({**EMAIL, "admin_password": "password123"}, "Admin password is too easy to guess"),
			({**EMAIL, "admin_password": "a long line\nwith a break"}, "only printable characters"),
			({**EMAIL, "admin_password": "a long line\twith a tab"}, "only printable characters"),
			({**EMAIL, "shell": "rm -rf /"}, "This app has no setting shell"),
		):
			with self.subTest(answers=answers), self.assertRaisesRegex(frappe.ValidationError, message):
				_get_user_data(server_input(app_inputs=answers), requirements(APP_INPUTS))

	def test_an_input_name_must_be_a_shell_variable(self) -> None:
		inputs = [{"name": "bad-name", "label": "Bad"}]

		with self.assertRaisesRegex(frappe.ValidationError, "not a valid shell variable name"):
			_get_user_data(server_input(app_inputs={"bad-name": "value"}), requirements(inputs))

	def test_an_app_refuses_its_own_user_data(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			_get_user_data(server_input(user_data="#!/bin/sh"), requirements())

	def test_any_other_server_refuses_app_settings(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			_get_user_data(server_input(app_inputs={"password": "a" * 12}), None)

	def test_any_other_server_keeps_the_customer_user_data(self) -> None:
		self.assertEqual(_get_user_data(server_input(user_data="#!/bin/sh"), None), "#!/bin/sh")


@patch("central.integrations.images.Region.get_zone", return_value="region-a.example.com")
@patch("central.integrations.images.BlockedDomain.is_blocked", return_value=False)
@patch("central.integrations.images.frappe.get_all", return_value=[])
@patch("central.integrations.images.frappe.db.exists", return_value=None)
class TestAppSubdomain(TestCase):
	def test_the_site_name_answer_is_the_subdomain(self, *_mocks) -> None:
		self.assertEqual(get_app_subdomain("region-a", {"site_name": " metrics "}), "metrics")

	def test_an_app_without_a_site_name_has_no_subdomain(self, *_mocks) -> None:
		self.assertIsNone(get_app_subdomain("region-a", {"admin_email": "me@example.com"}))

	def test_a_site_name_must_be_a_dns_label(self, *_mocks) -> None:
		for name in ("Metrics", "my.site", "-metrics", "metrics_1"):
			with self.subTest(name=name), self.assertRaisesRegex(frappe.ValidationError, "lowercase letters"):
				get_app_subdomain("region-a", {"site_name": name})

	def test_a_routed_name_is_taken(self, exists, *_mocks) -> None:
		exists.side_effect = lambda doctype, _filters: doctype == "Site Domain"

		with self.assertRaisesRegex(frappe.ValidationError, "already taken"):
			get_app_subdomain("region-a", {"site_name": "metrics"})

	def test_a_name_a_pending_creation_holds_is_taken(self, exists, *_mocks) -> None:
		exists.side_effect = lambda doctype, _filters: doctype == "Resource Action"

		with self.assertRaisesRegex(frappe.ValidationError, "already taken"):
			get_app_subdomain("region-a", {"site_name": "metrics"})

		filters = next(call.args[1] for call in exists.call_args_list if call.args[0] == "Resource Action")
		self.assertEqual(
			{key: filters[key] for key in ("action", "region", "subdomain")},
			{"action": "create", "region": "region-a", "subdomain": "metrics"},
		)

	def test_a_name_a_site_chose_is_taken(self, _exists, get_all, *_mocks) -> None:
		get_all.return_value = [{"name": "site-1"}]

		with self.assertRaisesRegex(frappe.ValidationError, "already taken"):
			get_app_subdomain("region-a", {"site_name": "metrics"})

	def test_a_reserved_name_is_refused(self, _exists, _get_all, is_blocked, _zone) -> None:
		is_blocked.return_value = True

		with self.assertRaisesRegex(frappe.ValidationError, "reserved"):
			get_app_subdomain("region-a", {"site_name": "admin"})


VM_MODULE = "central.infrastructure.doctype.virtual_machine.virtual_machine"


def machine(**values) -> VirtualMachine:
	fields = {"doctype": "Virtual Machine", "name": "vm-1", "region": "region-a", "status": "Running"}
	return frappe.get_doc({**fields, "has_site": 0, "ipv6_address": "fd00::1", **values})


@patch(f"{VM_MODULE}.Region.get_zone", return_value="region-a.example.com")
@patch(f"{VM_MODULE}.frappe.enqueue_doc")
class TestAppSubdomainRoute(TestCase):
	def report(self, server: VirtualMachine, subdomain: str | None, previous_address: str | None) -> None:
		server._doc_before_save = machine(**{**server.as_dict(), "ipv6_address": previous_address})
		with patch(f"{VM_MODULE}.frappe.db.get_value", return_value=subdomain):
			server.on_update()

	def test_an_app_server_is_routed_when_it_first_gets_an_address(self, enqueue, _zone) -> None:
		self.report(machine(), "metrics", previous_address=None)

		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.args[:3], ("Virtual Machine", "vm-1", "route_app_subdomain"))
		self.assertEqual(enqueue.call_args.kwargs["domain"], "metrics.region-a.example.com")

	def test_a_later_report_does_not_route_again(self, enqueue, _zone) -> None:
		self.report(machine(), "metrics", previous_address="fd00::1")

		enqueue.assert_not_called()

	def test_nothing_is_routed_before_the_server_has_an_address(self, enqueue, _zone) -> None:
		self.report(machine(ipv6_address=None), "metrics", previous_address=None)

		enqueue.assert_not_called()

	def test_a_pilot_server_is_left_to_its_site(self, enqueue, _zone) -> None:
		self.report(machine(has_site=1), "metrics", previous_address=None)

		enqueue.assert_not_called()

	def test_a_server_without_a_site_name_is_not_routed(self, enqueue, _zone) -> None:
		self.report(machine(), None, previous_address=None)

		enqueue.assert_not_called()
